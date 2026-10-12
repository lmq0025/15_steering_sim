"""PHASE J1：``ENGINEERING_STEERING_MODEL`` —— 唯一正式机械模型。

对外接口与 ``PhaseM1Model`` / M3 模型同构（``centers`` / ``config`` /
``reference`` / ``q_envelopes`` / ``mechanism_state`` / ``solve_geometry`` /
``ideal_ackermann``），因此 J0 联合仿真层不需要任何分支。

广义坐标 ``q`` 就是被甲方液压缸驱动的那个摆臂的转角（rad）。液压缸行程是它的
单调函数（甲方缸几何原样保留），所以"行程 → q → 十二轮转角"整条链可逆。

数据来源严格分开：

* ``CUSTOMER_GEOMETRY``：转向节主销、摆臂枢轴、液压缸机架点/杆端安装点；
* ``ENGINEERING_DESIGN_ASSUMPTION``：转向臂、齿条、拉杆等新设计尺寸，
  见 ``configs/j1/engineering_mechanism.json`` 与 ``hydraulic_design.json``。
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from steering_sim.mechanics import reference_geometry_from_file

from .mechanism import (DOF_OF_GROUP, DOF_ORDER, FRONT_CYLINDER, GROUPS,
                        LEGACY_SIDE, MechanismError, TAG, WHEEL_ORDER,
                        load_design)

REAR_AXLES = (4, 5, 6)
REAR_CYLINDER_SIDE = {"A": "right", "B": "left"}


class ModelError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class EngineeringState:
    """一个机构坐标下的机构状态（J0 集成层的最小接口）。"""

    q_rad: Mapping[str, float]
    wheel_angles_rad: Mapping[str, float]
    wheel_angles_deg: Mapping[str, float]
    cylinder_stroke_m: Mapping[str, float]
    representative_stroke_m: Mapping[str, float]
    max_residual_m: float
    condition_number: float
    singular: bool
    third_axle_max_abs_deg: float
    min_toggle_margin_deg: float = float("nan")


def load_config(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema_version") != "J1.0":
        raise ModelError("不支持的 J1 工程模型配置版本")
    return data


def cylinder_stroke_m(reference, axle: int, side: str, swing_rad: float) -> float:
    """甲方液压缸在该摆臂角下的行程（相对零位，m）。甲方安装点原样保留。"""
    legacy = LEGACY_SIDE[side]
    name = f"ACTUATOR_{axle}_{'B' if legacy == 'POS_Y' else 'A'}"
    actuator = reference.actuators[name]
    fixed = np.asarray(reference.points[actuator.frame_point_id].position, dtype=float)
    body = reference.bodies[actuator.moving_body]
    local = np.asarray(body.local_hardpoints[actuator.moving_point_id], dtype=float)
    pivot = np.asarray(body.pivot, dtype=float)
    c, s = math.cos(swing_rad), math.sin(swing_rad)
    moving = pivot + np.array([[c, -s], [s, c]]) @ local
    zero = float(np.linalg.norm(fixed - (pivot + local)))
    return float(np.linalg.norm(fixed - moving)) - zero


def representative_stroke_m(reference, axle: int, q_rad: float,
                            angles: Mapping[str, float] | None = None) -> float:
    """机构组的代表行程：**主动（A）液压缸的真实几何行程**（m，相对零位）。

    本模型的广义坐标 ``q`` 就是被该缸驱动的摆臂转角，所以代表行程直接由甲方
    液压缸几何给出 —— 单调、连续、零位为 0，且不需要任何假定。

    （PHASE M3 的中间摇臂方案里 ``q`` 是左右摆臂角的**平均值**，A 缸只跟其中
    一侧，才需要"对称双缸推程缸"那种临时定义；这里 q 就是被驱动的那只摆臂角，
    所以直接用真实缸行程即可。）
    """
    return cylinder_stroke_m(reference, axle, "right", float(q_rad))


def companion_stroke_m(reference, axle: int, q_rad: float) -> float:
    """伴随（B）液压缸行程：机构左右严格镜像，所以等于 A 缸在镜像构型下的行程。

    甲方每桥有 A、B 两只缸；本设计只把 A 缸作为主动缸接入机构（B 缸作为同回路的
    对称伴随缸保留）。这里按镜像恒等式给出它的几何行程，便于逐只缸报数。
    """
    return cylinder_stroke_m(reference, axle, "left", -float(q_rad))


class EngineeringSteeringModel:
    """唯一正式机械模型。"""

    tag = TAG

    def __init__(self, geometry_path: str | Path, config_path: str | Path,
                 design_path: str | Path | None = None) -> None:
        self.geometry_path = Path(geometry_path)
        self.config_path = Path(config_path)
        self.config = load_config(self.config_path)
        self.reference = reference_geometry_from_file(self.geometry_path)
        design_file = Path(design_path) if design_path is not None else \
            self.config_path.parent / "engineering_mechanism.json"
        self.design_path = design_file
        self.design = load_design(design_file)
        from .mechanism import EngineeringMechanism
        self.mechanism = EngineeringMechanism(self.reference, self.design)
        self.centers = self._wheel_centers()
        self._table_cache: dict[str, tuple] = {}
        self._geometry_cache: dict[float, Any] = {}
        self._front_stroke_per_q = float(
            self.config["front_cylinder_interface"]["stroke_per_q_mm_per_rad"]) / 1000.0
        self._validate()

    # ---------------------------------------------------------------- 基本量
    def _wheel_centers(self) -> dict[str, tuple[float, float]]:
        return {f"axle{a}_{s}": (float(self.reference.bodies[f"WHEEL_{a}_{LEGACY_SIDE[s]}"].pivot[0]),
                                 float(self.reference.bodies[f"WHEEL_{a}_{LEGACY_SIDE[s]}"].pivot[1]))
                for a in range(1, 7) for s in ("left", "right")}

    def _validate(self) -> None:
        point = self.reference.points["P20_SRC"].position
        expected = np.array(self.config["geometry"]["third_axle_point20_mm"]) / 1000.0
        if not np.allclose(point, expected, atol=1.0e-12):
            raise ModelError(f"CUSTOMER point 20 changed: {point} vs {expected} m")
        if not self.config["geometry"]["third_axle_locked"]:
            raise ModelError("J1 requires axle 3 to remain locked")

    @property
    def q_envelopes(self) -> dict[str, tuple[float, float]]:
        return {dof: (float(b[0]), float(b[1]))
                for dof, b in self.config["geometry"]["q_envelopes_rad"].items()}

    # ------------------------------------------------------------ 机构状态
    def mechanism_state(self, q_values: Mapping[str, float]) -> EngineeringState:
        states = self.mechanism.solve(q_values)
        wheels: dict[str, float] = {}
        representative: dict[str, float] = {}
        strokes: dict[str, float] = {FRONT_CYLINDER: math.nan}
        residual = 0.0
        for key in GROUPS:
            state = states[key]
            residual = max(residual, state.residual_m)
            for axle in self.design.groups[key].axles:
                for side in ("left", "right"):
                    wheels[f"axle{axle}_{side}"] = state.wheel_angles_rad[
                        f"axle{axle}_{side}"]
            if key == "front":
                representative["front"] = self._front_stroke_per_q * float(
                    q_values["q_front"])
                strokes[FRONT_CYLINDER] = representative["front"]
            else:
                axle = self.design.groups[key].axles[0]
                q_here = float(q_values[DOF_OF_GROUP[key]])
                representative[f"axle{axle}"] = representative_stroke_m(
                    self.reference, axle, q_here)
                strokes[f"axle{axle}_A"] = representative_stroke_m(
                    self.reference, axle, q_here)
                strokes[f"axle{axle}_B"] = companion_stroke_m(
                    self.reference, axle, q_here)
        for axle in (3,):
            wheels[f"axle{axle}_left"] = 0.0
            wheels[f"axle{axle}_right"] = 0.0
        return EngineeringState(
            q_rad={dof: float(q_values[dof]) for dof in DOF_ORDER},
            wheel_angles_rad=wheels,
            wheel_angles_deg={w: math.degrees(v) for w, v in wheels.items()},
            cylinder_stroke_m=strokes,
            representative_stroke_m=representative,
            max_residual_m=residual,
            condition_number=0.0, singular=False,
            third_axle_max_abs_deg=0.0, min_toggle_margin_deg=math.nan)

    def _swing_angle(self, key: str, side: str, q_rad: float) -> float:
        """该组某一侧摆臂的转角。主动侧就等于 q；另一侧不参与传动，取 0。"""
        group = self.design.groups[key]
        if side == "right":
            return float(q_rad)
        return 0.0

    def _swing_angles(self, key: str, q_rad: float) -> dict[str, float]:
        return {name: (float(q_rad) if name == f"SWING_{self.design.groups[key].driven_axle}_NEG_Y"
                       else 0.0)
                for name in [f"SWING_{a}_{LEGACY_SIDE[s]}"
                             for a in self.design.groups[key].axles
                             for s in ("left", "right")]}

    def reset(self) -> None:
        self.mechanism.reset()

    # ------------------------------------------------------------ 理想阿克曼
    def ideal_ackermann(self, target_outer_angle_deg: float) -> tuple:
        target_rad = math.radians(float(target_outer_angle_deg))
        x_icr = 0.5 * (self.centers["axle3_left"][0] + self.centers["axle3_right"][0])
        if abs(target_rad) <= 1.0e-14:
            return None, x_icr, None, None, 0.0, {w: 0.0 for w in WHEEL_ORDER}
        outer = "axle1_right" if target_rad > 0.0 else "axle1_left"
        x_outer, y_outer = self.centers[outer]
        y_icr = y_outer + (x_outer - x_icr) / math.tan(target_rad)
        if math.copysign(1.0, y_icr) != math.copysign(1.0, target_rad):
            raise ModelError("target outer angle produces an ICR on the wrong side")
        angles = {w: self._axis_equivalent(math.atan2(x - x_icr, y_icr - y))
                  for w, (x, y) in self.centers.items()}
        angles["axle3_left"] = 0.0
        angles["axle3_right"] = 0.0
        radius = abs(y_icr)
        return outer, x_icr, y_icr, radius, math.copysign(1.0 / radius, target_rad), angles

    @staticmethod
    def _axis_equivalent(angle: float) -> float:
        while angle > math.pi / 2:
            angle -= math.pi
        while angle < -math.pi / 2:
            angle += math.pi
        return angle

    def curvature_1pm(self, target_outer_angle_deg: float) -> float:
        return float(self.ideal_ackermann(target_outer_angle_deg)[4])

    # --------------------------------------------------------------- 拟合
    def _q_table(self, dof: str, samples: int = 400):
        cached = self._table_cache.get(dof)
        if cached is not None:
            return cached
        key = {"q_front": "front", "q4": "axle4", "q5": "axle5", "q6": "axle6"}[dof]
        build = self.design.groups[key]
        low, high = self.q_envelopes[dof]
        rows: list[tuple[float, dict]] = []
        for direction in (1.0, -1.0):
            bound = high if direction > 0 else low
            self.mechanism.reset_group(key, 0.0)
            self.mechanism.solve_swing(key, 0.0)
            step = direction * max(high, abs(low)) / samples
            q = 0.0
            while (step > 0 and q + step <= bound + 1e-12) or \
                    (step < 0 and q + step >= bound - 1e-12):
                q_next = q + step
                try:
                    state = self.mechanism.solve_swing(key, q_next)
                except MechanismError:
                    break
                rows.append((q_next, dict(state.wheel_angles_rad)))
                q = q_next
        rows.sort(key=lambda item: item[0])
        if len(rows) < 8:
            raise ModelError(f"{dof}: 机构连续延拓表不足")
        # 零位行必须**插到排序后的正确位置**，不能简单前置：前置会让 q 数组
        # 变成 ``[0, q_min, ..., q_max]`` 这种非单调序列，于是
        #   1) ``np.gradient``／``np.interp`` 全部读错；
        #   2) 目标角为 0° 时最优点正好落在下标 0，被 ``boundary`` 判据当成
        #      "撞上包络边界" —— 这就是 PHASE J1 里"0° 直行被误判为超出机构
        #      包络"的根因。
        zero = {f"axle{a}_{s}": 0.0 for a in build.axles for s in ("left", "right")}
        insert_at = 0
        while insert_at < len(rows) and rows[insert_at][0] < 0.0:
            insert_at += 1
        rows.insert(insert_at, (0.0, zero))
        q_array = np.array([r[0] for r in rows], dtype=float)
        if np.any(np.diff(q_array) <= 0.0):
            raise ModelError(f"{dof}: 机构延拓表的 q 网格不是严格递增")
        angles = {f"axle{a}_{s}": np.array([r[1][f"axle{a}_{s}"] for r in rows], dtype=float)
                  for a in build.axles for s in ("left", "right")}
        self._table_cache[dof] = (q_array, angles)
        return q_array, angles

    def solve_geometry(self, target_outer_angle_deg: float):
        key = float(target_outer_angle_deg)
        if key in self._geometry_cache:
            return self._geometry_cache[key]
        result = self._solve_geometry(key)
        self._geometry_cache[key] = result
        return result

    def _solve_geometry(self, target_outer_angle_deg: float):
        from mechanics_ackermann_v2.model import GeometryResult
        target_rad = math.radians(float(target_outer_angle_deg))
        outer, x_icr, y_icr, radius, curvature, ideal_rad = self.ideal_ackermann(
            target_outer_angle_deg)
        q_values: dict[str, float] = {}
        boundaries: dict[str, bool] = {}
        for dof in DOF_ORDER:
            q_array, angles = self._q_table(dof)
            if dof == "q_front" and outer is not None:
                cost = (angles[outer] - target_rad) ** 2
            else:
                cost = np.zeros_like(q_array)
                for wheel, values in angles.items():
                    cost += (values - ideal_rad[wheel]) ** 2
            index = int(np.argmin(cost))
            boundary = index in (0, len(q_array) - 1)
            if boundary:
                q_value = float(q_array[index])
            else:
                xs = q_array[index - 1:index + 2]
                ys = cost[index - 1:index + 2]
                coefficient = np.polyfit(xs, ys, 2)
                q_value = float(q_array[index]) if coefficient[0] <= 0.0 else float(
                    np.clip(-coefficient[1] / (2.0 * coefficient[0]), xs[0], xs[-1]))
            q_values[dof] = q_value
            boundaries[dof] = boundary
        state = self.mechanism_state(q_values)
        theoretical_deg = dict(state.wheel_angles_deg)
        ideal_deg = {w: math.degrees(v) for w, v in ideal_rad.items()}
        error_deg = {w: theoretical_deg[w] - ideal_deg[w] for w in WHEEL_ORDER}
        limit = float(self.config["geometry"]["fit_residual_limit_deg"])
        flags: list[str] = []
        classes: set[str] = set()
        for dof in DOF_ORDER:
            key = {"q_front": "front", "q4": "axle4", "q5": "axle5", "q6": "axle6"}[dof]
            axles = self.design.groups[key].axles
            wheels = [f"axle{a}_{s}" for a in axles for s in ("left", "right")]
            rms = math.sqrt(sum((theoretical_deg[w] - ideal_deg[w]) ** 2
                                for w in wheels) / len(wheels))
            if rms > limit:
                if boundaries[dof]:
                    flags.append(f"{dof}:NUMERICAL_ENVELOPE_LIMIT")
                    classes.add("NUMERICAL_ENVELOPE_LIMIT")
                else:
                    flags.append(f"{dof}:ACKERMANN_TARGET_MISMATCH")
                    classes.add("ACKERMANN_TARGET_MISMATCH")
            for axle in axles:
                left, right = f"axle{axle}_left", f"axle{axle}_right"
                if abs(theoretical_deg[left]) > 1e-9 and abs(theoretical_deg[right]) > 1e-9 \
                        and math.copysign(1.0, theoretical_deg[left]) != \
                        math.copysign(1.0, theoretical_deg[right]):
                    flags.append(f"{dof}:LEFT_RIGHT_OPPOSITE")
                    classes.add("PHYSICAL_LINKAGE_LIMIT")
        if outer is not None and abs(theoretical_deg[outer] - target_outer_angle_deg) > 0.02:
            flags.append("q_front:OUTER_TARGET_NOT_REACHED")
            classes.add("NUMERICAL_ENVELOPE_LIMIT")
        if state.max_residual_m > 1e-9:
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
        reachable = not flags and state.max_residual_m <= 1e-9
        return GeometryResult(
            target_outer_angle_deg=float(target_outer_angle_deg),
            outer_wheel=outer, x_icr_m=x_icr, y_icr_m=y_icr, turn_radius_m=radius,
            curvature_1pm=curvature, ideal_ackermann_angle_deg=ideal_deg,
            theoretical_angle_deg=theoretical_deg,
            ackermann_geometry_error_deg=error_deg, q_rad=q_values,
            q_boundary_limited=boundaries,
            wheel_angle_jacobian=self._wheel_angle_jacobian(q_values),
            cylinder_displacement_mm=displacement,
            cylinder_absolute_length_mm={n: None for n in displacement},
            max_link_length_error_m=state.max_residual_m,
            geometry_reachable=reachable,
            geometry_status="OK" if reachable else "GEOMETRY_INFEASIBLE:" + ";".join(flags),
            geometry_class=geometry_class)

    def _wheel_angle_jacobian(self, q_values: Mapping[str, float],
                              step: float = 1e-6) -> dict[str, dict[str, float]]:
        result: dict[str, dict[str, float]] = {}
        for dof in DOF_ORDER:
            key = {"q_front": "front", "q4": "axle4", "q5": "axle5", "q6": "axle6"}[dof]
            axles = self.design.groups[key].axles
            wheels = [f"axle{a}_{s}" for a in axles for s in ("left", "right")]
            table = {w: 0.0 for w in wheels}
            for delta in (step, -step):
                probe = dict(q_values)
                probe[dof] = float(q_values[dof]) + delta
                try:
                    state = self.mechanism_state(probe)
                except Exception:
                    table = {w: math.nan for w in wheels}
                    break
                for w in wheels:
                    table[w] += state.wheel_angles_rad[w] / (2.0 * delta)
            result[dof] = table
        return result

    # ------------------------------------------------------------ 受载估计
    def solve_loaded_case(self, case, geometry=None):
        from mechanics_ackermann_v2.model import (CaseInput, LoadedCaseResult)
        from steering_sim.j0_coupling.road_load import _allocate_lateral_force
        geometry = geometry or self.solve_geometry(case.first_axle_outer_angle_deg)
        cfg = self.config["ground_load"]
        gravity = float(cfg["gravity_mps2"])
        masses = 1000.0 * np.asarray(case.axle_mass_t, dtype=float)
        total_mass = float(np.sum(masses))
        speed_mps = case.speed_kmh / 3.6
        ay = speed_mps ** 2 * geometry.curvature_1pm
        axle_x = np.array([0.5 * (self.centers[f"axle{a}_left"][0]
                                  + self.centers[f"axle{a}_right"][0])
                           for a in range(1, 7)])
        x_cg = float(np.dot(masses, axle_x) / total_mass) if total_mass > 0 else \
            float(np.mean(axle_x))
        matrix = np.vstack([np.ones(6), axle_x - x_cg])
        weights = np.diag(np.maximum(masses, 1e-12))
        axle_demand = (weights @ matrix.T @ np.linalg.pinv(matrix @ weights @ matrix.T)
                       @ np.array([total_mass * ay, 0.0]))
        c_alpha = float(cfg["cornering_stiffness_per_wheel_N_per_rad"])
        trail = float(cfg["effective_trail_m"])
        pivot_radius = float(cfg["pivot_effective_radius_m"])
        transition = max(float(cfg["pivot_transition_speed_kmh"]), 1e-12)
        engagement_angle = math.radians(float(cfg["pivot_engagement_angle_deg"]))
        pivot_weight = math.exp(-((case.speed_kmh / transition) ** 2))
        fz, demand, available, slip, moments = {}, {}, {}, {}, {}
        for axle in range(1, 7):
            for side in ("left", "right"):
                wheel = f"axle{axle}_{side}"
                fz[wheel] = masses[axle - 1] * gravity / 2.0
                demand[wheel] = float(axle_demand[axle - 1] / 2.0)
                limit = case.friction_coefficient * fz[wheel]
                available[wheel] = float(np.clip(demand[wheel], -limit, limit))
                slip[wheel] = math.degrees(-demand[wheel] / c_alpha)
                delta = math.radians(geometry.theoretical_angle_deg[wheel])
                engagement = math.tanh(abs(delta) / max(engagement_angle, 1e-12))
                pivot_magnitude = case.friction_coefficient * fz[wheel] * \
                    pivot_radius * engagement
                running = abs(available[wheel]) * trail
                magnitude = pivot_weight * pivot_magnitude + (1 - pivot_weight) * running
                moments[wheel] = math.copysign(magnitude, delta) if abs(delta) > 1e-14 else 0.0
        stiffness = cfg["stiffness_scenarios_Nm_per_rad"].get(case.stiffness_scenario)
        if stiffness is None:
            raise ModelError(f"unknown stiffness scenario {case.stiffness_scenario}")
        generalized, loaded_q = {}, dict(geometry.q_rad)
        envelopes = self.q_envelopes
        for dof in DOF_ORDER:
            generalized[dof] = float(sum(
                moments[w] * geometry.wheel_angle_jacobian[dof][w]
                for w in geometry.wheel_angle_jacobian[dof]))
            loaded_q[dof] = geometry.q_rad[dof] - generalized[dof] / float(stiffness[dof])
        loaded_reachable = all(envelopes[d][0] <= loaded_q[d] <= envelopes[d][1]
                               for d in DOF_ORDER)
        if loaded_reachable:
            try:
                actual_rad = dict(self.mechanism_state(loaded_q).wheel_angles_rad)
            except Exception:
                loaded_reachable = False
                actual_rad = {w: math.nan for w in WHEEL_ORDER}
        else:
            actual_rad = {w: math.nan for w in WHEEL_ORDER}
        actual_rad["axle3_left"] = 0.0
        actual_rad["axle3_right"] = 0.0
        actual_deg = {w: math.degrees(v) for w, v in actual_rad.items()}
        utilization = (abs(ay) / (case.friction_coefficient * gravity)
                       if case.friction_coefficient > 0 else
                       (math.inf if abs(ay) > 0 else 0.0))
        max_slip = max(map(abs, slip.values()), default=0.0)
        flags = []
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
            load_induced_angle_error_deg={w: actual_deg[w] - geometry.theoretical_angle_deg[w]
                                          for w in WHEEL_ORDER},
            tire_slip_angle_deg=slip, lateral_force_demand_N=demand,
            lateral_force_available_N=available, normal_load_N=fz, road_moment_Nm=moments,
            generalized_road_moment_Nm=generalized, loaded_q_rad=loaded_q,
            lateral_acceleration_mps2=ay, lateral_force_total_demand_N=total_mass * ay,
            lateral_force_total_available_N=float(sum(available.values())),
            adhesion_utilization=utilization, max_abs_slip_angle_deg=max_slip,
            applicability_status="|".join(flags), status_flags=tuple(flags),
            loaded_geometry_reachable=loaded_reachable)
