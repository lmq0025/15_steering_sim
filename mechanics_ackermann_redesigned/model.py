"""PHASE M3：``REDESIGNED_ACKERMANN_TRANSMISSION`` 机械模型。

本包是 PHASE M3 新增的**工程设计提案**模型，与 ``mechanics_ackermann_v2``
（甲方原始结构的 ``AS_BUILT_REFERENCE``）并存、互不覆盖：

* ``mechanics_ackermann_v2``  ：甲方原始铰点与原始杆件拓扑，只读对照；
* ``mechanics_ackermann_redesigned``：在不改动甲方任何原始坐标的前提下，
  增加中间摇臂与**转向节之间的阿克曼转向梯形**，重新建立
  "液压缸行程 → 摆臂角度 → 车轮转角"的关系。

对外接口刻意与 ``PhaseM1Model`` 保持一致（``centers`` / ``config`` /
``reference`` / ``ideal_ackermann`` / ``solve_geometry`` / ``mechanism_state``），
因此 J0 集成层可以用同一套代码驱动两种机构。

**所有新增点都是工程新设计点**，不是甲方实测硬点；本模型输出的任何角度都
不得被表述为"原车已验证的机械结构结果"。
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from steering_sim.ackermann.state import MechanismState
from steering_sim.ackermann.redesign import (DOF_OF_GROUP, LEGACY_SIDE,
                                             REDESIGN_TAG, WHEEL_ORDER,
                                             RedesignedMechanism, RedesignError,
                                             load_redesign_parameters,
                                             cylinder_stroke_m)
from steering_sim.mechanics import reference_geometry_from_file

# 复用 M1 的数据容器：它们只是不可变的结果结构，复用可以保证两种机构
# 输出字段完全一致，下游不需要分支。
from mechanics_ackermann_v2.model import (CaseInput, GeometryResult,
                                          LoadedCaseResult)

DOF_ORDER = ("q_front", "q4", "q5", "q6")
REAR_AXLES = (4, 5, 6)
FRONT_CYLINDER = "front_group_1"
REAR_CYLINDER_SIDE = {"A": "right", "B": "left"}


def load_config(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema_version") != "M3.0":
        raise ValueError("unsupported PHASE M3 configuration schema")
    return data


class RedesignedAckermannModel:
    """新设计机构模型。"""

    tag = REDESIGN_TAG

    def __init__(self, geometry_path: str | Path, config_path: str | Path,
                 design_path: str | Path | None = None) -> None:
        self.geometry_path = Path(geometry_path)
        self.config_path = Path(config_path)
        self.config = load_config(self.config_path)
        self.reference = reference_geometry_from_file(self.geometry_path)
        design_file = Path(design_path) if design_path is not None else \
            self.config_path.parent / "design_parameters.json"
        self.design_path = design_file
        self.parameters = load_redesign_parameters(design_file)
        self.centers = self._wheel_centers()
        self.mechanism = RedesignedMechanism(self.reference, self.parameters)
        self._table_cache: dict[str, tuple] = {}
        self._geometry_cache: dict[float, GeometryResult] = {}
        self._front_stroke_per_q = float(
            self.config["front_cylinder_interface"]["stroke_per_q_mm_per_rad"]) / 1000.0
        self._validate_customer_geometry()

    # ------------------------------------------------------------- 基本量
    def _wheel_centers(self) -> dict[str, tuple[float, float]]:
        centers: dict[str, tuple[float, float]] = {}
        for axle in range(1, 7):
            for side, legacy in (("left", "POS_Y"), ("right", "NEG_Y")):
                pivot = self.reference.bodies[f"WHEEL_{axle}_{legacy}"].pivot
                centers[f"axle{axle}_{side}"] = (float(pivot[0]), float(pivot[1]))
        return centers

    def _validate_customer_geometry(self) -> None:
        """确认甲方原始硬点没有被本轮设计改动。"""
        point = self.reference.points["P20_SRC"].position
        expected = np.array(self.config["geometry"]["third_axle_point20_mm"]) / 1000.0
        if not np.allclose(point, expected, atol=1.0e-12):
            raise ValueError(
                f"CUSTOMER point 20 changed: got {point}, expected {expected} m")
        if not self.config["geometry"]["third_axle_locked"]:
            raise ValueError("PHASE M3 requires axle 3 to remain locked")

    @property
    def q_envelopes(self) -> dict[str, tuple[float, float]]:
        return {dof: (float(bounds[0]), float(bounds[1]))
                for dof, bounds in self.config["geometry"]["q_envelopes_rad"].items()}

    # --------------------------------------------------------- 理想阿克曼
    def ideal_ackermann(self, target_outer_angle_deg: float) -> tuple:
        """与 M1 完全一致的共同 ICR 公式（三桥横线定 ICR）。"""
        target_rad = math.radians(float(target_outer_angle_deg))
        x_icr = 0.5 * (self.centers["axle3_left"][0] + self.centers["axle3_right"][0])
        if abs(target_rad) <= 1.0e-14:
            return None, x_icr, None, None, 0.0, {wheel: 0.0 for wheel in WHEEL_ORDER}
        outer = "axle1_right" if target_rad > 0.0 else "axle1_left"
        x_outer, y_outer = self.centers[outer]
        y_icr = y_outer + (x_outer - x_icr) / math.tan(target_rad)
        if math.copysign(1.0, y_icr) != math.copysign(1.0, target_rad):
            raise ValueError("target outer angle produces an ICR on the wrong side")
        angles = {wheel: self._axis_equivalent(math.atan2(x - x_icr, y_icr - y))
                  for wheel, (x, y) in self.centers.items()}
        angles["axle3_left"] = 0.0
        angles["axle3_right"] = 0.0
        radius = abs(y_icr)
        curvature = math.copysign(1.0 / radius, target_rad)
        return outer, x_icr, y_icr, radius, curvature, angles

    @staticmethod
    def _axis_equivalent(angle: float) -> float:
        while angle > math.pi / 2:
            angle -= math.pi
        while angle < -math.pi / 2:
            angle += math.pi
        return angle

    def curvature_1pm(self, target_outer_angle_deg: float) -> float:
        return float(self.ideal_ackermann(target_outer_angle_deg)[4])

    # ------------------------------------------------------------ 机构状态
    def mechanism_state(self, q_values: Mapping[str, float]) -> MechanismState:
        state = self.mechanism.solve(q_values)
        strokes: dict[str, float] = {
            FRONT_CYLINDER: self._front_stroke_per_q * float(q_values["q_front"])}
        representative: dict[str, float] = {
            "front": strokes[FRONT_CYLINDER]}
        for axle in REAR_AXLES:
            group = state.groups[f"axle{axle}"]
            for side_letter, side in REAR_CYLINDER_SIDE.items():
                swing = float(group.body_angles_rad[f"SWING_{axle}_{LEGACY_SIDE[side]}"])
                strokes[f"axle{axle}_{side_letter}"] = cylinder_stroke_m(
                    self.reference, axle, side, swing)
            representative[f"axle{axle}"] = float(
                group.representative_stroke_m)
        return MechanismState(
            q_rad={dof: float(q_values[dof]) for dof in DOF_ORDER},
            wheel_angles_rad=dict(state.wheel_angles_rad),
            wheel_angles_deg=dict(state.wheel_angles_deg),
            cylinder_stroke_m=strokes,
            representative_stroke_m=representative,
            max_residual_m=state.max_residual_m,
            condition_number=state.max_condition_number,
            singular=state.max_condition_number > 1.0e8,
            third_axle_max_abs_deg=state.third_axle_max_abs_deg,
            min_toggle_margin_deg=state.min_toggle_margin_deg)

    def reset(self) -> None:
        self.mechanism.reset()

    # ------------------------------------------------------------- 目标拟合
    def _q_table(self, dof: str, samples: int = 400):
        """机构组的 q → 轮角表（构造后缓存，只算一次）。

        只对 ``q ≥ 0`` 做连续延拓；``q < 0`` 由**镜像恒等式**构造
        （见 :func:`steering_sim.ackermann.redesign.mirror_angles`）。
        这样既快，又彻底避免负半轴上的数值分支跟踪失败——实测过负向扫描会在
        某个 q 处跳到另一个装配分支，而正向可以一直走到包络边缘。
        """
        cached = self._table_cache.get(dof)
        if cached is not None:
            return cached
        from steering_sim.ackermann.redesign import mirror_angles
        key = {"q_front": "front", "q4": "axle4", "q5": "axle5", "q6": "axle6"}[dof]
        build = self.mechanism.builds[key]
        low, high = self.q_envelopes[dof]
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
            raise RedesignError(f"{dof}: 新机构正向连续延拓表不足，无法拟合目标角")
        negative = [(-value, mirror_angles(angles)) for value, angles in positive]
        negative = [(value, angles) for value, angles in negative
                    if value >= min(low, 0.0) - 1.0e-12]
        zero = {name: 0.0 for name in build.chain.body_names}
        rows = list(reversed(negative)) + [(0.0, zero)] + positive
        q_array = np.array([row[0] for row in rows], dtype=float)
        angles = {wheel: np.array([row[1][body] for row in rows], dtype=float)
                  for body, wheel in build.wheels.items()}
        self._table_cache[dof] = (q_array, angles)
        return q_array, angles

    def solve_geometry(self, target_outer_angle_deg: float) -> GeometryResult:
        # 全工况表里同一个目标角会出现 17×3 = 51 次，纯几何结果与车速/摩擦系数
        # 无关，所以按目标角缓存（只影响速度，不影响任何数值）。
        key = float(target_outer_angle_deg)
        cached = self._geometry_cache.get(key)
        if cached is not None:
            return cached
        result = self._solve_geometry(key)
        self._geometry_cache[key] = result
        return result

    def _solve_geometry(self, target_outer_angle_deg: float) -> GeometryResult:
        target_rad = math.radians(float(target_outer_angle_deg))
        outer, x_icr, y_icr, radius, curvature, ideal_rad = self.ideal_ackermann(
            target_outer_angle_deg)
        q_values: dict[str, float] = {}
        boundaries: dict[str, bool] = {}
        for dof in DOF_ORDER:
            q_array, angles = self._q_table(dof)
            wheels = [wheel for wheel in angles]
            if outer is not None and dof == "q_front" and outer in angles:
                cost = (angles[outer] - target_rad) ** 2
            else:
                cost = np.zeros_like(q_array)
                for wheel in wheels:
                    cost += (angles[wheel] - ideal_rad[wheel]) ** 2
            index = int(np.argmin(cost))
            boundary = index in (0, len(q_array) - 1)
            if boundary:
                q_value = float(q_array[index])
            else:
                xs = q_array[index - 1:index + 2]
                ys = cost[index - 1:index + 2]
                coefficient = np.polyfit(xs, ys, 2)
                if coefficient[0] <= 0.0:
                    q_value = float(q_array[index])
                else:
                    q_value = float(np.clip(
                        -coefficient[1] / (2.0 * coefficient[0]), xs[0], xs[-1]))
            q_values[dof] = q_value
            boundaries[dof] = boundary
        state = self.mechanism_state(q_values)
        theoretical_rad = dict(state.wheel_angles_rad)
        ideal_deg = {wheel: math.degrees(value) for wheel, value in ideal_rad.items()}
        theoretical_deg = {wheel: math.degrees(value)
                           for wheel, value in theoretical_rad.items()}
        error_deg = {wheel: theoretical_deg[wheel] - ideal_deg[wheel]
                     for wheel in WHEEL_ORDER}

        fit_limit = float(self.config["geometry"]["fit_residual_limit_deg"])
        flags: list[str] = []
        classes: set[str] = set()
        for dof in DOF_ORDER:
            key = {"q_front": "front", "q4": "axle4", "q5": "axle5", "q6": "axle6"}[dof]
            axles = self.parameters.groups[key].axles
            wheels = [f"axle{axle}_{side}" for axle in axles
                      for side in ("left", "right")]
            rms = math.sqrt(sum((theoretical_deg[w] - ideal_deg[w]) ** 2
                                for w in wheels) / len(wheels))
            if rms > fit_limit:
                if boundaries[dof]:
                    flags.append(f"{dof}:NUMERICAL_ENVELOPE_LIMIT")
                    classes.add("NUMERICAL_ENVELOPE_LIMIT")
                else:
                    flags.append(f"{dof}:ACKERMANN_TARGET_MISMATCH")
                    classes.add("ACKERMANN_TARGET_MISMATCH")
            for axle in axles:
                if axle == 3:
                    continue
                left, right = f"axle{axle}_left", f"axle{axle}_right"
                if abs(theoretical_deg[left]) > 1.0e-9 and \
                        abs(theoretical_deg[right]) > 1.0e-9 and \
                        math.copysign(1.0, theoretical_deg[left]) != \
                        math.copysign(1.0, theoretical_deg[right]):
                    flags.append(f"{dof}:LEFT_RIGHT_OPPOSITE")
                    classes.add("PHYSICAL_LINKAGE_LIMIT")
        if outer is not None and \
                abs(theoretical_deg[outer] - target_outer_angle_deg) > 0.02:
            flags.append("q_front:OUTER_TARGET_NOT_REACHED")
            classes.add("NUMERICAL_ENVELOPE_LIMIT")
        if state.max_residual_m > 1.0e-9:
            flags.append("KINEMATIC_SOLVER_FAILURE:LINK_RESIDUAL")
            classes.add("KINEMATIC_SOLVER_FAILURE")
        for order in ("KINEMATIC_SOLVER_FAILURE", "PHYSICAL_LINKAGE_LIMIT",
                      "NUMERICAL_ENVELOPE_LIMIT", "ACKERMANN_TARGET_MISMATCH"):
            if order in classes:
                geometry_class = order
                break
        else:
            geometry_class = "OK"
        displacement = {name: 1000.0 * value
                        for name, value in state.cylinder_stroke_m.items()}
        absolute = {name: None for name in state.cylinder_stroke_m}
        reachable = not flags and state.max_residual_m <= 1.0e-9
        return GeometryResult(
            target_outer_angle_deg=float(target_outer_angle_deg),
            outer_wheel=outer, x_icr_m=x_icr, y_icr_m=y_icr,
            turn_radius_m=radius, curvature_1pm=curvature,
            ideal_ackermann_angle_deg=ideal_deg,
            theoretical_angle_deg=theoretical_deg,
            ackermann_geometry_error_deg=error_deg,
            q_rad=q_values, q_boundary_limited=boundaries,
            wheel_angle_jacobian=self._wheel_angle_jacobian(q_values),
            cylinder_displacement_mm=displacement,
            cylinder_absolute_length_mm=absolute,
            max_link_length_error_m=state.max_residual_m,
            geometry_reachable=reachable,
            geometry_status="OK" if reachable else "GEOMETRY_INFEASIBLE:" + ";".join(flags),
            geometry_class=geometry_class)

    def _wheel_angle_jacobian(self, q_values: Mapping[str, float],
                              step: float = 1.0e-6) -> dict[str, dict[str, float]]:
        result: dict[str, dict[str, float]] = {}
        for dof in DOF_ORDER:
            key = {"q_front": "front", "q4": "axle4", "q5": "axle5", "q6": "axle6"}[dof]
            axles = self.parameters.groups[key].axles
            wheels = [f"axle{axle}_{side}" for axle in axles
                      for side in ("left", "right")]
            table = {wheel: 0.0 for wheel in wheels}
            for delta in (step, -step):
                probe = dict(q_values)
                probe[dof] = float(q_values[dof]) + delta
                try:
                    state = self.mechanism_state(probe)
                except Exception:
                    table = {wheel: math.nan for wheel in wheels}
                    break
                for wheel in wheels:
                    table[wheel] += state.wheel_angles_rad[wheel] / (2.0 * delta)
            result[dof] = table
        return result

    # ------------------------------------------------------------ 受载估计
    def solve_loaded_case(self, case: CaseInput,
                          geometry: GeometryResult | None = None) -> LoadedCaseResult:
        """静态柔度估计（与 M1 同一套公式），仅用于全工况表的"受载估计角"列。

        **这不是 J0 的液压驱动角**：J0 中机构坐标由液压行程反求，道路载荷经
        虚功反馈一次，绝不在这里再叠加柔度修正。
        """
        geometry = geometry or self.solve_geometry(case.first_axle_outer_angle_deg)
        cfg = self.config["ground_load"]
        gravity = float(cfg["gravity_mps2"])
        masses = 1000.0 * np.asarray(case.axle_mass_t, dtype=float)
        total_mass = float(np.sum(masses))
        speed_mps = case.speed_kmh / 3.6
        ay = speed_mps ** 2 * geometry.curvature_1pm
        axle_x = np.array([
            0.5 * (self.centers[f"axle{a}_left"][0] + self.centers[f"axle{a}_right"][0])
            for a in range(1, 7)])
        x_cg = float(np.dot(masses, axle_x) / total_mass) if total_mass > 0 else \
            float(np.mean(axle_x))
        matrix = np.vstack([np.ones(6), axle_x - x_cg])
        weights = np.diag(np.maximum(masses, 1.0e-12))
        axle_demand = (weights @ matrix.T @ np.linalg.pinv(matrix @ weights @ matrix.T)
                       @ np.array([total_mass * ay, 0.0]))
        c_alpha = float(cfg["cornering_stiffness_per_wheel_N_per_rad"])
        trail = float(cfg["effective_trail_m"])
        pivot_radius = float(cfg["pivot_effective_radius_m"])
        transition = max(float(cfg["pivot_transition_speed_kmh"]), 1.0e-12)
        engagement_angle = math.radians(float(cfg["pivot_engagement_angle_deg"]))
        pivot_weight = math.exp(-((case.speed_kmh / transition) ** 2))
        fz: dict[str, float] = {}
        demand: dict[str, float] = {}
        available: dict[str, float] = {}
        slip: dict[str, float] = {}
        moments: dict[str, float] = {}
        for axle in range(1, 7):
            for side in ("left", "right"):
                wheel = f"axle{axle}_{side}"
                fz[wheel] = masses[axle - 1] * gravity / 2.0
                demand[wheel] = float(axle_demand[axle - 1] / 2.0)
                limit = case.friction_coefficient * fz[wheel]
                available[wheel] = float(np.clip(demand[wheel], -limit, limit))
                slip[wheel] = math.degrees(-demand[wheel] / c_alpha)
                delta = math.radians(geometry.theoretical_angle_deg[wheel])
                engagement = math.tanh(abs(delta) / max(engagement_angle, 1.0e-12))
                pivot_magnitude = case.friction_coefficient * fz[wheel] * \
                    pivot_radius * engagement
                running = abs(available[wheel]) * trail
                magnitude = pivot_weight * pivot_magnitude + (1.0 - pivot_weight) * running
                moments[wheel] = math.copysign(magnitude, delta) if abs(delta) > 1.0e-14 else 0.0
        generalized: dict[str, float] = {}
        loaded_q = dict(geometry.q_rad)
        stiffness = cfg["stiffness_scenarios_Nm_per_rad"].get(case.stiffness_scenario)
        if stiffness is None:
            raise ValueError(f"unknown stiffness scenario: {case.stiffness_scenario}")
        envelopes = self.q_envelopes
        for dof in DOF_ORDER:
            generalized[dof] = float(sum(
                moments[wheel] * geometry.wheel_angle_jacobian[dof][wheel]
                for wheel in geometry.wheel_angle_jacobian[dof]))
            loaded_q[dof] = geometry.q_rad[dof] - generalized[dof] / float(stiffness[dof])
        loaded_reachable = all(envelopes[dof][0] <= loaded_q[dof] <= envelopes[dof][1]
                               for dof in DOF_ORDER)
        if loaded_reachable:
            try:
                state = self.mechanism_state(loaded_q)
                actual_rad = dict(state.wheel_angles_rad)
            except Exception:
                loaded_reachable = False
                actual_rad = {wheel: math.nan for wheel in WHEEL_ORDER}
        else:
            actual_rad = {wheel: math.nan for wheel in WHEEL_ORDER}
        actual_rad["axle3_left"] = 0.0
        actual_rad["axle3_right"] = 0.0
        actual_deg = {wheel: math.degrees(value) for wheel, value in actual_rad.items()}
        error_deg = {wheel: actual_deg[wheel] - geometry.theoretical_angle_deg[wheel]
                     for wheel in WHEEL_ORDER}
        utilization = (abs(ay) / (case.friction_coefficient * gravity)
                       if case.friction_coefficient > 0.0
                       else (math.inf if abs(ay) > 0.0 else 0.0))
        max_slip = max(map(abs, slip.values()), default=0.0)
        flags: list[str] = []
        if not geometry.geometry_reachable:
            flags.append("GEOMETRY_INFEASIBLE")
        if utilization > 1.0:
            flags.append("ADHESION_INFEASIBLE")
        if max_slip > float(cfg["linear_slip_limit_deg"]):
            flags.append("OUTSIDE_LINEAR_TIRE_RANGE")
        if not loaded_reachable:
            flags.append("LOADED_GEOMETRY_INFEASIBLE")
        if not flags:
            flags.append("APPLICABLE_WITH_ASSUMED_PARAMETERS")
        return LoadedCaseResult(
            case=case, geometry=geometry, actual_loaded_angle_deg=actual_deg,
            load_induced_angle_error_deg=error_deg, tire_slip_angle_deg=slip,
            lateral_force_demand_N=demand, lateral_force_available_N=available,
            normal_load_N=fz, road_moment_Nm=moments,
            generalized_road_moment_Nm=generalized, loaded_q_rad=loaded_q,
            lateral_acceleration_mps2=ay,
            lateral_force_total_demand_N=total_mass * ay,
            lateral_force_total_available_N=float(sum(available.values())),
            adhesion_utilization=utilization, max_abs_slip_angle_deg=max_slip,
            applicability_status="|".join(flags), status_flags=tuple(flags),
            loaded_geometry_reachable=loaded_reachable)

    # ---------------------------------------------------------------- 校核
    def linkage_health(self, samples: int = 25) -> dict[str, Any]:
        """在整段机构坐标上检查残差 / 条件数 / 死点余量，供报告与测试使用。"""
        report: dict[str, Any] = {}
        for dof in DOF_ORDER:
            low, high = self.q_envelopes[dof]
            max_residual = 0.0
            max_condition = 0.0
            min_toggle = 180.0
            failures = 0
            for q in np.linspace(low, high, samples):
                try:
                    state = self.mechanism_state({**{d: 0.0 for d in DOF_ORDER}, dof: float(q)})
                except Exception:
                    failures += 1
                    continue
                max_residual = max(max_residual, state.max_residual_m)
                max_condition = max(max_condition, state.condition_number)
                min_toggle = min(min_toggle, state.min_toggle_margin_deg)
            report[dof] = {"q_lo_rad": low, "q_hi_rad": high,
                           "q_lo_deg": math.degrees(low), "q_hi_deg": math.degrees(high),
                           "max_residual_m": max_residual,
                           "max_condition_number": max_condition,
                           "min_toggle_margin_deg": min_toggle,
                           "failures": failures}
        return report
