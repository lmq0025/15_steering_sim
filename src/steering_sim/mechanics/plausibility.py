"""Non-claiming plausibility metrics for mechanical steering outputs."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np

from .io_model import MechanicalSteeringOutput, WHEEL_OUTPUT_ORDER
from .kinematics import ideal_ackermann_angles


@dataclass(frozen=True, slots=True)
class SteeringPlausibilityReport:
    maximum_wheel_angle_jump_rad: float
    monotonic_by_wheel: Mapping[str, bool]
    left_right_same_sign_fraction: float
    maximum_ackermann_reference_error_deg: float | None
    maximum_paired_cylinder_residual_m: float
    all_reachable: bool
    any_out_of_range: bool
    minimum_singularity_proximity: float


class SteeringPlausibilityEvaluator:
    """Compute trends and reference errors; this is not accuracy validation."""

    @staticmethod
    def evaluate(
        outputs: Sequence[MechanicalSteeringOutput],
        *,
        ackermann_geometry_m: Mapping[int, tuple[float, float]] | None = None,
        monotonic_tolerance_rad: float = 1.0e-10,
    ) -> SteeringPlausibilityReport:
        if not outputs:
            raise ValueError("at least one output is required")
        series = {
            name: np.array([output.wheel_angles_rad[name] for output in outputs])
            for name in WHEEL_OUTPUT_ORDER
        }
        maximum_jump = max(
            (float(np.max(np.abs(np.diff(values)), initial=0.0)) for values in series.values()),
            default=0.0,
        )
        monotonic = {}
        for name, values in series.items():
            differences = np.diff(values)
            monotonic[name] = bool(
                np.all(differences >= -monotonic_tolerance_rad)
                or np.all(differences <= monotonic_tolerance_rad)
            )

        relation = []
        ackermann_errors = []
        for output in outputs:
            for axle in range(1, 7):
                pos = output.wheel_angles_rad[f"axle{axle}_POS_Y"]
                neg = output.wheel_angles_rad[f"axle{axle}_NEG_Y"]
                if max(abs(pos), abs(neg)) > monotonic_tolerance_rad:
                    relation.append(np.sign(pos) == np.sign(neg))
                if ackermann_geometry_m and axle in ackermann_geometry_m:
                    wheelbase, track = ackermann_geometry_m[axle]
                    inner, outer = (pos, neg) if abs(pos) >= abs(neg) else (neg, pos)
                    if abs(inner) > monotonic_tolerance_rad:
                        _, ideal_outer = ideal_ackermann_angles(inner, wheelbase, track)
                        ackermann_errors.append(np.degrees(outer - ideal_outer))

        paired = [
            abs(value)
            for output in outputs
            for name, value in output.actuator_residuals.items()
            if name.endswith("_PAIRED_RMS")
        ]
        proximity = [float(output.diagnostics["singularity_proximity"]) for output in outputs]
        return SteeringPlausibilityReport(
            maximum_wheel_angle_jump_rad=maximum_jump,
            monotonic_by_wheel=monotonic,
            left_right_same_sign_fraction=float(np.mean(relation)) if relation else 1.0,
            maximum_ackermann_reference_error_deg=(
                float(np.max(np.abs(ackermann_errors))) if ackermann_errors else None
            ),
            maximum_paired_cylinder_residual_m=max(paired, default=0.0),
            all_reachable=all(bool(output.diagnostics["reachable"]) for output in outputs),
            any_out_of_range=any(output.out_of_range for output in outputs),
            minimum_singularity_proximity=min(proximity),
        )
