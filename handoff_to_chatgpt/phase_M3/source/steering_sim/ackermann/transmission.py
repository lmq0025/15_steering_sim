"""PHASE M3：优化设计机构的双向传动接口。

任务书第九节要求机构模块提供两个**互为逆运算**的函数：

``target_angle_to_strokes()``
    输入一桥外侧目标转角 → 输出四个机构组的目标液压缸行程。
``strokes_to_wheel_angles()``
    输入四组实际液压缸行程 → 输出十二轮机械实际转角。

反算路径中**绝不调用原始目标角**：行程 → 机构坐标 → 闭链 → 轮角，全程只用
行程与机构几何，因此"目标角 → 行程 → 再反算"得到的轮角是真实的机构结果，
不是把目标角复制回来的假结果。

行程的单调性由机构组自身的连续延拓表保证；一旦代表行程在某个机构坐标处
折返（``ds/dq = 0``），反算即报错，绝不静默取分支。
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping

import numpy as np

from .redesign import (DOF_OF_GROUP, FRONT_CYLINDER, GROUP_OF_AXLE, LEGACY_SIDE,
                       WHEEL_ORDER)

FRONT_DOF = "q_front"
REAR_DOF = {"axle4": "q4", "axle5": "q5", "axle6": "q6"}
#: 每个机构组的代表缸（与 J0 的 ``rear_representative_cylinder`` 一致）。
REPRESENTATIVE = {"axle4": "axle4_A", "axle5": "axle5_A", "axle6": "axle6_A"}
#: 每个机构组的伴随缸（由同一机构坐标决定，不作为独立状态）。
COMPANION = {"axle4": "axle4_B", "axle5": "axle5_B", "axle6": "axle6_B"}


class TransmissionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class StrokeSolution:
    target_outer_angle_deg: float
    q_rad: Mapping[str, float]
    strokes_m: Mapping[str, float]
    wheel_angles_deg: Mapping[str, float]
    strokes_within_travel: bool
    stroke_limits_m: Mapping[str, tuple[float, float]]
    out_of_travel: tuple[str, ...]


def _monotone_inverse(grid: np.ndarray, values: np.ndarray, target: float,
                      name: str) -> float:
    """在严格单调的表上反插值。表不单调时显式失败。"""
    step = np.diff(values)
    if not (np.all(step > 0.0) or np.all(step < 0.0)):
        raise TransmissionError(f"{name}: 代表行程在该区间内不单调，无法唯一反算")
    if target < min(values[0], values[-1]) - 1.0e-12 or \
            target > max(values[0], values[-1]) + 1.0e-12:
        raise TransmissionError(
            f"{name}: 行程 {target * 1e3:.3f} mm 超出机构可达范围 "
            f"[{min(values) * 1e3:.3f}, {max(values) * 1e3:.3f}] mm")
    if step[0] > 0.0:
        return float(np.interp(target, values, grid))
    return float(np.interp(target, values[::-1], grid[::-1]))


class RedesignedTransmission:
    """新设计机构的双向传动映射（行程 ↔ 机构坐标 ↔ 十二轮转角）。"""

    def __init__(self, model) -> None:
        self.model = model
        self._tables: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        for dof in (FRONT_DOF, *REAR_DOF.values()):
            self._tables[dof] = self._stroke_table(dof)
        # 配置里同一段还放着说明性字段（字符串），只取真正的二元数值区间。
        limits = getattr(model, "config", {}).get("cylinder_travel_m", {})
        self.travel_limits = {
            name: (float(bounds[0]), float(bounds[1]))
            for name, bounds in limits.items()
            if isinstance(bounds, (list, tuple)) and len(bounds) == 2
            and all(isinstance(value, (int, float)) for value in bounds)}

    # -------------------------------------------------------------- 建表
    def _stroke_table(self, dof: str, samples: int = 400):
        """代表（A）缸行程 ↔ 机构坐标的表：正半轴延拓，负半轴镜像构造。"""
        from .redesign import mirror_angles

        key = {"q_front": "front", "q4": "axle4", "q5": "axle5", "q6": "axle6"}[dof]
        build = self.model.mechanism.builds[key]
        low, high = self.model.q_envelopes[dof]
        build.chain.reset()
        build.chain.solve(0.0)
        positive: list[tuple[float, dict]] = []
        q = 0.0
        step = max(high, abs(low)) / samples
        while q + step <= high + 1e-12:
            q_next = q + step
            try:
                solution = build.chain.solve(q_next)
            except Exception:
                break
            positive.append((q_next, dict(solution.angles_rad)))
            q = q_next
        if len(positive) < 4:
            raise TransmissionError(f"{dof}: 新机构连续延拓表不足")
        negative = [(-value, mirror_angles(angles)) for value, angles in positive]
        negative = [(value, angles) for value, angles in negative
                    if value >= min(low, 0.0) - 1.0e-12]
        zero = {name: 0.0 for name in build.chain.body_names}
        rows = list(reversed(negative)) + [(0.0, zero)] + positive
        grid = np.array([row[0] for row in rows], dtype=float)
        return grid, self._representative_strokes(key, rows)

    def _representative_strokes(self, key: str, rows) -> np.ndarray:
        """代表行程：前组为占位接口 ``x = 0.25 q``，后桥为对称双缸推程缸位移。"""
        from .redesign import representative_stroke_m
        grid = np.array([row[0] for row in rows], dtype=float)
        if key == "front":
            return self.model._front_stroke_per_q * grid
        axle = int(key[4:])
        return np.asarray(
            [representative_stroke_m(self.model.reference, axle, float(q),
                                     angles) for q, angles in rows], dtype=float)

    def q_span(self, dof: str) -> tuple[float, float]:
        grid, _ = self._tables[dof]
        return float(grid[0]), float(grid[-1])

    # ------------------------------------------------------ 目标角 → 行程
    def target_angle_to_strokes(self, target_outer_angle_deg: float) -> StrokeSolution:
        geometry = self.model.solve_geometry(float(target_outer_angle_deg))
        q_values = {dof: float(geometry.q_rad[dof])
                    for dof in (FRONT_DOF, *REAR_DOF.values())}
        state = self.model.mechanism_state(q_values)
        # 目标行程 = 四组**等效代表行程**（前组占位接口；后桥为对称双缸推程缸
        # 位移）。逐只缸的真实几何行程另在 seven_strokes() 里给出，两者不可混用：
        # 反算路径吃的必须是与建表时同一个量。
        representative = state.representative_stroke_m
        strokes = {FRONT_CYLINDER: float(representative["front"])}
        for key, _dof in REAR_DOF.items():
            strokes[REPRESENTATIVE[key]] = float(representative[key])
        out_of_travel = tuple(
            name for name, value in strokes.items()
            if name in self.travel_limits
            and not (self.travel_limits[name][0] - 1.0e-12 <= value
                     <= self.travel_limits[name][1] + 1.0e-12))
        limits = {name: self.travel_limits.get(name, (math.nan, math.nan))
                  for name in strokes}
        return StrokeSolution(
            target_outer_angle_deg=float(target_outer_angle_deg), q_rad=q_values,
            strokes_m=strokes, wheel_angles_deg=dict(state.wheel_angles_deg),
            strokes_within_travel=not out_of_travel, stroke_limits_m=limits,
            out_of_travel=out_of_travel)

    # ------------------------------------------------------ 行程 → 轮角
    def _stroke_at(self, key: str, axle: int, q_rad: float) -> float:
        """在机构坐标 q 处解一次闭链，返回**代表行程**（m）。

        必须与建表时用的是同一个量：后桥的代表行程是对称双缸的推程缸位移
        （q ≥ 0 用 A 缸、q < 0 用 B 缸），不是单只 A 缸的几何行程。
        """
        from .redesign import representative_stroke_m, solve_chain_continuation
        build = self.model.mechanism.builds[key]
        solution = solve_chain_continuation(build.chain, float(q_rad))
        return representative_stroke_m(self.model.reference, axle, float(q_rad),
                                       solution.angles_rad)

    def _invert_rear(self, key: str, dof: str, target: float) -> float:
        """表反插值给出初值，再用 brentq 精修到机器精度。

        表是分段的，直接用线性插值会有 O(Δq²) 的偏差（约 1e-4 rad），
        对"行程 → 轮角"的往返一致性来说太大。
        """
        from scipy.optimize import brentq

        grid, values = self._tables[dof]
        estimate = _monotone_inverse(grid, values, target, dof)
        span = float(grid[-1] - grid[0])
        window = max(0.02, 0.02 * span)
        low = max(float(grid[0]), estimate - window)
        high = min(float(grid[-1]), estimate + window)
        axle = int(key[4:])
        try:
            f_low = self._stroke_at(key, axle, low) - target
            f_high = self._stroke_at(key, axle, high) - target
        except Exception:
            return estimate
        if f_low == 0.0:
            return low
        if f_high == 0.0:
            return high
        if f_low * f_high > 0.0:
            return estimate
        return float(brentq(lambda q: self._stroke_at(key, axle, q) - target,
                            low, high, xtol=1e-13, rtol=1e-14, maxiter=200))

    def strokes_to_wheel_angles(self, strokes_m: Mapping[str, float]) -> dict[str, float]:
        """由四组实际行程反求十二轮转角；不读取任何目标角。"""
        for name in (FRONT_CYLINDER, *REPRESENTATIVE.values()):
            if name not in strokes_m:
                raise TransmissionError(f"缺少代表缸行程：{name}")
        q_values: dict[str, float] = {}
        front_target = float(strokes_m[FRONT_CYLINDER])
        grid, values = self._tables[FRONT_DOF]
        q_values[FRONT_DOF] = self._invert_front(grid, values, front_target)
        for key, dof in REAR_DOF.items():
            q_values[dof] = self._invert_rear(
                key, dof, float(strokes_m[REPRESENTATIVE[key]]))
        state = self.model.mechanism_state(q_values)
        return dict(state.wheel_angles_deg)

    @staticmethod
    def _invert_front(grid: np.ndarray, values: np.ndarray, target: float) -> float:
        return _monotone_inverse(grid, values, target, FRONT_DOF)

    # ------------------------------------------------------------ 行程限位
    def companion_strokes(self, q_values: Mapping[str, float]) -> dict[str, float]:
        state = self.model.mechanism_state(q_values)
        return {name: float(state.cylinder_stroke_m[name]) for name in COMPANION.values()}

    def seven_strokes(self, q_values: Mapping[str, float]) -> dict[str, float]:
        return dict(self.model.mechanism_state(q_values).cylinder_stroke_m)
