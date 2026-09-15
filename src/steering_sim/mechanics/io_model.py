"""Stable actuator-position to twelve-wheel-angle mechanical I/O layer."""
from __future__ import annotations

from dataclasses import dataclass
import math
from types import MappingProxyType
from typing import Mapping

import numpy as np
from scipy.optimize import minimize_scalar

from .io_parameters import CalibrationParameterSet, PositionDefinition
from .kinematics import (
    ACTUATOR_ORDER, GENERALIZED_COORDINATES, SixAxleSteeringKinematics,
    UnreachableGeometryError,
)


WHEEL_OUTPUT_ORDER = tuple(
    f"axle{axle}_{side}" for axle in range(1, 7) for side in ("POS_Y", "NEG_Y")
)
INVERSE_X_TOL_RAD = 1.0e-12
INVERSE_RESIDUAL_TOL_M = 1.0e-9
INVERSE_OBJECTIVE_TIE_TOL_M2 = 1.0e-20
RANGE_SAMPLE_COUNT = 33
INVERSE_REFINEMENT_MAX_ITERATIONS = 8


class InvalidActuatorPositionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ActuatorPosition:
    value_m: float
    definition: PositionDefinition = PositionDefinition.ABSOLUTE_LENGTH_M

    def __post_init__(self) -> None:
        object.__setattr__(self, "definition", PositionDefinition(self.definition))
        if not math.isfinite(self.value_m):
            raise InvalidActuatorPositionError("actuator position must be finite")


@dataclass(frozen=True, slots=True)
class MechanicalActuatorInput:
    front_position: float
    axle3_A: ActuatorPosition | None
    axle3_B: ActuatorPosition | None
    axle4_A: ActuatorPosition | None
    axle4_B: ActuatorPosition | None
    axle5_A: ActuatorPosition | None
    axle5_B: ActuatorPosition | None
    axle6_A: ActuatorPosition | None
    axle6_B: ActuatorPosition | None

    def __post_init__(self) -> None:
        if not math.isfinite(self.front_position):
            raise InvalidActuatorPositionError("front_position must be finite")

    def rear_pair(self, axle: int) -> tuple[ActuatorPosition | None, ActuatorPosition | None]:
        if axle not in range(3, 7):
            raise ValueError("rear actuator axle must be 3..6")
        return getattr(self, f"axle{axle}_A"), getattr(self, f"axle{axle}_B")


@dataclass(frozen=True, slots=True)
class MechanicalSteeringOutput:
    wheel_angles_rad: Mapping[str, float]
    generalized_coordinates: Mapping[str, float]
    actuator_residuals: Mapping[str, float]
    constraint_residuals: Mapping[str, float]
    valid: bool
    singular: bool
    out_of_range: bool
    diagnostics: Mapping[str, object]

    def __post_init__(self) -> None:
        for name in (
            "wheel_angles_rad", "generalized_coordinates", "actuator_residuals",
            "constraint_residuals", "diagnostics",
        ):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))


@dataclass(frozen=True, slots=True)
class _RearInverseResult:
    q_rad: float
    residuals_m: Mapping[str, float]
    predicted_lengths_m: Mapping[str, float]
    objective: float
    out_of_range: bool
    sensors_used: int


