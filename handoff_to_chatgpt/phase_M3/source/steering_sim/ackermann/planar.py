"""PHASE M3：通用平面闭链机构求解器（新设计机构的运动学内核）。

甲方原始六桥机构（``mechanics_ackermann_v2``）的拓扑是**冻结**的：R02B 的
``SixAxleSteeringKinematics`` 里写死了每一组的构件名与连杆名。M3 的
``REDESIGNED_ACKERMANN_TRANSMISSION`` 是**另一套拓扑**（摆臂 → 中间摇臂 →
转向节，转向节之间加转向梯形），所以这里提供一个小而完整的平面闭链求解器，
**不改动** ``steering_sim.mechanics`` 里的任何既有模型。

数学与 R02B 的 ``_ClosedChainGroup`` 完全一致，便于对照：

* 每个刚体一个转角自由度，绕自身枢轴（主销/摇臂轴）转 ``+Z``；
* 每根刚性杆给出一条标量约束 ``|P_a(θ_a) − P_b(θ_b)| = L``；
* 再加一条坐标约束 ``mean(θ_c1, θ_c2) = q``（机构自由度）；
* 牛顿式最小二乘求解，解析雅可比，**以上一步的解为初值**从 ``q=0`` 连续延拓，
  出现分支跳变或残差超限即报错，绝不静默换分支。

角度约定：所有 ``θ`` 都是相对 ``q=0`` 零位的转角增量，单位 rad，正方向为 ``+Z``
逆时针。
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Sequence

import numpy as np
from scipy.optimize import least_squares

from steering_sim.mechanics.geometry2d import RigidBody2D, RigidLink2D

#: 装配残差上限（m）。与 R02B 一致。
RESIDUAL_TOLERANCE_M = 1.0e-10
#: 条件数上限：超过即认为接近奇异，必须显式失败。
SINGULAR_CONDITION_LIMIT = 1.0e10
#: 相邻步的最大构件角增量（rad）：超过即认为发生了装配分支跳变。
BRANCH_JUMP_LIMIT_RAD = 0.5


class PlanarChainError(RuntimeError):
    """平面闭链不可解、残差超限或发生分支跳变。"""


@dataclass(frozen=True, slots=True)
class ChainSolution:
    q_rad: float
    angles_rad: Mapping[str, float]
    residuals_m: Mapping[str, float]
    point_angles_rad: Mapping[str, float]
    condition_number: float
    singular: bool

    @property
    def max_residual_m(self) -> float:
        return max((abs(value) for value in self.residuals_m.values()), default=0.0)


@dataclass(frozen=True, slots=True)
class LinkageReport:
    """单个构件的传动角健康度（用于死点判据）。"""

    name: str
    min_toggle_margin_deg: float
    max_toggle_margin_deg: float


class PlanarClosedChain:
    """一组单自由度平面闭链（若干刚体 + 刚性杆约束 + 一个坐标约束）。

    ``bodies`` 的顺序即未知量顺序；``coordinate_bodies`` 的两个构件角度的算术
    平均值等于广义坐标 ``q``。约束数必须恰好等于刚体数。
    """

    def __init__(self, name: str, bodies: Sequence[RigidBody2D],
                 links: Sequence[RigidLink2D],
                 coordinate_bodies: tuple[str, str]) -> None:
        if len(bodies) != len(links) + 1:
            raise ValueError(
                f"{name}: 需要 len(links) = len(bodies) − 1，得到 "
                f"{len(bodies)} 个刚体与 {len(links)} 根杆")
        self.name = name
        self.bodies = tuple(bodies)
        self.links = tuple(links)
        self.body_index = {body.name: index for index, body in enumerate(self.bodies)}
        if len(self.body_index) != len(self.bodies):
            raise ValueError(f"{name}: 刚体名重复")
        for body_name in coordinate_bodies:
            if body_name not in self.body_index:
                raise ValueError(f"{name}: 坐标构件 {body_name!r} 不在刚体表中")
        if coordinate_bodies[0] == coordinate_bodies[1]:
            raise ValueError(f"{name}: 坐标必须由两个不同构件的平均角定义")
        self.coordinate_bodies = coordinate_bodies
        self._previous_q = 0.0
        self._previous = np.zeros(len(self.bodies))

    # ------------------------------------------------------------------ 内部
    @property
    def body_names(self) -> tuple[str, ...]:
        return tuple(body.name for body in self.bodies)

    @property
    def previous_q(self) -> float:
        """上一次成功求解用的广义坐标（连续延拓的热启动判据）。"""
        return float(self._previous_q)

    def reset(self) -> None:
        self._previous_q = 0.0
        self._previous = np.zeros(len(self.bodies))

    def seed(self, angles_rad: Mapping[str, float], q_rad: float = 0.0) -> None:
        self._previous = np.array([float(angles_rad[name]) for name in self.body_names])
        self._previous_q = float(q_rad)

    def _angles(self, x: np.ndarray) -> dict[str, float]:
        return dict(zip(self.body_names, map(float, x)))

    def _point(self, endpoint: tuple[str, str], angles: Mapping[str, float]) -> np.ndarray:
        body_name, point_id = endpoint
        return self.bodies[self.body_index[body_name]].world_point(
            point_id, angles[body_name])

    def residual_vector(self, q_rad: float, x: np.ndarray) -> np.ndarray:
        angles = self._angles(x)
        rows = [float(np.linalg.norm(self._point(link.endpoint_b, angles)
                                     - self._point(link.endpoint_a, angles))
                      - link.reference_length) for link in self.links]
        rows.append(0.5 * sum(angles[name] for name in self.coordinate_bodies) - q_rad)
        return np.asarray(rows, dtype=float)

    def _body_derivative(self, endpoint: tuple[str, str], angles: Mapping[str, float],
                         body_name: str) -> np.ndarray:
        owner, point_id = endpoint
        if owner != body_name:
            return np.zeros(2)
        return self.bodies[self.body_index[owner]].point_angle_derivative(
            point_id, angles[owner])

    def _column(self, q_rad: float, x: np.ndarray, body_name: str) -> np.ndarray:
        angles = self._angles(x)
        column = np.zeros(len(self.links) + 1)
        for row, link in enumerate(self.links):
            point_a = self._point(link.endpoint_a, angles)
            point_b = self._point(link.endpoint_b, angles)
            delta = point_b - point_a
            length = float(np.linalg.norm(delta))
            if length <= 1.0e-14:
                raise PlanarChainError(f"{link.name}: 两端点重合")
            d_a = self._body_derivative(link.endpoint_a, angles, body_name)
            d_b = self._body_derivative(link.endpoint_b, angles, body_name)
            column[row] = float(delta @ (d_b - d_a) / length)
        if body_name in self.coordinate_bodies:
            column[-1] = 0.5
        return column

    def jacobian(self, q_rad: float, x: np.ndarray) -> np.ndarray:
        return np.column_stack([self._column(q_rad, x, name)
                                for name in self.body_names])

    # ------------------------------------------------------------------ 求解
    def _newton(self, q_rad: float, x0: np.ndarray, iterations: int = 40):
        """方阵牛顿迭代：从上一构型出发，二次收敛，比通用最小二乘更快更准。"""
        x = np.asarray(x0, dtype=float).copy()
        residual = self.residual_vector(q_rad, x)
        best = (float(np.max(np.abs(residual))), x.copy())
        for _ in range(iterations):
            # 装配精度门限是 1e-10 m；到 1e-13 就没有必要再迭代，
            # 否则会在机器精度附近空转几十次，把优化目标函数拖慢一个量级。
            if best[0] <= 1.0e-13:
                break
            try:
                jacobian = self.jacobian(q_rad, x)
                step = np.linalg.solve(jacobian, -residual)
            except (np.linalg.LinAlgError, PlanarChainError):
                break
            if not np.all(np.isfinite(step)):
                break
            scale = 1.0
            improved = False
            for _ in range(12):
                trial = x + scale * step
                value = self.residual_vector(q_rad, trial)
                norm = float(np.max(np.abs(value)))
                if np.isfinite(norm) and norm < best[0]:
                    x, residual, best = trial, value, (norm, trial.copy())
                    improved = True
                    break
                scale *= 0.5
            if not improved:
                break
        return best[1], best[0]

    def solve(self, q_rad: float) -> ChainSolution:
        if not np.isfinite(q_rad):
            raise PlanarChainError(f"{self.name}: 广义坐标不是有限值")
        candidate, max_residual = self._newton(q_rad, self._previous)
        if max_residual > RESIDUAL_TOLERANCE_M:
            result = least_squares(
                lambda x: self.residual_vector(q_rad, x), candidate,
                jac=lambda x: self.jacobian(q_rad, x),
                xtol=1e-14, ftol=1e-14, gtol=1e-14, max_nfev=800)
            trial_residual = float(np.max(np.abs(
                self.residual_vector(q_rad, result.x)), initial=0.0))
            if np.all(np.isfinite(result.x)) and trial_residual < max_residual:
                candidate, max_residual = result.x, trial_residual
        if not np.all(np.isfinite(candidate)) or max_residual > RESIDUAL_TOLERANCE_M:
            raise PlanarChainError(
                f"{self.name}: 闭链不可解；最大装配残差 {max_residual:.3e} m")
        if abs(q_rad - self._previous_q) <= 0.1 and \
                float(np.max(np.abs(candidate - self._previous), initial=0.0)) > BRANCH_JUMP_LIMIT_RAD:
            raise PlanarChainError(f"{self.name}: 检测到装配分支跳变")
        jacobian = self.jacobian(q_rad, candidate)
        condition = float(np.linalg.cond(jacobian))
        singular = (not np.isfinite(condition)) or condition > SINGULAR_CONDITION_LIMIT
        if singular:
            sensitivity = np.full(len(self.bodies), np.nan)
        else:
            q_column = np.zeros(len(self.bodies))
            q_column[-1] = 1.0
            sensitivity = np.linalg.solve(jacobian, q_column)
        angles = self._angles(candidate)
        residual = self.residual_vector(q_rad, candidate)
        self._previous_q = float(q_rad)
        self._previous = candidate.copy()
        point_angles = {name: polyline_angle(self, angles, name)
                        for name in self.body_names}
        return ChainSolution(
            q_rad=float(q_rad), angles_rad=angles,
            residuals_m=dict(zip((link.name for link in self.links),
                                 map(float, residual[:-1]))),
            point_angles_rad=point_angles,
            condition_number=condition, singular=singular)


def polyline_angle(chain: PlanarClosedChain, angles: Mapping[str, float],
                   body_name: str) -> float:
    """构件自身相对零位的转角（与 ``angles_rad`` 相同，保留给可读性）。"""
    return float(angles[body_name])


# --------------------------------------------------------------- 死点判据
def coupler_rocker_relative_deg(point_a: np.ndarray, point_b: np.ndarray,
                                pivot_b: np.ndarray,
                                pivot_a: np.ndarray | None = None) -> float:
    """连杆相对摇杆的夹角（度），用于判断四杆是否接近死点。

    ``point_a``/``point_b`` 是连杆两端点，``pivot_b`` 是摇杆枢轴；传入
    ``pivot_a`` 时同时给出连杆相对曲柄的夹角，取两者中更危险的一个。
    """
    coupler = np.asarray(point_b, dtype=float) - np.asarray(point_a, dtype=float)
    rocker = np.asarray(point_b, dtype=float) - np.asarray(pivot_b, dtype=float)
    values = [_relative_deg(coupler, rocker)]
    if pivot_a is not None:
        crank = np.asarray(point_a, dtype=float) - np.asarray(pivot_a, dtype=float)
        values.append(_relative_deg(coupler, crank))
    return min(values, key=lambda value: min(abs(value), 180.0 - abs(value)))


def _relative_deg(first: np.ndarray, second: np.ndarray) -> float:
    a1 = np.degrees(np.arctan2(first[1], first[0]))
    a2 = np.degrees(np.arctan2(second[1], second[0]))
    return (a1 - a2 + 180.0) % 360.0 - 180.0


def toggle_margin_deg(value: float) -> float:
    """把相对夹角折算成"距死点的最小角度"。"""
    return min(abs(value), 180.0 - abs(value))


def build_bodies(pivots: Mapping[str, tuple[float, float]],
                 hardpoints: Mapping[str, Mapping[str, tuple[float, float]]]
                 ) -> dict[str, RigidBody2D]:
    """由**零位全局坐标**构造刚体：局部硬点 = 全局点 − 枢轴。"""
    bodies: dict[str, RigidBody2D] = {}
    for name, pivot in pivots.items():
        local = {
            point_id: (float(position[0]) - float(pivot[0]),
                       float(position[1]) - float(pivot[1]))
            for point_id, position in hardpoints.get(name, {}).items()
        }
        bodies[name] = RigidBody2D(name=name, pivot=(float(pivot[0]), float(pivot[1])),
                                   local_hardpoints=MappingProxyType(local))
    return bodies


def build_link(name: str, endpoint_a: tuple[str, str], endpoint_b: tuple[str, str],
               bodies: Mapping[str, RigidBody2D]) -> RigidLink2D:
    """由零位构型自动定长：两硬点零位距离即杆长。"""
    point_a = bodies[endpoint_a[0]].world_point(endpoint_a[1], 0.0)
    point_b = bodies[endpoint_b[0]].world_point(endpoint_b[1], 0.0)
    return RigidLink2D(name=name, endpoint_a=endpoint_a, endpoint_b=endpoint_b,
                       reference_length=float(np.linalg.norm(point_b - point_a)))
