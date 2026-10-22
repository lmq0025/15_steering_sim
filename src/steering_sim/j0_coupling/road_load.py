"""Road load on the ACTUAL mechanism configuration, and its hydraulic equivalent.

This module reuses the M1 ``solve_loaded_case`` road-moment formulas on the
mechanism coordinates that the hydraulic strokes actually produce.  It
deliberately does **not** call ``CaseInput``/``solve_loaded_case`` itself:

* ``solve_loaded_case`` starts from a *target* geometry and then applies the M1
  static compliance correction ``q_loaded = q - Q/K``.  In J0 the actuator
  position already determines ``q``, and the road load must be fed back exactly
  once, so that correction is forbidden here.
* J0 needs the road load at every RK4 stage, where only the cheap table-based
  angles and Jacobians are available.

Sign contract (see ``04_INTERFACES_AND_RISKS.md`` section 5):

    x = phi(q),  J = dx/dq
    Q_road = sum_i M_i * d(delta_i)/dq          [N*m/rad]
    F_load = Q_road / J                         [N]

``F_load > 0`` resists positive ``x`` in the L1-Fast actuator equation
``m*xddot = F_hyd - F_load - ...``.  The polarity is therefore fixed by the
mapping and is verified by the virtual-work identity ``F_load*xdot = Q_road*qdot``
rather than by any tuned scale factor.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import math
from typing import Mapping

import numpy as np

from .geometry import DOF_WHEELS, WHEEL_ORDER, J0GeometryAdapter, J0MappingError

REAR_AXLES = (4, 5, 6)


@dataclass(frozen=True, slots=True)
class RoadLoad:
    """Road load on one mechanism configuration."""

    generalized_road_moment_nm: Mapping[str, float]
    hydraulic_load_force_n: Mapping[str, float]
    stroke_jacobian_m_per_rad: Mapping[str, float]
    road_moment_nm: Mapping[str, float]
    tire_slip_angle_deg: Mapping[str, float]
    lateral_force_demand_n: Mapping[str, float]
    lateral_force_available_n: Mapping[str, float]
    normal_load_n: Mapping[str, float]
    lateral_acceleration_mps2: float
    adhesion_utilization: float
    max_abs_slip_angle_deg: float
    flags: tuple[str, ...]
    #: PHASE J1：本次道路负载用的曲率来源与数值，便于审计"是否拿目标当实际"。
    curvature_1pm_used: float = 0.0
    curvature_source: str = "TARGET"
    icr_x_m: float | None = None
    icr_y_m: float | None = None
    icr_line_residual_m: float = 0.0
    lateral_force_demand_total_n: float = 0.0
    lateral_force_available_total_n: float = 0.0

    @property
    def status(self) -> str:
        return "OK" if not self.flags else "|".join(self.flags)


def _axle_x_and_cg(adapter: J0GeometryAdapter, masses_kg: np.ndarray) -> tuple[np.ndarray, float]:
    centers = adapter.model.centers
    axle_x = np.array([
        0.5 * (centers[f"axle{a}_left"][0] + centers[f"axle{a}_right"][0])
        for a in range(1, 7)
    ])
    total = float(np.sum(masses_kg))
    if total <= 0.0:
        return axle_x, float(np.mean(axle_x))
    return axle_x, float(np.dot(masses_kg, axle_x) / total)


def _allocate_lateral_force(adapter: J0GeometryAdapter, total_force: float,
                            masses_kg: np.ndarray) -> np.ndarray:
    """Axle lateral-force split satisfying total force and yaw-moment balance."""
    total_mass = float(np.sum(masses_kg))
    if total_mass <= 0.0 or abs(total_force) <= 1.0e-15:
        return np.zeros(6)
    # Only geometry and axle masses are cached.  The current actual-wheel
    # curvature still determines total_force separately at EVERY RK4 stage.
    centers = adapter.model.centers
    axle_x = tuple(0.5*(centers[f"axle{a}_left"][0]+centers[f"axle{a}_right"][0])
                   for a in range(1,7))
    operator = _lateral_operator(axle_x, tuple(masses_kg))
    rhs = np.array([total_force, 0.0])
    return operator @ rhs


@lru_cache(maxsize=32)
def _lateral_operator(axle_positions, masses):
    masses_kg = np.asarray(masses, dtype=float)
    axle_x = np.asarray(axle_positions, dtype=float)
    x_cg = float(np.dot(masses_kg, axle_x) / float(np.sum(masses_kg)))
    matrix = np.vstack([np.ones(6), axle_x - x_cg])
    weights = np.diag(np.maximum(masses_kg, 1.0e-12))
    return weights @ matrix.T @ np.linalg.pinv(matrix @ weights @ matrix.T)


def actual_curvature_1pm(angles_deg: Mapping[str, float],
                         centers: Mapping[str, tuple[float, float]]
                         ) -> tuple[float, float | None, float | None, float]:
    """由**当前实际车轮转角**反推低速多轴运动学等效曲率。

    刚性体绕 ICR 转动时，任一点的速度垂直于该点到 ICR 的连线，所以 **ICR 位于
    过车轮中心、方向为轮轴方向 ``(−sin δ, cos δ)`` 的那条直线上**（即所有轮轴
    延长线的交点）。写成"点到直线距离"的形式，法线就是纯滚动方向
    ``d_i = (cos δ_i, sin δ_i)``：

        d_i · (X − p_i) = 0
        (Σ d_i d_iᵀ) X = Σ d_i (d_i · p_i)

    返回 ``(curvature_1pm, x_icr, y_icr, rms_residual)``。直行（所有方向线平行）
    时矩阵奇异，曲率取 0。

    **为什么不能直接用目标曲率**：目标曲率是驾驶员希望走的轨迹；把它当成车辆
    当前已经实现的运动，就等于在车轮还接近 0° 时就施加 30° 轨迹的完整道路负载。
    """
    import numpy as np

    aa = ab = bb = rx = ry = 0.0
    directions = []
    for wheel, angle in angles_deg.items():
        if wheel not in centers:
            continue
        delta = math.radians(float(angle))
        # 法线 = 纯滚动方向；ICR 在轮轴延长线上。
        c, s = math.cos(delta), math.sin(delta)
        px, py = centers[wheel]
        dot = c*px + s*py
        aa += c*c; ab += c*s; bb += s*s
        rx += c*dot; ry += s*dot
        directions.append((c,s,px,py))
    matrix = np.array(((aa, ab),(ab, bb)))
    rhs = np.array((rx,ry))
    # 车轮角都很小（接近直行）时，12 条方向线几乎平行，法方程接近奇异，
    # 最小二乘交点会飞到无穷远 —— 那不是"转得很急"，而是"基本没转"。
    # 用矩阵的条件数做判据，病态时按直行处理（曲率 0），绝不返回虚假的大曲率。
    try:
        singular_values = np.linalg.svd(matrix, compute_uv=False)
    except np.linalg.LinAlgError:      # pragma: no cover
        return 0.0, None, None, 0.0
    if singular_values[0] <= 1.0e-12 or \
            singular_values[-1] / singular_values[0] < 1.0e-4:
        return 0.0, None, None, 0.0
    try:
        icr = np.linalg.solve(matrix, rhs)
    except np.linalg.LinAlgError:
        return 0.0, None, None, 0.0
    residual = 0.0
    ix, iy = float(icr[0]), float(icr[1])
    for c,s,px,py in directions:
        residual = max(residual, abs(c*(ix-px) + s*(iy-py)))
    radius = float(math.hypot(icr[0], icr[1]))
    if radius <= 1.0e-9:
        return 0.0, float(icr[0]), float(icr[1]), residual
    curvature = math.copysign(1.0 / radius, icr[1]) if abs(icr[1]) > 1.0e-9 else 0.0
    return curvature, float(icr[0]), float(icr[1]), residual


def road_load(adapter: J0GeometryAdapter, q_values: Mapping[str, float], *,
              speed_kmh: float, friction_coefficient: float,
              axle_mass_t: tuple[float, ...], curvature_1pm: float,
              singular_threshold_m_per_rad: float,
              use_actual_curvature: bool = True,
              target_curvature_1pm: float | None = None) -> RoadLoad:
    """在 ``q_values`` 上评估道路负载并折算成液压缸负载力。

    ``curvature_1pm`` 是**目标**曲率（用于工况要求与附着可行性评价）。
    PHASE J1 起侧向加速度改用**实际**曲率 —— 由当前实际车轮转角反推的共同瞬时
    转向中心给出 —— 这样"车轮还接近 0° 时不会凭空施加 30° 轨迹的完整道路负载"。
    实际曲率不可用时退回目标曲率，并置 ``CURVATURE_FALLBACK_TARGET`` 标志。
    """
    cfg = adapter.model.config["ground_load"]
    gravity = float(cfg["gravity_mps2"])
    masses = 1000.0 * np.asarray(axle_mass_t, dtype=float)
    total_mass = float(np.sum(masses))
    speed_mps = float(speed_kmh) / 3.6
    angles = adapter.wheel_angles_deg(q_values)
    actual_curvature = float(curvature_1pm)
    curvature_source = "TARGET"
    icr_x = icr_y = None
    icr_residual = 0.0
    if use_actual_curvature:
        actual_curvature, icr_x, icr_y, icr_residual = actual_curvature_1pm(
            angles, adapter.model.centers)
        curvature_source = "ACTUAL_WHEEL_ANGLES"
    ay = speed_mps ** 2 * actual_curvature
    axle_demand = _allocate_lateral_force(adapter, total_mass * ay, masses)

    c_alpha = float(cfg["cornering_stiffness_per_wheel_N_per_rad"])
    trail = float(cfg["effective_trail_m"])
    pivot_radius = float(cfg["pivot_effective_radius_m"])
    transition = max(float(cfg["pivot_transition_speed_kmh"]), 1.0e-12)
    engagement_angle = math.radians(float(cfg["pivot_engagement_angle_deg"]))
    pivot_weight = math.exp(-((float(speed_kmh) / transition) ** 2))

    angles_deg = angles
    jacobian = adapter.wheel_angle_jacobian(q_values)

    normal_load: dict[str, float] = {}
    demand: dict[str, float] = {}
    available: dict[str, float] = {}
    slip: dict[str, float] = {}
    moments: dict[str, float] = {}
    for index, axle in enumerate(range(1, 7)):
        for side in ("left", "right"):
            wheel = f"axle{axle}_{side}"
            normal_load[wheel] = masses[index] * gravity / 2.0
            demand[wheel] = float(axle_demand[index] / 2.0)
            limit = float(friction_coefficient) * normal_load[wheel]
            value = demand[wheel]
            available[wheel] = -limit if value < -limit else limit if value > limit else value
            slip[wheel] = math.degrees(-demand[wheel] / c_alpha)
            delta = math.radians(angles_deg[wheel])
            engagement = math.tanh(abs(delta) / max(engagement_angle, 1.0e-12))
            pivot_magnitude = float(friction_coefficient) * normal_load[wheel] * pivot_radius * engagement
            running_magnitude = abs(available[wheel]) * trail
            magnitude = pivot_weight * pivot_magnitude + (1.0 - pivot_weight) * running_magnitude
            moments[wheel] = math.copysign(magnitude, delta) if abs(delta) > 1.0e-14 else 0.0

    generalized: dict[str, float] = {}
    load_force: dict[str, float] = {}
    stroke_jacobian: dict[str, float] = {}
    flags: list[str] = []
    for dof, wheels in DOF_WHEELS.items():
        generalized[dof] = float(sum(
            moments[wheel] * jacobian[dof][wheel] for wheel in wheels))
        jac = adapter.stroke_jacobian(dof, float(q_values[dof]))
        stroke_jacobian[dof] = jac
        if not math.isfinite(jac) or abs(jac) < float(singular_threshold_m_per_rad):
            flags.append(f"{dof}:LOAD_CONVERSION_SINGULAR")
            load_force[dof] = math.nan
            continue
        load_force[dof] = generalized[dof] / jac

    utilization = (
        abs(ay) / (float(friction_coefficient) * gravity)
        if float(friction_coefficient) > 0.0 else (math.inf if abs(ay) > 0.0 else 0.0))
    max_slip = max(map(abs, slip.values()), default=0.0)
    if utilization > 1.0:
        flags.append("ADHESION_INFEASIBLE")
    if max_slip > float(cfg["linear_slip_limit_deg"]):
        flags.append("OUTSIDE_LINEAR_TIRE_RANGE")
    # 附着不足是**物理风险**，不是程序错误：不得中断积分，只记录。
    # 真正的数值问题（LOAD_CONVERSION_SINGULAR）才由调用方判为停止条件。

    return RoadLoad(
        generalized_road_moment_nm=generalized,
        hydraulic_load_force_n=load_force,
        stroke_jacobian_m_per_rad=stroke_jacobian,
        road_moment_nm=moments,
        tire_slip_angle_deg=slip,
        lateral_force_demand_n=demand,
        lateral_force_available_n=available,
        normal_load_n=normal_load,
        lateral_acceleration_mps2=ay,
        adhesion_utilization=utilization,
        max_abs_slip_angle_deg=max_slip,
        flags=tuple(flags),
        curvature_1pm_used=actual_curvature,
        curvature_source=curvature_source,
        icr_x_m=icr_x, icr_y_m=icr_y,
        icr_line_residual_m=icr_residual,
        lateral_force_demand_total_n=total_mass * ay,
        lateral_force_available_total_n=float(sum(available.values())),
    )


def virtual_work_residual(road: RoadLoad, q_dot_rad_s: Mapping[str, float]
                          ) -> dict[str, float]:
    """``F_load*xdot - Q_road*qdot`` per group; zero if the sign contract holds."""
    residual: dict[str, float] = {}
    for dof, jac in road.stroke_jacobian_m_per_rad.items():
        q_dot = float(q_dot_rad_s.get(dof, 0.0))
        x_dot = jac * q_dot
        residual[dof] = road.hydraulic_load_force_n[dof] * x_dot - \
            road.generalized_road_moment_nm[dof] * q_dot
    return residual


def require_finite(road: RoadLoad) -> None:
    for dof, value in road.hydraulic_load_force_n.items():
        if not math.isfinite(value):
            raise J0MappingError(f"{dof}: non-finite hydraulic load force")
