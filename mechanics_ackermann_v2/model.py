"""Six-axle rigid-link Ackermann model with simplified tire/road feedback.

The module deliberately does not import hydraulics, control, degradation, or
lifetime code.  It reuses only the frozen R02B rigid-link kinematics and the
CUSTOMER hardpoint file.  Axle 3 is locked by the M1 topology regardless of
the actuator records preserved in the source coordinate table.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from steering_sim.ackermann.state import MechanismState
from steering_sim.mechanics import (
    SixAxleSteeringKinematics,
    reference_geometry_from_file,
)


WHEEL_ORDER = tuple(
    f"axle{axle}_{side}"
    for axle in range(1, 7)
    for side in ("left", "right")
)
DOF_ORDER = ("q_front", "q4", "q5", "q6")
DOF_TO_LEGACY_INDEX = {"q_front": 0, "q4": 2, "q5": 3, "q6": 4}
DOF_WHEELS = {
    "q_front": ("axle1_left", "axle1_right", "axle2_left", "axle2_right"),
    "q4": ("axle4_left", "axle4_right"),
    "q5": ("axle5_left", "axle5_right"),
    "q6": ("axle6_left", "axle6_right"),
}
REAR_CYLINDERS = tuple(
    f"axle{axle}_{side}" for axle in (4, 5, 6) for side in ("A", "B")
)


def load_config(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema_version") != "M1.0":
        raise ValueError("unsupported PHASE M1 configuration schema")
    return data


@dataclass(frozen=True, slots=True)
class CaseInput:
    speed_kmh: float
    first_axle_outer_angle_deg: float
    friction_coefficient: float
    axle_mass_t: tuple[float, float, float, float, float, float]
    stiffness_scenario: str = "medium_flexibility"

    def __post_init__(self) -> None:
        if len(self.axle_mass_t) != 6:
            raise ValueError("axle_mass_t must contain six values")
        values = (
            self.speed_kmh,
            self.first_axle_outer_angle_deg,
            self.friction_coefficient,
            *self.axle_mass_t,
        )
        if not all(math.isfinite(float(value)) for value in values):
            raise ValueError("case inputs must be finite")
        if self.speed_kmh < 0.0:
            raise ValueError("speed_kmh must be nonnegative")
        if self.friction_coefficient < 0.0:
            raise ValueError("friction_coefficient must be nonnegative")
        if any(value < 0.0 for value in self.axle_mass_t):
            raise ValueError("axle masses must be nonnegative")


@dataclass(frozen=True, slots=True)
class GeometryResult:
    target_outer_angle_deg: float
    outer_wheel: str | None
    x_icr_m: float | None
    y_icr_m: float | None
    turn_radius_m: float | None
    curvature_1pm: float
    ideal_ackermann_angle_deg: Mapping[str, float]
    theoretical_angle_deg: Mapping[str, float]
    ackermann_geometry_error_deg: Mapping[str, float]
    q_rad: Mapping[str, float]
    q_boundary_limited: Mapping[str, bool]
    wheel_angle_jacobian: Mapping[str, Mapping[str, float]]
    cylinder_displacement_mm: Mapping[str, float]
    cylinder_absolute_length_mm: Mapping[str, float | None]
    max_link_length_error_m: float
    geometry_reachable: bool
    geometry_status: str
    #: PHASE M2 §五：五类状态分离。
    #: ``OK`` / ``NUMERICAL_ENVELOPE_LIMIT`` / ``KINEMATIC_SOLVER_FAILURE`` /
    #: ``PHYSICAL_LINKAGE_LIMIT`` / ``ACKERMANN_TARGET_MISMATCH``
    geometry_class: str = "OK"

    @property
    def outer_target_reached(self) -> bool:
        if self.outer_wheel is None:
            return True
        return abs(self.theoretical_angle_deg[self.outer_wheel]
                   - self.target_outer_angle_deg) <= 0.02


@dataclass(frozen=True, slots=True)
class LoadedCaseResult:
    case: CaseInput
    geometry: GeometryResult
    actual_loaded_angle_deg: Mapping[str, float]
    load_induced_angle_error_deg: Mapping[str, float]
    tire_slip_angle_deg: Mapping[str, float]
    lateral_force_demand_N: Mapping[str, float]
    lateral_force_available_N: Mapping[str, float]
    normal_load_N: Mapping[str, float]
    road_moment_Nm: Mapping[str, float]
    generalized_road_moment_Nm: Mapping[str, float]
    loaded_q_rad: Mapping[str, float]
    lateral_acceleration_mps2: float
    lateral_force_total_demand_N: float
    lateral_force_total_available_N: float
    adhesion_utilization: float
    max_abs_slip_angle_deg: float
    applicability_status: str
    status_flags: tuple[str, ...]
    loaded_geometry_reachable: bool


@dataclass(slots=True)
class _Lookup:
    q: np.ndarray
    angles_rad: dict[str, np.ndarray]
    actuator_lengths_m: dict[str, np.ndarray]
    max_residual_m: np.ndarray

    def interp(self, values: np.ndarray, q_value: float) -> float:
        return float(np.interp(q_value, self.q, values))

    def angle(self, wheel: str, q_value: float) -> float:
        return self.interp(self.angles_rad[wheel], q_value)

    def derivative(self, wheel: str, q_value: float) -> float:
        values = self.angles_rad[wheel]
        derivative = np.gradient(values, self.q)
        return self.interp(derivative, q_value)


class PhaseM1Model:
    """Four-DOF M1 model: front linkage plus axles 4, 5, and 6."""

    def __init__(
        self,
        geometry_path: str | Path,
        config_path: str | Path,
    ) -> None:
        self.geometry_path = Path(geometry_path)
        self.config_path = Path(config_path)
        self.config = load_config(self.config_path)
        self.reference = reference_geometry_from_file(self.geometry_path)
        self.centers = self._wheel_centers()
        self._validate_customer_geometry()
        self.lookups = self._build_lookups()
        self.reference_lengths_m = self._reference_active_cylinder_lengths()
        self._loaded_exact_solver = SixAxleSteeringKinematics(self.reference)

    def _wheel_centers(self) -> dict[str, tuple[float, float]]:
        centers: dict[str, tuple[float, float]] = {}
        for axle in range(1, 7):
            for side, legacy_side in (("left", "POS_Y"), ("right", "NEG_Y")):
                pivot = self.reference.bodies[f"WHEEL_{axle}_{legacy_side}"].pivot
                centers[f"axle{axle}_{side}"] = (float(pivot[0]), float(pivot[1]))
        return centers

    def _validate_customer_geometry(self) -> None:
        point = self.reference.points["P20_SRC"].position
        expected = np.array(self.config["geometry"]["third_axle_point20_mm"]) / 1000.0
        if not np.allclose(point, expected, atol=1.0e-12):
            raise ValueError(
                f"CUSTOMER point 20 changed: got {point}, expected {expected} m"
            )
        if not self.config["geometry"]["third_axle_locked"]:
            raise ValueError("PHASE M1 requires axle 3 to remain locked")

    @staticmethod
    def _legacy_q(dof: str, value: float) -> np.ndarray:
        q = np.zeros(5)
        q[DOF_TO_LEGACY_INDEX[dof]] = value
        return q

    @staticmethod
    def _public_wheel_name(legacy_name: str) -> str:
        _, axle, side = legacy_name.split("_")
        return f"axle{axle}_{'left' if side == 'POS' else 'right'}"

    def _solution_angles(self, solution) -> dict[str, float]:
        return {
            f"axle{axle}_{side}": float(
                solution.wheel_angles[
                    f"WHEEL_{axle}_{'POS_Y' if side == 'left' else 'NEG_Y'}"
                ]
            )
            for axle in range(1, 7)
            for side in ("left", "right")
        }

    def _scan_direction(self, dof: str, bound: float, step: float) -> list[tuple]:
        model = SixAxleSteeringKinematics(self.reference)
        count = max(1, int(math.ceil(abs(bound) / step)))
        values = np.linspace(0.0, bound, count + 1)
        rows: list[tuple] = []
        for q_value in values:
            try:
                solution = model.solve(self._legacy_q(dof, float(q_value)))
            except Exception:
                break
            rows.append((float(q_value), solution))
        return rows

    def _build_lookup_for_dof(self, dof: str) -> _Lookup:
        lower, upper = self.config["geometry"]["q_envelopes_rad"][dof]
        step = float(self.config["geometry"]["lookup_step_rad"])
        negative = self._scan_direction(dof, float(lower), step)
        positive = self._scan_direction(dof, float(upper), step)
        rows = list(reversed(negative[1:])) + positive
        if len(rows) < 5:
            raise RuntimeError(f"insufficient continuous kinematic lookup for {dof}")
        q = np.array([row[0] for row in rows])
        all_angles = [self._solution_angles(row[1]) for row in rows]
        angles = {
            wheel: np.array([item[wheel] for item in all_angles], dtype=float)
            for wheel in WHEEL_ORDER
        }
        actuator_names = tuple(rows[0][1].actuator_lengths)
        actuators = {
            name: np.array(
                [row[1].actuator_lengths.get(name, math.nan) for row in rows],
                dtype=float,
            )
            for name in actuator_names
        }
        residuals = np.array(
            [
                max((abs(value) for value in row[1].constraint_residuals.values()), default=0.0)
                for row in rows
            ],
            dtype=float,
        )
        return _Lookup(q=q, angles_rad=angles, actuator_lengths_m=actuators, max_residual_m=residuals)

    def _build_lookups(self) -> dict[str, _Lookup]:
        return {dof: self._build_lookup_for_dof(dof) for dof in DOF_ORDER}

    def _reference_active_cylinder_lengths(self) -> dict[str, float]:
        solution = SixAxleSteeringKinematics(self.reference).solve(np.zeros(5))
        return {
            f"axle{axle}_{side}": float(solution.actuator_lengths[f"ACTUATOR_{axle}_{side}"])
            for axle in (4, 5, 6)
            for side in ("A", "B")
        }

    @property
    def q_envelopes(self) -> dict[str, tuple[float, float]]:
        """Q 坐标的连续延拓可解范围（rad）。PHASE M3 起作为 J0 集成层的公共入口。"""
        return {dof: (float(bounds[0]), float(bounds[1]))
                for dof, bounds in self.config["geometry"]["q_envelopes_rad"].items()}

    def mechanism_state(self, q_values: Mapping[str, float]):
        """统一机构状态入口（与 ``RedesignedAckermannModel`` 同构）。

        返回对象提供 J0 集成层需要的字段：十二轮转角、七个液压缸行程、
        闭链残差、条件数与三桥锁止角。J0 的 ``geometry.py`` 只依赖这一接口，
        因此切换 ``AS_BUILT_REFERENCE`` / ``REDESIGNED_ACKERMANN`` 不需要改动
        联合仿真循环本身。
        """
        solution = self._exact_solution(q_values)
        angles_rad = self._solution_angles(solution)
        angles_rad["axle3_left"] = 0.0
        angles_rad["axle3_right"] = 0.0
        displacement, _ = self._cylinder_outputs(q_values, solution)
        strokes = {
            "front_group_1": 0.001 * displacement["front_group_1"]}
        for axle in (4, 5, 6):
            for side in ("A", "B"):
                strokes[f"axle{axle}_{side}"] = \
                    0.001 * displacement[f"axle{axle}_{side}"]
        residual = max(
            (abs(value) for value in solution.constraint_residuals.values()),
            default=0.0)
        condition = float(solution.status.condition_number)
        return MechanismState(
            q_rad={dof: float(q_values[dof]) for dof in DOF_ORDER},
            wheel_angles_rad=angles_rad,
            wheel_angles_deg={wheel: math.degrees(value)
                              for wheel, value in angles_rad.items()},
            cylinder_stroke_m=strokes,
            representative_stroke_m={
                "front": strokes["front_group_1"],
                **{f"axle{axle}": strokes[f"axle{axle}_A"] for axle in (4, 5, 6)}},
            max_residual_m=residual,
            condition_number=condition,
            singular=bool(solution.status.singular),
            third_axle_max_abs_deg=max(abs(math.degrees(angles_rad["axle3_left"])),
                                       abs(math.degrees(angles_rad["axle3_right"]))),
            min_toggle_margin_deg=math.nan)

    @staticmethod
    def _axis_equivalent(angle: float) -> float:
        while angle > math.pi / 2:
            angle -= math.pi
        while angle < -math.pi / 2:
            angle += math.pi
        return angle

    def ideal_ackermann(self, target_outer_angle_deg: float) -> tuple:
        target_rad = math.radians(float(target_outer_angle_deg))
        x_icr = 0.5 * (
            self.centers["axle3_left"][0] + self.centers["axle3_right"][0]
        )
        if abs(target_rad) <= 1.0e-14:
            return None, x_icr, None, None, 0.0, {wheel: 0.0 for wheel in WHEEL_ORDER}
        outer = "axle1_right" if target_rad > 0.0 else "axle1_left"
        x_outer, y_outer = self.centers[outer]
        y_icr = y_outer + (x_outer - x_icr) / math.tan(target_rad)
        if math.copysign(1.0, y_icr) != math.copysign(1.0, target_rad):
            raise ValueError("target outer angle produces an ICR on the wrong side")
        angles: dict[str, float] = {}
        for wheel, (x, y) in self.centers.items():
            angles[wheel] = self._axis_equivalent(math.atan2(x - x_icr, y_icr - y))
        radius = abs(y_icr)
        curvature = math.copysign(1.0 / radius, target_rad)
        return outer, x_icr, y_icr, radius, curvature, angles

    @staticmethod
    def _quadratic_best_q(q: np.ndarray, cost: np.ndarray) -> tuple[float, bool]:
        index = int(np.argmin(cost))
        boundary = index in (0, len(q) - 1)
        if boundary:
            return float(q[index]), True
        xs = q[index - 1:index + 2]
        ys = cost[index - 1:index + 2]
        coefficient = np.polyfit(xs, ys, 2)
        if coefficient[0] <= 0.0:
            return float(q[index]), False
        value = float(np.clip(-coefficient[1] / (2.0 * coefficient[0]), xs[0], xs[-1]))
        return value, False

    def _fit_front_outer(self, outer: str | None, target_rad: float) -> tuple[float, bool]:
        if outer is None:
            return 0.0, False
        lookup = self.lookups["q_front"]
        values = lookup.angles_rad[outer]
        cost = (values - target_rad) ** 2
        return self._quadratic_best_q(lookup.q, cost)

    def _fit_rear_pair(self, dof: str, ideal: Mapping[str, float]) -> tuple[float, bool]:
        lookup = self.lookups[dof]
        cost = np.zeros_like(lookup.q)
        for wheel in DOF_WHEELS[dof]:
            cost += (lookup.angles_rad[wheel] - ideal[wheel]) ** 2
        return self._quadratic_best_q(lookup.q, cost)

    def _angles_from_q(self, q_values: Mapping[str, float]) -> dict[str, float]:
        angles = {wheel: 0.0 for wheel in WHEEL_ORDER}
        for dof, wheels in DOF_WHEELS.items():
            lookup = self.lookups[dof]
            q_value = float(q_values[dof])
            for wheel in wheels:
                angles[wheel] = lookup.angle(wheel, q_value)
        angles["axle3_left"] = 0.0
        angles["axle3_right"] = 0.0
        return angles

    def _exact_solution(self, q_values: Mapping[str, float], solver=None):
        target = np.zeros(5)
        for dof, index in DOF_TO_LEGACY_INDEX.items():
            target[index] = float(q_values[dof])
        active_solver = solver or SixAxleSteeringKinematics(self.reference)
        try:
            return active_solver.solve(target)
        except Exception:
            active_solver.reset()
            steps = max(2, int(math.ceil(np.max(np.abs(target)) / 0.02)) + 1)
            solution = None
            for factor in np.linspace(0.0, 1.0, steps):
                solution = active_solver.solve(target * factor)
            return solution

    def _jacobian_from_q(self, q_values: Mapping[str, float]) -> dict[str, dict[str, float]]:
        jacobian: dict[str, dict[str, float]] = {}
        for dof, wheels in DOF_WHEELS.items():
            jacobian[dof] = {
                wheel: self.lookups[dof].derivative(wheel, float(q_values[dof]))
                for wheel in wheels
            }
        return jacobian

    def _cylinder_outputs(self, q_values: Mapping[str, float], exact_solution=None) -> tuple[dict, dict]:
        displacement: dict[str, float] = {}
        absolute: dict[str, float | None] = {}
        front = self.config["front_cylinder_interface"]
        displacement["front_group_1"] = float(front["stroke_per_q_mm_per_rad"]) * q_values["q_front"]
        absolute["front_group_1"] = None
        for axle in (4, 5, 6):
            dof = f"q{axle}"
            lookup = self.lookups[dof]
            for side in ("A", "B"):
                public = f"axle{axle}_{side}"
                legacy = f"ACTUATOR_{axle}_{side}"
                length = (
                    float(exact_solution.actuator_lengths[legacy])
                    if exact_solution is not None
                    else lookup.interp(lookup.actuator_lengths_m[legacy], q_values[dof])
                )
                absolute[public] = 1000.0 * length
                displacement[public] = 1000.0 * (length - self.reference_lengths_m[public])
        return displacement, absolute

    def solve_geometry(self, target_outer_angle_deg: float) -> GeometryResult:
        target_rad = math.radians(float(target_outer_angle_deg))
        outer, x_icr, y_icr, radius, curvature, ideal_rad = self.ideal_ackermann(
            target_outer_angle_deg
        )
        q_values: dict[str, float] = {}
        boundaries: dict[str, bool] = {}
        q_values["q_front"], boundaries["q_front"] = self._fit_front_outer(outer, target_rad)
        for dof in ("q4", "q5", "q6"):
            q_values[dof], boundaries[dof] = self._fit_rear_pair(dof, ideal_rad)
        exact_solution = self._exact_solution(q_values)
        theoretical_rad = self._solution_angles(exact_solution)
        theoretical_rad["axle3_left"] = 0.0
        theoretical_rad["axle3_right"] = 0.0
        jacobian = self._jacobian_from_q(q_values)
        displacement, absolute = self._cylinder_outputs(q_values, exact_solution)
        fit_limit = float(self.config["geometry"]["fit_residual_limit_deg"])
        flags: list[str] = []
        # PHASE M2 §五：五类状态必须分开，不得再把"匹配不上"判成"不可达"。
        #   NUMERICAL_ENVELOPE_LIMIT  拟合撞上数值搜索包络（搜索范围不够）
        #   ACKERMANN_TARGET_MISMATCH 拟合没撞包络，但残差超限（机构能动，但配不上）
        #   LEFT_RIGHT_OPPOSITE       同桥左右轮方向相反（机构无法满足阿克曼方向）
        classes: set[str] = set()
        for dof, wheels in DOF_WHEELS.items():
            rms = math.degrees(math.sqrt(np.mean([
                (theoretical_rad[wheel] - ideal_rad[wheel]) ** 2 for wheel in wheels
            ])))
            if rms > fit_limit:
                if boundaries[dof]:
                    flags.append(f"{dof}:NUMERICAL_ENVELOPE_LIMIT")
                    classes.add("NUMERICAL_ENVELOPE_LIMIT")
                else:
                    flags.append(f"{dof}:ACKERMANN_TARGET_MISMATCH")
                    classes.add("ACKERMANN_TARGET_MISMATCH")
            axle = dof[1:] if dof.startswith("q") and dof != "q_front" else None
            if axle is not None:
                left, right = f"axle{axle}_left", f"axle{axle}_right"
                if abs(theoretical_rad[left]) > 1.0e-9 and \
                        abs(theoretical_rad[right]) > 1.0e-9 and \
                        math.copysign(1.0, theoretical_rad[left]) != \
                        math.copysign(1.0, theoretical_rad[right]):
                    flags.append(f"{dof}:LEFT_RIGHT_OPPOSITE")
                    classes.add("PHYSICAL_LINKAGE_LIMIT")
        if outer is not None and abs(math.degrees(theoretical_rad[outer]) - target_outer_angle_deg) > 0.02:
            flags.append("q_front:OUTER_TARGET_NOT_REACHED")
            classes.add("NUMERICAL_ENVELOPE_LIMIT")
        max_residual = max(
            (abs(value) for value in exact_solution.constraint_residuals.values()),
            default=0.0,
        )
        ideal_deg = {wheel: math.degrees(value) for wheel, value in ideal_rad.items()}
        theoretical_deg = {
            wheel: math.degrees(value) for wheel, value in theoretical_rad.items()
        }
        error_deg = {
            wheel: theoretical_deg[wheel] - ideal_deg[wheel] for wheel in WHEEL_ORDER
        }
        # ``geometry_class`` 是 PHASE M2 新增的五类状态；``geometry_status`` 与
        # ``geometry_reachable`` 保持旧语义（仅"有没有 flag"），以免破坏既有调用方。
        for order in ("PHYSICAL_LINKAGE_LIMIT", "NUMERICAL_ENVELOPE_LIMIT",
                      "ACKERMANN_TARGET_MISMATCH"):
            if order in classes:
                geometry_class = order
                break
        else:
            geometry_class = "OK"
        reachable = not flags and max_residual <= 1.0e-9
        return GeometryResult(
            target_outer_angle_deg=float(target_outer_angle_deg),
            outer_wheel=outer,
            x_icr_m=x_icr,
            y_icr_m=y_icr,
            turn_radius_m=radius,
            curvature_1pm=curvature,
            ideal_ackermann_angle_deg=ideal_deg,
            theoretical_angle_deg=theoretical_deg,
            ackermann_geometry_error_deg=error_deg,
            q_rad=q_values,
            q_boundary_limited=boundaries,
            wheel_angle_jacobian=jacobian,
            cylinder_displacement_mm=displacement,
            cylinder_absolute_length_mm=absolute,
            max_link_length_error_m=max_residual,
            geometry_reachable=reachable,
            geometry_status="OK" if reachable else "GEOMETRY_INFEASIBLE:" + ";".join(flags),
            geometry_class=geometry_class,
        )

    def _axle_x_and_cg(self, masses_kg: np.ndarray) -> tuple[np.ndarray, float]:
        axle_x = np.array([
            0.5 * (self.centers[f"axle{axle}_left"][0] + self.centers[f"axle{axle}_right"][0])
            for axle in range(1, 7)
        ])
        total = float(np.sum(masses_kg))
        if total <= 0.0:
            return axle_x, float(np.mean(axle_x))
        return axle_x, float(np.dot(masses_kg, axle_x) / total)

    def _allocate_lateral_force(self, total_force: float, masses_kg: np.ndarray) -> np.ndarray:
        total_mass = float(np.sum(masses_kg))
        if total_mass <= 0.0 or abs(total_force) <= 1.0e-15:
            return np.zeros(6)
        axle_x, x_cg = self._axle_x_and_cg(masses_kg)
        a = np.vstack([np.ones(6), axle_x - x_cg])
        weights = np.diag(np.maximum(masses_kg, 1.0e-12))
        rhs = np.array([total_force, 0.0])
        return weights @ a.T @ np.linalg.pinv(a @ weights @ a.T) @ rhs

    def solve_loaded_case(
        self,
        case: CaseInput,
        geometry: GeometryResult | None = None,
    ) -> LoadedCaseResult:
        geometry = geometry or self.solve_geometry(case.first_axle_outer_angle_deg)
        cfg = self.config["ground_load"]
        gravity = float(cfg["gravity_mps2"])
        masses = 1000.0 * np.asarray(case.axle_mass_t, dtype=float)
        total_mass = float(np.sum(masses))
        speed_mps = case.speed_kmh / 3.6
        ay = speed_mps ** 2 * geometry.curvature_1pm
        fy_total_demand = total_mass * ay
        axle_fy_demand = self._allocate_lateral_force(fy_total_demand, masses)
        c_alpha = float(cfg["cornering_stiffness_per_wheel_N_per_rad"])
        trail = float(cfg["effective_trail_m"])
        pivot_radius = float(cfg["pivot_effective_radius_m"])
        transition = max(float(cfg["pivot_transition_speed_kmh"]), 1.0e-12)
        engagement_angle = math.radians(float(cfg["pivot_engagement_angle_deg"]))
        pivot_weight = math.exp(-((case.speed_kmh / transition) ** 2))
        fz: dict[str, float] = {}
        fy_demand: dict[str, float] = {}
        fy_available: dict[str, float] = {}
        slip: dict[str, float] = {}
        moments: dict[str, float] = {}
        for axle in range(1, 7):
            for side in ("left", "right"):
                wheel = f"axle{axle}_{side}"
                fz[wheel] = masses[axle - 1] * gravity / 2.0
                fy_demand[wheel] = float(axle_fy_demand[axle - 1] / 2.0)
                limit = case.friction_coefficient * fz[wheel]
                fy_available[wheel] = float(np.clip(fy_demand[wheel], -limit, limit))
                slip[wheel] = math.degrees(-fy_demand[wheel] / c_alpha)
                delta = math.radians(geometry.theoretical_angle_deg[wheel])
                engagement = math.tanh(abs(delta) / max(engagement_angle, 1.0e-12))
                pivot_magnitude = case.friction_coefficient * fz[wheel] * pivot_radius * engagement
                running_magnitude = abs(fy_available[wheel]) * trail
                magnitude = pivot_weight * pivot_magnitude + (1.0 - pivot_weight) * running_magnitude
                moments[wheel] = math.copysign(magnitude, delta) if abs(delta) > 1.0e-14 else 0.0
        generalized: dict[str, float] = {}
        loaded_q = dict(geometry.q_rad)
        stiffness = cfg["stiffness_scenarios_Nm_per_rad"].get(case.stiffness_scenario)
        if stiffness is None:
            raise ValueError(f"unknown stiffness scenario: {case.stiffness_scenario}")
        for dof, wheels in DOF_WHEELS.items():
            generalized[dof] = float(sum(
                moments[wheel] * geometry.wheel_angle_jacobian[dof][wheel]
                for wheel in wheels
            ))
            loaded_q[dof] = geometry.q_rad[dof] - generalized[dof] / float(stiffness[dof])
        loaded_reachable = all(
            self.lookups[dof].q[0] <= loaded_q[dof] <= self.lookups[dof].q[-1]
            for dof in DOF_ORDER
        )
        if loaded_reachable:
            try:
                loaded_solution = self._exact_solution(loaded_q, self._loaded_exact_solver)
                actual_rad = self._solution_angles(loaded_solution)
                actual_rad["axle3_left"] = 0.0
                actual_rad["axle3_right"] = 0.0
            except Exception:
                loaded_reachable = False
                actual_rad = {wheel: math.nan for wheel in WHEEL_ORDER}
                actual_rad["axle3_left"] = 0.0
                actual_rad["axle3_right"] = 0.0
        else:
            actual_rad = {wheel: math.nan for wheel in WHEEL_ORDER}
            actual_rad["axle3_left"] = 0.0
            actual_rad["axle3_right"] = 0.0
        actual_deg = {wheel: math.degrees(value) for wheel, value in actual_rad.items()}
        error_deg = {
            wheel: actual_deg[wheel] - geometry.theoretical_angle_deg[wheel]
            for wheel in WHEEL_ORDER
        }
        utilization = (
            abs(ay) / (case.friction_coefficient * gravity)
            if case.friction_coefficient > 0.0 else (math.inf if abs(ay) > 0.0 else 0.0)
        )
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
        status = "|".join(flags)
        return LoadedCaseResult(
            case=case,
            geometry=geometry,
            actual_loaded_angle_deg=actual_deg,
            load_induced_angle_error_deg=error_deg,
            tire_slip_angle_deg=slip,
            lateral_force_demand_N=fy_demand,
            lateral_force_available_N=fy_available,
            normal_load_N=fz,
            road_moment_Nm=moments,
            generalized_road_moment_Nm=generalized,
            loaded_q_rad=loaded_q,
            lateral_acceleration_mps2=ay,
            lateral_force_total_demand_N=fy_total_demand,
            lateral_force_total_available_N=float(sum(fy_available.values())),
            adhesion_utilization=utilization,
            max_abs_slip_angle_deg=max_slip,
            applicability_status=status,
            status_flags=tuple(flags),
            loaded_geometry_reachable=loaded_reachable,
        )

    def link_invariance_check(self, q_values: Mapping[str, float]) -> float:
        """Evaluate the exact R02B solver at a continued M1 q and return drift."""
        target = np.zeros(5)
        for dof, index in DOF_TO_LEGACY_INDEX.items():
            target[index] = q_values[dof]
        model = SixAxleSteeringKinematics(self.reference)
        steps = max(2, int(math.ceil(np.max(np.abs(target)) / 0.02)) + 1)
        solution = None
        for factor in np.linspace(0.0, 1.0, steps):
            solution = model.solve(target * factor)
        assert solution is not None
        return max(
            abs(length - self.reference.links[name].reference_length)
            for name, length in solution.rigid_link_lengths.items()
        )
