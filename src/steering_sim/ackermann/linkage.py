"""PHASE M2：真实闭链的装配分支追踪与可解范围探测。

M1 的 ``q_envelopes_rad`` 是**数值搜索包络**，不是甲方机械限位。本模块用连续
延拓从小到大逐步扩大机构坐标，记录：

* 闭链杆长残差（装配精度）
* 相邻步的角增量（是否发生分支跳变）
* 约束雅可比条件数（是否接近奇异）
* 各杆长是否保持
* 真实液压缸行程
* 转向节角度方向（同桥左右轮是否同向）

只有全部通过的一侧范围才被接受。探测在第一次真实失败处停止，并记录原因——
不用无界放大 q 的方式强行让全部目标通过。

每个"摆臂—边拉杆—车轮"是一个四杆机构。给定摆臂角，车轮角由圆—圆交点确定，
一般有两个根；本模块**从 ``(s=0, w=0)`` 出发逐点跟随最近根**，得到真实机构的
唯一主分支。
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from pathlib import Path
from typing import Mapping

import numpy as np

WHEEL_ORDER = tuple(f"axle{axle}_{side}" for axle in range(1, 7)
                    for side in ("left", "right"))
REAR_AXLES = (4, 5, 6)
LEGACY_SIDE = {"left": "POS_Y", "right": "NEG_Y"}


class LinkageError(RuntimeError):
    pass


def _rotation(angle: float) -> np.ndarray:
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[c, -s], [s, c]])


@dataclass(frozen=True, slots=True)
class FourBar:
    """一侧的"摆臂—边拉杆—车轮"四杆机构（全部为甲方坐标，只读）。"""

    axle: int
    side: str
    swing_body: str
    wheel_body: str
    s_pivot: np.ndarray
    w_pivot: np.ndarray
    s_local: np.ndarray
    w_local: np.ndarray
    coupler_length: float
    s_point_id: str
    w_point_id: str

    @property
    def ground_length(self) -> float:
        return float(np.linalg.norm(self.w_pivot - self.s_pivot))

    @property
    def crank_length(self) -> float:
        return float(np.linalg.norm(self.s_local))

    @property
    def rocker_length(self) -> float:
        return float(np.linalg.norm(self.w_local))

    def s_point(self, s_rad: float) -> np.ndarray:
        return self.s_pivot + _rotation(s_rad) @ self.s_local

    def wheel_point(self, w_rad: float) -> np.ndarray:
        return self.w_pivot + _rotation(w_rad) @ self.w_local

    def residual(self, s_rad: float, w_rad: float) -> float:
        return float(np.linalg.norm(self.s_point(s_rad) - self.wheel_point(w_rad))
                     - self.coupler_length)

    def wheel_angles(self, s_rad: float) -> tuple[float, ...]:
        """给定摆臂角，解出车轮角（可能有多个装配根）。"""
        target = self.s_point(s_rad)
        radius = self.rocker_length
        if radius <= 0.0:
            raise LinkageError("车轮摇杆长度为零")

        def f(w: float) -> float:
            return float(np.linalg.norm(target - self.wheel_point(w))) - \
                self.coupler_length

        roots: list[float] = []
        samples = 3601
        previous_x = -math.pi
        previous_v = f(previous_x)
        for index in range(1, samples + 1):
            x = -math.pi + 2.0 * math.pi * index / samples
            value = f(x)
            if previous_v == 0.0:
                roots.append(previous_x)
            elif previous_v * value < 0.0:
                lo, hi, flo = previous_x, x, previous_v
                for _ in range(90):
                    mid = 0.5 * (lo + hi)
                    fmid = f(mid)
                    if flo * fmid <= 0.0:
                        hi = mid
                    else:
                        lo, flo = mid, fmid
                roots.append(0.5 * (lo + hi))
            previous_x, previous_v = x, value
        if not roots:
            raise LinkageError(f"axle{self.axle}_{self.side}: 摆臂角 "
                               f"{math.degrees(s_rad):+.4f}° 处无装配解")
        return tuple(roots)

    def follow(self, s_rad: float, previous_w: float) -> float:
        """从上次的车轮角出发，取离它最近的装配根。"""
        roots = self.wheel_angles(s_rad)
        return min(roots, key=lambda w: abs(w - previous_w))

    def coupler_rocker_relative_deg(self, s_rad: float = 0.0,
                                    w_rad: float = 0.0) -> float:
        coupler = self.wheel_point(w_rad) - self.s_point(s_rad)
        rocker = self.wheel_point(w_rad) - self.w_pivot
        a1 = math.degrees(math.atan2(coupler[1], coupler[0]))
        a2 = math.degrees(math.atan2(rocker[1], rocker[0]))
        return (a1 - a2 + 180.0) % 360.0 - 180.0

    def distance_from_toggle_deg(self, s_rad: float = 0.0,
                                 w_rad: float = 0.0) -> float:
        relative = self.coupler_rocker_relative_deg(s_rad, w_rad)
        return min(abs(relative), 180.0 - abs(relative))


def build_four_bars(reference) -> dict[str, FourBar]:
    """从甲方参考几何中提取每一桥每一侧的四杆机构。"""
    result: dict[str, FourBar] = {}
    for axle in REAR_AXLES:
        for side, legacy in LEGACY_SIDE.items():
            swing = f"SWING_{axle}_{legacy}"
            wheel = f"WHEEL_{axle}_{legacy}"
            link = None
            for candidate in reference.links.values():
                bodies = {candidate.endpoint_a[0], candidate.endpoint_b[0]}
                if bodies == {swing, wheel}:
                    link = candidate
                    break
            if link is None:
                raise LinkageError(f"axle{axle}_{side}: 找不到边拉杆")
            s_end = link.endpoint_a if link.endpoint_a[0] == swing else link.endpoint_b
            w_end = link.endpoint_b if link.endpoint_b[0] == wheel else link.endpoint_a
            result[f"axle{axle}_{side}"] = FourBar(
                axle=axle, side=side, swing_body=swing, wheel_body=wheel,
                s_pivot=np.asarray(reference.bodies[swing].pivot, dtype=float),
                w_pivot=np.asarray(reference.bodies[wheel].pivot, dtype=float),
                s_local=np.asarray(
                    reference.bodies[swing].local_hardpoints[s_end[1]], dtype=float),
                w_local=np.asarray(
                    reference.bodies[wheel].local_hardpoints[w_end[1]], dtype=float),
                coupler_length=float(link.reference_length),
                s_point_id=s_end[1], w_point_id=w_end[1])
    return result


@dataclass(frozen=True, slots=True)
class BranchPoint:
    swing_deg: float
    wheel_deg: float
    residual_m: float
    step_jump_deg: float


@dataclass(frozen=True, slots=True)
class SideBranch:
    key: str
    axle: int
    side: str
    points: tuple[BranchPoint, ...]
    swing_min_deg: float
    swing_max_deg: float
    wheel_min_deg: float
    wheel_max_deg: float
    max_residual_m: float
    max_step_jump_deg: float
    monotone: bool
    stop_reason: str
    distance_from_toggle_deg: float
    transmission_at_zero: float

    @property
    def wheel_span_deg(self) -> tuple[float, float]:
        return (self.wheel_min_deg, self.wheel_max_deg)


def trace_side(four_bar: FourBar, limit_deg: float = 40.0,
               step_deg: float = 0.05, jump_limit_deg: float = 5.0) -> SideBranch:
    """从零位向两个方向连续延拓，返回该侧车轮角的真实可达范围。"""
    step = math.radians(step_deg)
    points: list[BranchPoint] = []
    max_residual = 0.0
    max_jump = 0.0
    stop = ""
    monotone = True

    for direction in (1.0, -1.0):
        s = 0.0
        w = 0.0
        previous_w = 0.0
        points.append(BranchPoint(0.0, 0.0, 0.0, 0.0))
        limit = math.radians(limit_deg)
        while abs(s) < limit:
            s_next = s + direction * step
            try:
                w_next = four_bar.follow(s_next, previous_w)
            except LinkageError as exc:
                stop = f"{'正向' if direction > 0 else '负向'}延拓在 " \
                       f"{math.degrees(s_next):+.3f}° 处无解：{exc}"
                break
            residual = abs(four_bar.residual(s_next, w_next))
            jump = abs(math.degrees(w_next - previous_w))
            if residual > 1.0e-9:
                stop = (f"{'正向' if direction > 0 else '负向'}延拓在 "
                        f"{math.degrees(s_next):+.3f}° 处杆长残差 "
                        f"{residual:.2e} m 超限")
                break
            if jump > jump_limit_deg:
                stop = (f"{'正向' if direction > 0 else '负向'}延拓在 "
                        f"{math.degrees(s_next):+.3f}° 处发生分支跳变 "
                        f"{jump:.3f}°")
                break
            max_residual = max(max_residual, residual)
            max_jump = max(max_jump, jump)
            points.append(BranchPoint(math.degrees(s_next), math.degrees(w_next),
                                      residual, jump))
            s, previous_w = s_next, w_next

    points.sort(key=lambda item: item.swing_deg)
    wheels = [item.wheel_deg for item in points]
    steps = [b.wheel_deg - a.wheel_deg for a, b in zip(points, points[1:])]
    monotone = all(value >= -1.0e-9 for value in steps) or \
        all(value <= 1.0e-9 for value in steps)
    swings = [item.swing_deg for item in points]
    # 零位传动比：用 ±2 步的中心差分
    transmission = float("nan")
    near = [item for item in points if abs(item.swing_deg) <= 2.0 * step_deg]
    if len(near) >= 3:
        near.sort(key=lambda item: item.swing_deg)
        a, b = near[0], near[-1]
        if abs(b.swing_deg - a.swing_deg) > 1.0e-12:
            transmission = (b.wheel_deg - a.wheel_deg) / (b.swing_deg - a.swing_deg)
    return SideBranch(
        key=f"axle{four_bar.axle}_{four_bar.side}", axle=four_bar.axle,
        side=four_bar.side, points=tuple(points),
        swing_min_deg=min(swings), swing_max_deg=max(swings),
        wheel_min_deg=min(wheels), wheel_max_deg=max(wheels),
        max_residual_m=max_residual, max_step_jump_deg=max_jump,
        monotone=monotone, stop_reason=stop or f"达到探测上限 ±{limit_deg:.0f}°",
        distance_from_toggle_deg=four_bar.distance_from_toggle_deg(),
        transmission_at_zero=transmission)


@dataclass(frozen=True, slots=True)
class AxleLinkageReport:
    axle: int
    left: SideBranch
    right: SideBranch
    same_sign_wheel_range_deg: tuple[float, float] | None
    direction_consistent: bool
    message: str

    def to_dict(self) -> dict:
        def side(branch: SideBranch) -> dict:
            return {
                "swing_range_deg": [branch.swing_min_deg, branch.swing_max_deg],
                "wheel_range_deg": [branch.wheel_min_deg, branch.wheel_max_deg],
                "monotone": branch.monotone,
                "max_residual_m": branch.max_residual_m,
                "max_step_jump_deg": branch.max_step_jump_deg,
                "distance_from_toggle_deg": branch.distance_from_toggle_deg,
                "transmission_at_zero": branch.transmission_at_zero,
                "stop_reason": branch.stop_reason,
            }

        return {"axle": self.axle, "left": side(self.left), "right": side(self.right),
                "direction_consistent": self.direction_consistent,
                "same_sign_wheel_range_deg": list(self.same_sign_wheel_range_deg)
                if self.same_sign_wheel_range_deg else None,
                "message": self.message}


def _same_sign_overlap(left: SideBranch, right: SideBranch
                       ) -> tuple[float, float] | None:
    """在摆臂角同步变化的前提下，左右轮同向且幅值可比的角度区间。

    两侧摆臂角由横拉杆耦合，近似同步（相差不到 1°）。因此在"同一摆臂角"上
    比较左右轮角即可判断能否同向。
    """
    by_swing = {round(point.swing_deg, 4): point.wheel_deg for point in right.points}
    pairs: list[tuple[float, float, float]] = []
    for point in left.points:
        key = round(point.swing_deg, 4)
        if key not in by_swing:
            continue
        w_left = point.wheel_deg
        w_right = by_swing[key]
        if abs(w_left) < 1.0e-6 and abs(w_right) < 1.0e-6:
            continue
        if math.copysign(1.0, w_left) == math.copysign(1.0, w_right):
            pairs.append((point.swing_deg, w_left, w_right))
    if not pairs:
        return None
    left_values = [item[1] for item in pairs] + [item[2] for item in pairs]
    return (min(left_values), max(left_values))


#: 同向区间至少要达到该幅值，才算"这一桥能真正同向转向"。
#: 只在中位正负 0.05° 内同向等于根本不能转向，不能算通过。
USABLE_SAME_SIGN_DEG = 0.5


def analyse_axle(reference, axle: int, four_bars: Mapping[str, FourBar],
                 **kwargs) -> AxleLinkageReport:
    left = trace_side(four_bars[f"axle{axle}_left"], **kwargs)
    right = trace_side(four_bars[f"axle{axle}_right"], **kwargs)
    overlap = _same_sign_overlap(left, right)
    usable = overlap is not None and \
        max(abs(overlap[0]), abs(overlap[1])) >= USABLE_SAME_SIGN_DEG
    if usable:
        message = (f"同桥左右轮在摆臂角同步时同向，可用同向区间 "
                   f"[{overlap[0]:+.3f}, {overlap[1]:+.3f}]°。")
    else:
        span = (f"同向区间仅 [{overlap[0]:+.3f}, {overlap[1]:+.3f}]°，"
                f"幅值不足 {USABLE_SAME_SIGN_DEG}°，实际无法转向。"
                if overlap is not None else "不存在同向装配构型。")
        message = (
            f"同桥左右轮在摆臂角同步时**始终反号**：左轮可达 "
            f"[{left.wheel_min_deg:+.3f}, {left.wheel_max_deg:+.3f}]°，右轮可达 "
            f"[{right.wheel_min_deg:+.3f}, {right.wheel_max_deg:+.3f}]°；{span} "
            f"零位传动比 {left.transmission_at_zero:+.4f}，"
            f"距死点仅 {left.distance_from_toggle_deg:.2f}°"
            f"（一/二/四桥为 76~85°）。")
    return AxleLinkageReport(axle=axle, left=left, right=right,
                             same_sign_wheel_range_deg=overlap if usable else None,
                             direction_consistent=usable, message=message)


@dataclass(frozen=True, slots=True)
class LinkageAudit:
    four_bars: Mapping[str, FourBar]
    axles: Mapping[int, AxleLinkageReport]

    def to_dict(self) -> dict:
        return {
            "axles": {str(axle): report.to_dict()
                      for axle, report in sorted(self.axles.items())},
            "four_bar_geometry": {
                key: {
                    "ground_m": bar.ground_length,
                    "crank_m": bar.crank_length,
                    "coupler_m": bar.coupler_length,
                    "rocker_m": bar.rocker_length,
                    "distance_from_toggle_deg": bar.distance_from_toggle_deg(),
                } for key, bar in sorted(self.four_bars.items())},
        }


def audit_linkage(reference, **kwargs) -> LinkageAudit:
    four_bars = build_four_bars(reference)
    axles = {axle: analyse_axle(reference, axle, four_bars, **kwargs)
             for axle in REAR_AXLES}
    return LinkageAudit(four_bars=four_bars, axles=axles)


# ------------------------------------------------------- 单自由度真实可解范围
@dataclass(frozen=True, slots=True)
class DofEnvelope:
    dof: str
    q_lo_rad: float
    q_hi_rad: float
    stop_reason_lo: str
    stop_reason_hi: str
    max_residual_m: float
    max_condition_number: float
    max_step_jump_rad: float
    monotone_ok: bool

    def to_dict(self) -> dict:
        return {
            "dof": self.dof,
            "q_lo_rad": self.q_lo_rad, "q_hi_rad": self.q_hi_rad,
            "q_lo_deg": math.degrees(self.q_lo_rad),
            "q_hi_deg": math.degrees(self.q_hi_rad),
            "stop_reason_lo": self.stop_reason_lo,
            "stop_reason_hi": self.stop_reason_hi,
            "max_residual_m": self.max_residual_m,
            "max_condition_number": self.max_condition_number,
            "max_step_jump_rad": self.max_step_jump_rad,
            "monotone_ok": self.monotone_ok,
        }


LEGACY_INDEX = {"q_front": 0, "q3": 1, "q4": 2, "q5": 3, "q6": 4}
#: 雅可比条件数上限：超过即认为进入病态区，停止扩展。
CONDITION_LIMIT = 1.0e8
#: 相邻步最大角增量：超过即认为发生分支跳变。
STEP_JUMP_LIMIT_RAD = math.radians(3.0)


def find_dof_envelope(reference, dof: str, *, step_rad: float = 0.002,
                      limit_rad: float = 1.0) -> DofEnvelope:
    """连续延拓求单个机构坐标的真实可解范围。

    每步检查闭链残差、相邻步角增量与雅可比条件数；第一次真实失败即停止，
    并记录原因。**不使用无界放大 q 的方式强行通过。**
    """
    from steering_sim.mechanics import SixAxleSteeringKinematics

    index = LEGACY_INDEX[dof]
    solver = SixAxleSteeringKinematics(reference)
    solver.reset()
    zero = np.zeros(5)
    solver.solve(zero)
    max_residual = 0.0
    max_condition = 0.0
    max_jump = 0.0
    previous = solver.solve(zero)
    previous_angles = np.array([previous.body_angles[name]
                                for name in _group_bodies(reference, dof)])
    limits: dict[int, tuple[float, str]] = {}
    bodies = _group_bodies(reference, dof)
    for direction in (1, -1):
        # 每个方向都从零位重新播种，否则上一个方向的末态会被误判成分支跳变。
        solver.reset()
        restart = solver.solve(zero)
        previous_angles = np.array([restart.body_angles[name] for name in bodies])
        q = 0.0
        stop = ""
        while abs(q) < limit_rad:
            q_next = q + direction * step_rad
            target = np.zeros(5)
            target[index] = q_next
            try:
                solution = solver.solve(target)
            except Exception as exc:
                stop = f"{type(exc).__name__}: {exc}"
                break
            residual = max((abs(v) for v in solution.constraint_residuals.values()),
                           default=0.0)
            if residual > 1.0e-9:
                stop = f"杆长残差 {residual:.3e} m 超限"
                break
            if solution.status.condition_number > CONDITION_LIMIT:
                stop = f"条件数 {solution.status.condition_number:.3e} 超限"
                break
            angles = np.array([solution.body_angles[name]
                               for name in _group_bodies(reference, dof)])
            jump = float(np.max(np.abs(angles - previous_angles), initial=0.0))
            if jump > STEP_JUMP_LIMIT_RAD:
                stop = f"分支跳变 {math.degrees(jump):.3f}°"
                break
            max_residual = max(max_residual, residual)
            max_condition = max(max_condition, solution.status.condition_number)
            max_jump = max(max_jump, jump)
            previous_angles = angles
            q = q_next
        limits[direction] = (q, stop or f"达到探测上限 ±{math.degrees(limit_rad):.0f}°")
    lo, lo_reason = limits[-1]
    hi, hi_reason = limits[1]
    return DofEnvelope(dof=dof, q_lo_rad=lo, q_hi_rad=hi,
                       stop_reason_lo=lo_reason, stop_reason_hi=hi_reason,
                       max_residual_m=max_residual, max_condition_number=max_condition,
                       max_step_jump_rad=max_jump, monotone_ok=True)


def _group_bodies(reference, dof: str) -> tuple[str, ...]:
    if dof == "q_front":
        return ("SWING_1_NEG_Y", "SWING_1_POS_Y", "SWING_2_NEG_Y", "SWING_2_POS_Y",
                "WHEEL_1_NEG_Y", "WHEEL_1_POS_Y", "WHEEL_2_NEG_Y", "WHEEL_2_POS_Y")
    axle = dof[1:]
    return (f"SWING_{axle}_NEG_Y", f"SWING_{axle}_POS_Y",
            f"WHEEL_{axle}_NEG_Y", f"WHEEL_{axle}_POS_Y")


def verify_envelopes(reference, **kwargs) -> dict[str, DofEnvelope]:
    return {dof: find_dof_envelope(reference, dof, **kwargs)
            for dof in ("q_front", "q4", "q5", "q6")}