class MechanicalSteeringIOModel:
    """Formal mechanical I/O: actuator positions -> q -> frozen closed chain -> wheels."""

    def __init__(
        self,
        kinematics: SixAxleSteeringKinematics,
        parameters: CalibrationParameterSet,
    ) -> None:
        self.kinematics = kinematics
        self.reference = kinematics.reference
        self.parameters = parameters
        expected_actuators = {f"ACTUATOR_{axle}_{side}" for axle in range(3, 7) for side in ("A", "B")}
        if set(parameters.actuators) != expected_actuators:
            raise ValueError("calibration set must contain exactly the eight rear actuators")
        expected_wheels = {f"WHEEL_{axle}_{side}" for axle in range(1, 7) for side in ("POS_Y", "NEG_Y")}
        if set(parameters.wheel_zero_offsets) != expected_wheels:
            raise ValueError("calibration set must contain exactly twelve wheel offsets")
        self._previous_q = np.zeros(5)
        self._solution_cache: dict[tuple[int, float], object] = {}

    def reset(self, q: np.ndarray | None = None) -> None:
        self._previous_q = np.zeros(5) if q is None else np.asarray(q, dtype=float).copy()
        if self._previous_q.shape != (5,):
            raise ValueError("q must have shape (5,)")
        self.kinematics.reset()

    def _solution_for_rear_q(self, axle: int, q_value: float):
        key = (axle, float(q_value))
        if key in self._solution_cache:
            return self._solution_cache[key]
        q = np.zeros(5)
        q[axle - 2] = q_value
        solution = SixAxleSteeringKinematics(self.reference).solve(q)
        self._solution_cache[key] = solution
        return solution

    def _lengths_for_rear_q(self, axle: int, q_value: float) -> Mapping[str, float]:
        return self._solution_for_rear_q(axle, q_value).actuator_lengths

    def _to_absolute(self, actuator_id: str, position: ActuatorPosition | None) -> float | None:
        if position is None:
            return None
        length = self.parameters.actuators[actuator_id].to_absolute_length(
            position.value_m, position.definition
        )
        if not math.isfinite(length) or length <= 0.0:
            raise InvalidActuatorPositionError(f"{actuator_id}: converted absolute length is invalid")
        return length

    def _inverse_rear_axle(
        self, axle: int, position_a: ActuatorPosition | None, position_b: ActuatorPosition | None
    ) -> _RearInverseResult:
        actuator_a, actuator_b = f"ACTUATOR_{axle}_A", f"ACTUATOR_{axle}_B"
        measured = {
            actuator_a: self._to_absolute(actuator_a, position_a),
            actuator_b: self._to_absolute(actuator_b, position_b),
        }
        available = {name: value for name, value in measured.items() if value is not None}
        if not available:
            raise InvalidActuatorPositionError(f"axle {axle}: at least one position sensor is required")
        weights = {
            actuator_a: self.parameters.paired_weight_a.value,
            actuator_b: self.parameters.paired_weight_b.value,
        }
        lower = self.parameters.inverse_lower_q_rad.value
        upper = self.parameters.inverse_upper_q_rad.value

        def objective(q_value):
            predicted = self._lengths_for_rear_q(axle, float(q_value))
            return float(sum(
                weights[name] * (predicted[name] - value) ** 2
                for name, value in available.items()
            ))

        previous = float(np.clip(self._previous_q[axle - 2], lower, upper))
        grid = np.linspace(lower, upper, RANGE_SAMPLE_COUNT)
        ranges = {name: [] for name in available}
        grid_cost = []
        for candidate_q in grid:
            lengths = self._lengths_for_rear_q(axle, float(candidate_q))
            for name in available:
                ranges[name].append(lengths[name])
            grid_cost.append(objective(candidate_q))
        candidates = [(float(grid[0]), grid_cost[0]), (float(grid[-1]), grid_cost[-1])]
        local_minima = [
            index for index in range(1, len(grid) - 1)
            if grid_cost[index] <= grid_cost[index - 1]
            and grid_cost[index] <= grid_cost[index + 1]
        ]
        if not local_minima:
            local_minima = [int(np.argmin(grid_cost))]
        for index in local_minima:
            left = float(grid[max(0, index - 1)])
            right = float(grid[min(len(grid) - 1, index + 1)])
            if left == right:
                continue
            result = minimize_scalar(
                objective, method="bounded", bounds=(left, right),
                options={"xatol": INVERSE_X_TOL_RAD, "maxiter": 200},
            )
            candidates.append((float(result.x), float(result.fun)))
        best_cost = min(cost for _, cost in candidates)
        eligible = [
            candidate for candidate in candidates
            if candidate[1] <= best_cost + INVERSE_OBJECTIVE_TIE_TOL_M2
        ]
        q_value, objective_value = min(eligible, key=lambda candidate: abs(candidate[0] - previous))
        for _ in range(INVERSE_REFINEMENT_MAX_ITERATIONS):
            solution = self._solution_for_rear_q(axle, q_value)
            numerator = 0.0
            denominator = 0.0
            for name, value in available.items():
                row = ACTUATOR_ORDER.index(name)
                derivative = solution.actuator_jacobian[row, axle - 2]
                length_residual = solution.actuator_lengths[name] - value
                numerator += weights[name] * derivative * length_residual
                denominator += weights[name] * derivative**2
            if denominator <= 0.0:
                break
            refined = float(np.clip(q_value - numerator / denominator, lower, upper))
            if abs(refined - q_value) <= INVERSE_X_TOL_RAD:
                q_value = refined
                break
            if objective(refined) > objective(q_value):
                break
            q_value = refined
        predicted = self._lengths_for_rear_q(axle, q_value)
        residuals = {name: predicted[name] - value for name, value in available.items()}
        objective_value = objective(q_value)
        out_of_range = any(
            value < min(ranges[name]) - INVERSE_RESIDUAL_TOL_M
            or value > max(ranges[name]) + INVERSE_RESIDUAL_TOL_M
            for name, value in available.items()
        )
        return _RearInverseResult(
            q_value, residuals,
            {actuator_a: predicted[actuator_a], actuator_b: predicted[actuator_b]},
            objective_value,
            out_of_range, len(available),
        )

    def solve_from_actuators(self, actuator_input: MechanicalActuatorInput) -> MechanicalSteeringOutput:
        q = np.zeros(5)
        q[0] = self.parameters.front_mapping.position_to_q_front(actuator_input.front_position)
        lower = self.parameters.inverse_lower_q_rad.value
        upper = self.parameters.inverse_upper_q_rad.value
        out_of_range = not lower <= q[0] <= upper
        actuator_residuals = {}
        predicted_lengths = {}
        inverse_diagnostics = {}

        for axle in range(3, 7):
            inverse = self._inverse_rear_axle(axle, *actuator_input.rear_pair(axle))
            q[axle - 2] = inverse.q_rad
            actuator_residuals.update(inverse.residuals_m)
            actuator_residuals[f"AXLE_{axle}_PAIRED_RMS"] = float(
                np.sqrt(np.mean(np.square(list(inverse.residuals_m.values()))))
            )
            predicted_lengths.update(inverse.predicted_lengths_m)
            inverse_diagnostics[f"axle{axle}"] = {
                "objective": inverse.objective,
                "sensors_used": inverse.sensors_used,
            }
            out_of_range = out_of_range or inverse.out_of_range

        restarted_from_reference = False
        crossing_zero = np.any(
            (self._previous_q * q <= 0.0)
            & (np.abs(self._previous_q - q) > INVERSE_X_TOL_RAD)
        )
        if crossing_zero:
            self.kinematics.reset()
            restarted_from_reference = True
        try:
            solution = self.kinematics.solve(q)
        except UnreachableGeometryError:
            self.kinematics.reset()
            restarted_from_reference = True
            solution = self.kinematics.solve(q)
        wheel_angles = {}
        for axle in range(1, 7):
            for side in ("POS_Y", "NEG_Y"):
                public_name = f"axle{axle}_{side}"
                internal_name = f"WHEEL_{axle}_{side}"
                wheel_angles[public_name] = (
                    solution.wheel_angles[internal_name]
                    + self.parameters.wheel_zero_offsets[internal_name].value
                )
        generalized = dict(zip(GENERALIZED_COORDINATES, map(float, q)))
        singular = bool(solution.status.singular)
        diagnostics = {
            "inverse": inverse_diagnostics,
            "predicted_actuator_lengths_m": predicted_lengths,
            "constraint_condition_number": solution.status.condition_number,
            "reachable": solution.status.reachable,
            "singularity_proximity": (
                0.0 if not np.isfinite(solution.status.condition_number)
                else 1.0 / max(solution.status.condition_number, 1.0)
            ),
            "range_definition": "numerical inverse search bound; not a mechanical limit",
            "reference_branch_restart": restarted_from_reference,
        }
        self._previous_q = q.copy()
        return MechanicalSteeringOutput(
            wheel_angles, generalized, actuator_residuals,
            solution.constraint_residuals,
            valid=not out_of_range and not singular,
            singular=singular,
            out_of_range=out_of_range,
            diagnostics=diagnostics,
        )

    def inputs_from_generalized_coordinates(
        self,
        q: np.ndarray,
        definition: PositionDefinition = PositionDefinition.ABSOLUTE_LENGTH_M,
    ) -> MechanicalActuatorInput:
        """Synthetic/calibration helper for q -> positions; not a driver command law."""
        q_array = np.asarray(q, dtype=float)
        if q_array.shape != (5,):
            raise ValueError("q must have shape (5,)")
        solution = SixAxleSteeringKinematics(self.reference).solve(q_array)
        positions = {}
        for axle in range(3, 7):
            for side in ("A", "B"):
                actuator_id = f"ACTUATOR_{axle}_{side}"
                raw = self.parameters.actuators[actuator_id].from_absolute_length(
                    solution.actuator_lengths[actuator_id], PositionDefinition(definition)
                )
                positions[f"axle{axle}_{side}"] = ActuatorPosition(raw, definition)
        return MechanicalActuatorInput(
            front_position=self.parameters.front_mapping.q_front_to_position(q_array[0]),
            axle3_A=positions["axle3_A"], axle3_B=positions["axle3_B"],
            axle4_A=positions["axle4_A"], axle4_B=positions["axle4_B"],
            axle5_A=positions["axle5_A"], axle5_B=positions["axle5_B"],
            axle6_A=positions["axle6_A"], axle6_B=positions["axle6_B"],
        )
