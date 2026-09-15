"""Six-axle steering coordination built on the frozen R02-B/R02-D models."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import math
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

import numpy as np
from scipy.optimize import brentq, minimize_scalar

from .io_model import (
    MechanicalActuatorInput, MechanicalSteeringIOModel, MechanicalSteeringOutput,
    WHEEL_OUTPUT_ORDER,
)
from .io_parameters import PositionDefinition
from .kinematics import GENERALIZED_COORDINATES, SixAxleSteeringKinematics


class SteeringMode(str, Enum):
    LOW_SPEED_COUNTER_PHASE = "LOW_SPEED_COUNTER_PHASE"
    CRAB = "CRAB"
    FRONT_GROUP_ONLY = "FRONT_GROUP_ONLY"
    CUSTOM = "CUSTOM"


@dataclass(frozen=True, slots=True)
class CoordinatorValue:
    value: float
    unit: str
    source: str
    confidence: str
    reference: str
    notes: str
    calibratable: bool
    lower_bound: float
    upper_bound: float

    def __post_init__(self) -> None:
        if not all((self.unit, self.source, self.confidence, self.reference, self.notes)):
            raise ValueError("coordinator values require complete provenance metadata")
        if not self.lower_bound <= self.value <= self.upper_bound:
            raise ValueError("coordinator baseline value is outside its bounds")


@dataclass(frozen=True, slots=True)
class SteeringPreset:
    name: str
    aliases: tuple[str, ...]
    source: str
    confidence: str
    notes: str
    axle_before: int
    axle_after: int
    fraction: CoordinatorValue
    x_icr_m: CoordinatorValue | None
    coordination_gains: Mapping[int, CoordinatorValue]

    def __post_init__(self) -> None:
        if self.axle_before not in range(1, 7) or self.axle_after not in range(1, 7):
            raise ValueError("ICR axle indices must be 1..6")
        if self.axle_before == self.axle_after:
            raise ValueError("ICR interpolation requires two distinct axles")
        if set(self.coordination_gains) != set(range(1, 7)):
            raise ValueError("a preset requires one coordination gain per axle")
        object.__setattr__(self, "coordination_gains", MappingProxyType(dict(self.coordination_gains)))


@dataclass(frozen=True, slots=True)
class SteeringCoordinatorConfig:
    presets: Mapping[str, SteeringPreset]
    sample_count: int
    boundary_tolerance_rad: float
    material_residual_rad: float
    hardpoints_frozen: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "presets", MappingProxyType(dict(self.presets)))
        if self.sample_count < 5 or self.sample_count % 2 == 0:
            raise ValueError("sample_count must be an odd integer >= 5")
        if not self.hardpoints_frozen:
            raise ValueError("R02-E must keep CUSTOMER hardpoints frozen")

    def preset(self, name_or_alias: str) -> SteeringPreset:
        normalized = name_or_alias.strip().lower()
        for preset in self.presets.values():
            if normalized == preset.name.lower() or normalized in (alias.lower() for alias in preset.aliases):
                return preset
        raise KeyError(f"unknown steering preset: {name_or_alias}")


def _configured_value(raw: Mapping) -> CoordinatorValue:
    required = {
        "value", "unit", "source", "confidence", "reference", "notes",
        "calibratable", "lower_bound", "upper_bound",
    }
    missing = required - raw.keys()
    if missing:
        raise ValueError(f"coordinator value missing metadata: {sorted(missing)}")
    return CoordinatorValue(
        float(raw["value"]), str(raw["unit"]), str(raw["source"]),
        str(raw["confidence"]), str(raw["reference"]), str(raw["notes"]),
        bool(raw["calibratable"]), float(raw["lower_bound"]), float(raw["upper_bound"]),
    )


def load_steering_coordinator_config(path: str | Path) -> SteeringCoordinatorConfig:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if (
        raw.get("schema_version") != "1.0"
        or raw.get("purpose") != "R02E_MULTI_AXLE_COORDINATION_BASELINE_ONLY"
    ):
        raise ValueError("unsupported R02-E coordinator baseline schema")
    presets = {}
    for name, item in raw["presets"].items():
        between = item["icr_between_axles"]
        direct = item.get("x_icr_m")
        gains = {
            axle: _configured_value(item["coordination_gains"][f"axle{axle}"])
            for axle in range(1, 7)
        }
        presets[name] = SteeringPreset(
            name=name,
            aliases=tuple(item.get("aliases", ())),
            source=str(item["source"]),
            confidence=str(item["confidence"]),
            notes=str(item["notes"]),
            axle_before=int(between["axle_before"]),
            axle_after=int(between["axle_after"]),
            fraction=_configured_value(between["fraction"]),
            x_icr_m=None if direct is None else _configured_value(direct),
            coordination_gains=gains,
        )
    numerical = raw["numerical_fit"]
    return SteeringCoordinatorConfig(
        presets=presets,
        sample_count=int(_configured_value(numerical["sample_count"]).value),
        boundary_tolerance_rad=_configured_value(numerical["boundary_tolerance_rad"]).value,
        material_residual_rad=math.radians(
            _configured_value(numerical["material_residual_deg"]).value
        ),
        hardpoints_frozen=bool(raw["hardpoints"]["frozen"]),
    )


def wheel_axis_centers(reference) -> Mapping[str, tuple[float, float]]:
    """Read all twelve steering-axis centers from frozen wheel-body pivots."""
    return MappingProxyType({
        f"axle{axle}_{side}": tuple(reference.bodies[f"WHEEL_{axle}_{side}"].pivot)
        for axle in range(1, 7)
        for side in ("POS_Y", "NEG_Y")
    })


def _axis_equivalent_angle(angle: float) -> float:
    while angle > math.pi / 2:
        angle -= math.pi
    while angle < -math.pi / 2:
        angle += math.pi
    return angle


def ideal_wheel_angles_from_icr(
    centers: Mapping[str, tuple[float, float]], x_icr_m: float, y_icr_m: float
) -> Mapping[str, float]:
    """Return pure-rolling wheel-axis directions in the existing +X/+Y frame."""
    if not math.isfinite(x_icr_m) or not math.isfinite(y_icr_m):
        raise ValueError("ICR coordinates must be finite")
    result = {}
    for wheel, (x_m, y_m) in centers.items():
        if math.hypot(x_m - x_icr_m, y_m - y_icr_m) <= 1.0e-12:
            raise ValueError(f"ICR coincides with {wheel} steering-axis center")
        result[wheel] = _axis_equivalent_angle(
            math.atan2(x_m - x_icr_m, y_icr_m - y_m)
        )
    return MappingProxyType(result)


def axle_mean_angles(wheel_angles: Mapping[str, float]) -> Mapping[int, float]:
    return MappingProxyType({
        axle: 0.5 * (
            float(wheel_angles[f"axle{axle}_POS_Y"])
            + float(wheel_angles[f"axle{axle}_NEG_Y"])
        )
        for axle in range(1, 7)
    })


@dataclass(frozen=True, slots=True)
class AxleSteeringDiagnostic:
    axle: int
    ideal_pos_y_rad: float
    ideal_neg_y_rad: float
    actual_pos_y_rad: float
    actual_neg_y_rad: float
    ideal_mean_rad: float
    actual_mean_rad: float
    ackermann_error_deg: float
    q_rad: float
    actuator_a_stroke_m: float | None
    actuator_b_stroke_m: float | None
    geometry_residual_rad: float
    fit_boundary_limited: bool
    status: str
    monotonic_branch_used: str
    branch_continuity: bool


@dataclass(frozen=True, slots=True)
class VehicleSteeringResult:
    preset: str
    mode: SteeringMode
    target_axle1_mean_angle_deg: float
    x_icr_m: float | None
    y_icr_m: float | None
    ideal_wheel_angles_rad: Mapping[str, float]
    q_target_rad: Mapping[str, float]
    actuator_input: MechanicalActuatorInput
    mechanical_output: MechanicalSteeringOutput
    axles: Mapping[int, AxleSteeringDiagnostic]
    feasible: bool
    largest_feasible_scale: float
    diagnostics: Mapping[str, object]

    def __post_init__(self) -> None:
        for field in ("ideal_wheel_angles_rad", "q_target_rad", "axles", "diagnostics"):
            object.__setattr__(self, field, MappingProxyType(dict(getattr(self, field))))


@dataclass(frozen=True, slots=True)
class _FitResult:
    q_rad: float
    residual_rad: float
    boundary_limited: bool
    branch: str
    continuous: bool


class MultiAxleSteeringCoordinator:
    """Command/mode -> ideal ICR targets -> frozen mechanics -> actuator I/O."""

    def __init__(
        self,
        io_model: MechanicalSteeringIOModel,
        config: SteeringCoordinatorConfig,
    ) -> None:
        self.io_model = io_model
        self.reference = io_model.reference
        self.config = config
        self.centers = wheel_axis_centers(self.reference)
        self._previous_q = np.zeros(5)
        self._wheel_cache: dict[tuple[int, float], Mapping[str, float]] = {}

    def reset(self) -> None:
        self._previous_q = np.zeros(5)
        self.io_model.reset()

    def axle_x_m(self, axle: int) -> float:
        return 0.5 * (
            self.centers[f"axle{axle}_POS_Y"][0]
            + self.centers[f"axle{axle}_NEG_Y"][0]
        )

    def resolve_x_icr(self, preset: SteeringPreset) -> float:
        if preset.x_icr_m is not None:
            return preset.x_icr_m.value
        x_before = self.axle_x_m(preset.axle_before)
        x_after = self.axle_x_m(preset.axle_after)
        return x_before + preset.fraction.value * (x_after - x_before)

    def _solve_y_icr(self, x_icr_m: float, target_rad: float) -> float:
        if abs(target_rad) <= 1.0e-14:
            return math.copysign(math.inf, target_rad if target_rad else 1.0)
        side = math.copysign(1.0, target_rad)
        lateral_edge = max(abs(center[1]) for center in self.centers.values()) + 1.0e-8

        def mismatch(radius: float) -> float:
            ideal = ideal_wheel_angles_from_icr(self.centers, x_icr_m, side * radius)
            mean = 0.5 * (ideal["axle1_POS_Y"] + ideal["axle1_NEG_Y"])
            return mean - target_rad

        low, high = lateral_edge, 1.0e6
        if mismatch(low) * mismatch(high) > 0.0:
            raise ValueError("requested axle-1 mean cannot define an external lateral ICR")
        return side * float(brentq(mismatch, low, high, xtol=1.0e-13, rtol=1.0e-13))

    def ideal_targets(
        self,
        target_axle1_mean_angle_deg: float,
        preset: SteeringPreset,
        mode: SteeringMode,
        custom_axle_gains: Mapping[int, float] | None = None,
    ) -> tuple[float | None, float | None, Mapping[str, float]]:
        target_rad = math.radians(float(target_axle1_mean_angle_deg))
        if not math.isfinite(target_rad):
            raise ValueError("target_axle1_mean_angle_deg must be finite")
        if mode is SteeringMode.LOW_SPEED_COUNTER_PHASE:
            x_icr = self.resolve_x_icr(preset)
            if abs(target_rad) <= 1.0e-14:
                ideal = {wheel: 0.0 for wheel in WHEEL_OUTPUT_ORDER}
                return x_icr, None, MappingProxyType(ideal)
            y_icr = self._solve_y_icr(x_icr, target_rad)
            raw = ideal_wheel_angles_from_icr(self.centers, x_icr, y_icr)
            ideal = {
                wheel: raw[wheel] * preset.coordination_gains[
                    int(wheel.split("_", 1)[0].removeprefix("axle"))
                ].value
                for wheel in WHEEL_OUTPUT_ORDER
            }
            return x_icr, y_icr, MappingProxyType(ideal)
        if mode is SteeringMode.CRAB:
            ideal = {
                wheel: target_rad * preset.coordination_gains[
                    int(wheel.split("_", 1)[0].removeprefix("axle"))
                ].value
                for wheel in WHEEL_OUTPUT_ORDER
            }
            return None, None, MappingProxyType(ideal)
        if mode is SteeringMode.FRONT_GROUP_ONLY:
            ideal = {
                wheel: target_rad if int(wheel.split("_", 1)[0].removeprefix("axle")) <= 2 else 0.0
                for wheel in WHEEL_OUTPUT_ORDER
            }
            return None, None, MappingProxyType(ideal)
        if mode is SteeringMode.CUSTOM:
            if custom_axle_gains is None or set(custom_axle_gains) != set(range(1, 7)):
                raise ValueError("CUSTOM mode requires gains for axles 1..6")
            ideal = {
                wheel: target_rad * float(custom_axle_gains[
                    int(wheel.split("_", 1)[0].removeprefix("axle"))
                ])
                for wheel in WHEEL_OUTPUT_ORDER
            }
            return None, None, MappingProxyType(ideal)
        raise ValueError(f"unsupported steering mode: {mode}")

    def _wheel_angles_for_q(self, dof_index: int, q_value: float) -> Mapping[str, float]:
        key = (dof_index, round(float(q_value), 14))
        if key not in self._wheel_cache:
            q = np.zeros(5)
            q[dof_index] = q_value
            solution = SixAxleSteeringKinematics(self.reference).solve(q)
            self._wheel_cache[key] = MappingProxyType({
                f"axle{axle}_{side}": (
                    solution.wheel_angles[f"WHEEL_{axle}_{side}"]
                    + self.io_model.parameters.wheel_zero_offsets[f"WHEEL_{axle}_{side}"].value
                )
                for axle in range(1, 7)
                for side in ("POS_Y", "NEG_Y")
            })
        return self._wheel_cache[key]

    def _fit_dof(
        self, dof_index: int, wheel_names: tuple[str, ...], targets: Mapping[str, float]
    ) -> _FitResult:
        lower = self.io_model.parameters.inverse_lower_q_rad.value
        upper = self.io_model.parameters.inverse_upper_q_rad.value

        def objective(q_value: float) -> float:
            actual = self._wheel_angles_for_q(dof_index, float(q_value))
            return float(sum((actual[name] - targets[name]) ** 2 for name in wheel_names))

        grid = np.linspace(lower, upper, self.config.sample_count)
        costs = np.array([objective(value) for value in grid])
        local = [
            index for index in range(1, len(grid) - 1)
            if costs[index] <= costs[index - 1] and costs[index] <= costs[index + 1]
        ]
        candidates: list[tuple[float, float, tuple[float, float]]] = [
            (float(grid[0]), float(costs[0]), (float(grid[0]), float(grid[1]))),
            (float(grid[-1]), float(costs[-1]), (float(grid[-2]), float(grid[-1]))),
        ]
        for index in local:
            interval = (float(grid[index - 1]), float(grid[index + 1]))
            result = minimize_scalar(
                objective, method="bounded", bounds=interval,
                options={"xatol": 1.0e-12, "maxiter": 200},
            )
            candidates.append((float(result.x), float(result.fun), interval))
        minimum = min(item[1] for item in candidates)
        tie_tolerance = max(1.0e-18, minimum * 1.0e-10)
        eligible = [item for item in candidates if item[1] <= minimum + tie_tolerance]
        previous = self._previous_q[dof_index]
        q_value, cost, interval = min(eligible, key=lambda item: abs(item[0] - previous))
        actual = self._wheel_angles_for_q(dof_index, q_value)
        values = np.array([actual[name] for name in wheel_names])
        h = 1.0e-5
        left = max(lower, q_value - h)
        right = min(upper, q_value + h)
        left_mean = np.mean([
            self._wheel_angles_for_q(dof_index, left)[name] for name in wheel_names
        ])
        right_mean = np.mean([
            self._wheel_angles_for_q(dof_index, right)[name] for name in wheel_names
        ])
        slope = (right_mean - left_mean) / max(right - left, 1.0e-15)
        if abs(slope) < 1.0e-4:
            monotonic = "turning-point proximity"
        else:
            monotonic = "increasing" if slope > 0.0 else "decreasing"
        branch = f"{monotonic} q in [{interval[0]:+.6f}, {interval[1]:+.6f}] rad"
        boundary = (
            q_value - lower <= self.config.boundary_tolerance_rad
            or upper - q_value <= self.config.boundary_tolerance_rad
        )
        continuous = bool(abs(q_value - previous) <= 0.1)
        return _FitResult(
            q_rad=q_value,
            residual_rad=float(math.sqrt(cost / len(wheel_names))),
            boundary_limited=boundary,
            branch=branch,
            continuous=continuous,
        )

    def _coordinate_once(
        self,
        target_deg: float,
        preset: SteeringPreset,
        mode: SteeringMode,
        custom_axle_gains: Mapping[int, float] | None,
    ) -> VehicleSteeringResult:
        x_icr, y_icr, ideal = self.ideal_targets(
            target_deg, preset, mode, custom_axle_gains
        )
        fits = []
        fits.append(self._fit_dof(
            0,
            ("axle1_POS_Y", "axle1_NEG_Y", "axle2_POS_Y", "axle2_NEG_Y"),
            ideal,
        ))
        for axle in range(3, 7):
            fits.append(self._fit_dof(
                axle - 2,
                (f"axle{axle}_POS_Y", f"axle{axle}_NEG_Y"),
                ideal,
            ))
        q = np.array([fit.q_rad for fit in fits])
        actuator_input = self.io_model.inputs_from_generalized_coordinates(
            q, PositionDefinition.STROKE_FROM_REFERENCE_M
        )
        self.io_model.reset(self._previous_q)
        mechanical = self.io_model.solve_from_actuators(actuator_input)

        axle_diagnostics = {}
        for axle in range(1, 7):
            ideal_pair = np.array([
                ideal[f"axle{axle}_POS_Y"], ideal[f"axle{axle}_NEG_Y"]
            ])
            actual_pair = np.array([
                mechanical.wheel_angles_rad[f"axle{axle}_POS_Y"],
                mechanical.wheel_angles_rad[f"axle{axle}_NEG_Y"],
            ])
            fit_index = 0 if axle <= 2 else axle - 2
            fit = fits[fit_index]
            residual = float(np.sqrt(np.mean((actual_pair - ideal_pair) ** 2)))
            material = residual > self.config.material_residual_rad
            if fit.boundary_limited and material:
                status = "geometry_limited"
            elif material:
                status = "baseline_mismatch"
            else:
                status = "matched_within_display_tolerance"
            stroke_a = stroke_b = None
            if axle >= 3:
                stroke_a = getattr(actuator_input, f"axle{axle}_A").value_m
                stroke_b = getattr(actuator_input, f"axle{axle}_B").value_m
            axle_diagnostics[axle] = AxleSteeringDiagnostic(
                axle=axle,
                ideal_pos_y_rad=float(ideal_pair[0]),
                ideal_neg_y_rad=float(ideal_pair[1]),
                actual_pos_y_rad=float(actual_pair[0]),
                actual_neg_y_rad=float(actual_pair[1]),
                ideal_mean_rad=float(np.mean(ideal_pair)),
                actual_mean_rad=float(np.mean(actual_pair)),
                ackermann_error_deg=math.degrees(float(np.max(np.abs(actual_pair - ideal_pair)))),
                q_rad=float(q[fit_index]),
                actuator_a_stroke_m=stroke_a,
                actuator_b_stroke_m=stroke_b,
                geometry_residual_rad=residual,
                fit_boundary_limited=fit.boundary_limited,
                status=status,
                monotonic_branch_used=fit.branch,
                branch_continuity=fit.continuous,
            )
        hard_limited = any(
            diagnostic.fit_boundary_limited
            and diagnostic.geometry_residual_rad > self.config.material_residual_rad
            for diagnostic in axle_diagnostics.values()
        )
        feasible = mechanical.valid and not hard_limited
        diagnostics = {
            "baseline_only": True,
            "not_customer_vehicle_prediction": True,
            "q_range_definition": "R02-B numerical verification interval; not a mechanical limit",
            "material_residual_definition": "display diagnostic only; not an engineering acceptance threshold",
            "axle5": axle_diagnostics[5],
            "axle6": axle_diagnostics[6],
        }
        return VehicleSteeringResult(
            preset=preset.name,
            mode=mode,
            target_axle1_mean_angle_deg=float(target_deg),
            x_icr_m=x_icr,
            y_icr_m=y_icr,
            ideal_wheel_angles_rad=ideal,
            q_target_rad=dict(zip(GENERALIZED_COORDINATES, map(float, q))),
            actuator_input=actuator_input,
            mechanical_output=mechanical,
            axles=axle_diagnostics,
            feasible=feasible,
            largest_feasible_scale=1.0,
            diagnostics=diagnostics,
        )

    def coordinate(
        self,
        target_axle1_mean_angle_deg: float,
        preset: str | SteeringPreset = "PUBLIC_6AXLE_BASELINE",
        mode: SteeringMode = SteeringMode.LOW_SPEED_COUNTER_PHASE,
        custom_axle_gains: Mapping[int, float] | None = None,
    ) -> VehicleSteeringResult:
        mode = SteeringMode(mode)
        selected = self.config.preset(preset) if isinstance(preset, str) else preset
        requested_previous = self._previous_q.copy()
        result = self._coordinate_once(
            target_axle1_mean_angle_deg, selected, mode, custom_axle_gains
        )
        scale = 1.0
        if not result.feasible and abs(target_axle1_mean_angle_deg) > 1.0e-12:
            low, high = 0.0, 1.0
            for _ in range(12):
                mid = 0.5 * (low + high)
                self._previous_q = requested_previous.copy()
                trial = self._coordinate_once(
                    target_axle1_mean_angle_deg * mid, selected, mode, custom_axle_gains
                )
                if trial.feasible:
                    low = mid
                else:
                    high = mid
            scale = low
            self._previous_q = requested_previous.copy()
            result = self._coordinate_once(
                target_axle1_mean_angle_deg, selected, mode, custom_axle_gains
            )
        object.__setattr__(result, "largest_feasible_scale", scale)
        self._previous_q = np.array([
            result.q_target_rad[name] for name in GENERALIZED_COORDINATES
        ])
        return result
