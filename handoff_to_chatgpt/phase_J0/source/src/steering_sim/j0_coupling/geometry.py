"""J0 hydraulic-stroke <-> mechanism-coordinate mapping.

The adapter owns one monotone table per mechanism degree of freedom, built from
the public ``SixAxleSteeringKinematics`` solver by continuation outward from the
``q = 0`` reference.  Nothing here re-implements closed-chain geometry and
nothing here reads a private ``PhaseM1Model`` attribute.

Representative equivalent stroke per actuation group:

* ``channel_front`` : ``x = 0.25 * q_front``  (ASSUMED placeholder, no CUSTOMER
  front hardpoints; identical to the M1 ``front_cylinder_interface`` entry)
* ``channel_rear_k``: ``x = L_A(q_k) - L_A(0)``  (ASSUMED choice of the A
  cylinder as the single equivalent coordinate; the CUSTOMER hardpoints and the
  A/B lengths themselves are CUSTOMER_GEOMETRY)

The B-cylinder stroke of the same axle is always produced from the same ``q``
and is never carried as an independent state.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping

import numpy as np

from steering_sim.mechanics import SixAxleSteeringKinematics

from .config import J0Config, CHANNEL_ORDER

DOF_ORDER = ("q_front", "q4", "q5", "q6")
DOF_TO_LEGACY_INDEX = {"q_front": 0, "q4": 2, "q5": 3, "q6": 4}
DOF_WHEELS = {
    "q_front": ("axle1_left", "axle1_right", "axle2_left", "axle2_right"),
    "q4": ("axle4_left", "axle4_right"),
    "q5": ("axle5_left", "axle5_right"),
    "q6": ("axle6_left", "axle6_right"),
}
WHEEL_ORDER = tuple(f"axle{a}_{s}" for a in range(1, 7) for s in ("left", "right"))
REAR_AXLES = (4, 5, 6)
FRONT_CYLINDER = "front_group_1"


class J0MappingError(RuntimeError):
    """Raised when a mapping is singular, non-monotone, or outside its envelope."""


@dataclass(frozen=True, slots=True)
class MappingStatus:
    ok: bool
    flags: tuple[str, ...]

    @property
    def label(self) -> str:
        return "OK" if self.ok else "|".join(self.flags)


@dataclass(frozen=True, slots=True)
class ExactLinkage:
    """Exact closed-chain result at one mechanism configuration."""

    q_rad: Mapping[str, float]
    wheel_angle_rad: Mapping[str, float]
    wheel_angle_deg: Mapping[str, float]
    cylinder_stroke_m: Mapping[str, float]
    max_link_residual_m: float
    condition_number: float
    singular: bool
    third_axle_max_abs_deg: float


class _DofTable:
    """Monotone one-dimensional table for a single mechanism degree of freedom."""

    def __init__(self, dof: str, q: np.ndarray, angles: dict[str, np.ndarray],
                 stroke_repr: np.ndarray, length_a: np.ndarray, length_b: np.ndarray,
                 residual: np.ndarray, condition: np.ndarray) -> None:
        self.dof = dof
        self.q = q
        self.angles = angles
        self.stroke_repr = stroke_repr
        self.length_a = length_a
        self.length_b = length_b
        self.residual = residual
        self.condition = condition
        self.angle_derivative = {
            wheel: np.gradient(values, q) for wheel, values in angles.items()
        }
        self.stroke_derivative = np.gradient(stroke_repr, q)
        # Strict monotonicity of the representative stroke is required for a
        # single-valued inverse; a flat or reversing branch must fail loudly.
        step = np.diff(stroke_repr)
        self.monotone_increasing = bool(np.all(step > 0.0))
        self.monotone_decreasing = bool(np.all(step < 0.0))
        self.monotone = self.monotone_increasing or self.monotone_decreasing

    @property
    def q_min(self) -> float:
        return float(self.q[0])

    @property
    def q_max(self) -> float:
        return float(self.q[-1])

    def angle(self, wheel: str, q_value: float) -> float:
        return float(np.interp(q_value, self.q, self.angles[wheel]))

    def angle_jacobian(self, wheel: str, q_value: float) -> float:
        return float(np.interp(q_value, self.q, self.angle_derivative[wheel]))

    def stroke(self, q_value: float) -> float:
        return float(np.interp(q_value, self.q, self.stroke_repr))

    def stroke_jacobian(self, q_value: float) -> float:
        return float(np.interp(q_value, self.q, self.stroke_derivative))

    def q_from_stroke(self, x: float) -> float:
        if not self.monotone:
            raise J0MappingError(f"{self.dof}: representative stroke is not monotone in q")
        # np.interp requires increasing sample coordinates, and the sign of
        # dx/dq is genuinely negative for the q5 and q6 groups, so the
        # decreasing branch is interpolated on the reversed arrays.
        if self.monotone_increasing:
            return float(np.interp(x, self.stroke_repr, self.q))
        return float(np.interp(x, self.stroke_repr[::-1], self.q[::-1]))


class J0GeometryAdapter:
    """Adapter around the frozen M1 closed chain for J0."""

    def __init__(self, model, config: J0Config) -> None:
        self.model = model
        self.config = config
        self.reference = model.reference
        self.kinematics = SixAxleSteeringKinematics(self.reference)
        self._step = float(config.mapping["table_step_rad"])
        self._front_stroke_per_q = float(config.mapping["front_stroke_per_q_m_per_rad"])
        self._representative_side = str(config.mapping["rear_representative_cylinder"])
        if self._representative_side != "A":
            raise J0MappingError("J0 first release only defines the A cylinder as representative")
        self._envelopes = {dof: tuple(float(v) for v in bounds)
                           for dof, bounds in model.config["geometry"]["q_envelopes_rad"].items()}
        self._zero_lengths = self._active_cylinder_lengths(np.zeros(5))
        self.tables = {dof: self._build_table(dof) for dof in DOF_ORDER}

    # ------------------------------------------------------------------ build
    def _active_cylinder_lengths(self, q_legacy: np.ndarray) -> dict[str, float]:
        solution = SixAxleSteeringKinematics(self.reference).solve(q_legacy)
        return {
            f"axle{axle}_{side}": float(solution.actuator_lengths[f"ACTUATOR_{axle}_{side}"])
            for axle in REAR_AXLES for side in ("A", "B")
        }

    @staticmethod
    def _legacy_q(dof: str, value: float) -> np.ndarray:
        q = np.zeros(5)
        q[DOF_TO_LEGACY_INDEX[dof]] = value
        return q

    def _scan(self, dof: str, bound: float) -> list[tuple[float, object]]:
        """Continuously extend the assembly branch from q=0 toward ``bound``."""
        solver = SixAxleSteeringKinematics(self.reference)
        count = max(1, int(math.ceil(abs(bound) / self._step)))
        rows: list[tuple[float, object]] = []
        for q_value in np.linspace(0.0, bound, count + 1):
            try:
                solution = solver.solve(self._legacy_q(dof, float(q_value)))
            except Exception:
                break
            rows.append((float(q_value), solution))
        return rows

    @staticmethod
    def _wheel_angles(solution) -> dict[str, float]:
        angles = {wheel: 0.0 for wheel in WHEEL_ORDER}
        for axle in range(1, 7):
            for side, legacy in (("left", "POS_Y"), ("right", "NEG_Y")):
                angles[f"axle{axle}_{side}"] = float(
                    solution.wheel_angles[f"WHEEL_{axle}_{legacy}"])
        angles["axle3_left"] = 0.0
        angles["axle3_right"] = 0.0
        return angles

    def _build_table(self, dof: str) -> _DofTable:
        lower, upper = self._envelopes[dof]
        negative = self._scan(dof, lower)
        positive = self._scan(dof, upper)
        rows = list(reversed(negative[1:])) + positive
        if len(rows) < 5:
            raise J0MappingError(f"{dof}: insufficient continuous kinematic table")
        q = np.array([value for value, _ in rows], dtype=float)
        angles = {wheel: np.empty_like(q) for wheel in WHEEL_ORDER}
        length_a = np.empty_like(q)
        length_b = np.empty_like(q)
        residual = np.empty_like(q)
        condition = np.empty_like(q)
        axle = dof[1:] if dof.startswith("q") and dof != "q_front" else None
        for index, (_, solution) in enumerate(rows):
            for wheel, value in self._wheel_angles(solution).items():
                angles[wheel][index] = value
            residual[index] = max(
                (abs(v) for v in solution.constraint_residuals.values()), default=0.0)
            condition[index] = solution.status.condition_number
            if axle is not None:
                length_a[index] = solution.actuator_lengths[f"ACTUATOR_{axle}_A"]
                length_b[index] = solution.actuator_lengths[f"ACTUATOR_{axle}_B"]
            else:
                length_a[index] = math.nan
                length_b[index] = math.nan
        # The grid spans [q_min, q_max] and contains q = 0 exactly (it is the
        # seed of both continuation scans); the zero stroke reference must be
        # taken there, not at the first grid point.
        zero_index = int(np.argmin(np.abs(q)))
        if abs(q[zero_index]) > 1.0e-15:
            raise J0MappingError(f"{dof}: continuation grid does not contain q = 0")
        if axle is None:
            stroke = self._front_stroke_per_q * q
        else:
            stroke = length_a - length_a[zero_index]
            length_b = length_b - length_b[zero_index]
        return _DofTable(dof, q, angles, stroke, length_a, length_b, residual, condition)

    # -------------------------------------------------------------- public API
    @property
    def q_zero(self) -> dict[str, float]:
        return {dof: 0.0 for dof in DOF_ORDER}

    def target(self, target_outer_angle_deg: float):
        """M1 target fit: mechanism coordinates and the seven target strokes."""
        return self.model.solve_geometry(float(target_outer_angle_deg))

    def curvature_1pm(self, target_outer_angle_deg: float) -> float:
        return float(self.model.ideal_ackermann(float(target_outer_angle_deg))[4])

    def representative_stroke(self, dof: str, q_value: float) -> float:
        return self.tables[dof].stroke(q_value)

    def stroke_jacobian(self, dof: str, q_value: float) -> float:
        return self.tables[dof].stroke_jacobian(q_value)

    def q_from_stroke(self, dof: str, x: float) -> tuple[float, MappingStatus]:
        """Invert the representative stroke.

        The returned coordinate is always usable for reporting, but a non-OK
        status means the caller must treat the step as a J0 stop condition.
        Nothing is silently clipped: an out-of-envelope request returns the
        boundary coordinate *and* the ``MAPPING_OUT_OF_ENVELOPE`` flag.
        """
        table = self.tables[dof]
        if not table.monotone:
            return table.q_from_stroke(float(np.clip(
                x, min(table.stroke_repr), max(table.stroke_repr)))), \
                MappingStatus(False, ("MAPPING_NON_MONOTONIC",))
        low, high = sorted((table.stroke(table.q_min), table.stroke(table.q_max)))
        if x < low or x > high:
            bounded = float(np.clip(x, low, high))
            return table.q_from_stroke(bounded), MappingStatus(False, ("MAPPING_OUT_OF_ENVELOPE",))
        q_value = table.q_from_stroke(x)
        jacobian = table.stroke_jacobian(q_value)
        threshold = float(self.config.mapping["singular_jacobian_threshold_m_per_rad"])
        if not math.isfinite(jacobian) or abs(jacobian) < threshold:
            return q_value, MappingStatus(False, ("MAPPING_SINGULAR",))
        return q_value, MappingStatus(True, ())

    def q_from_strokes(self, x_by_channel: Mapping[str, float]
                       ) -> tuple[dict[str, float], dict[str, MappingStatus]]:
        q_values: dict[str, float] = {}
        status: dict[str, MappingStatus] = {}
        for channel in CHANNEL_ORDER:
            dof = {"channel_front": "q_front", "channel_rear_1": "q4",
                   "channel_rear_2": "q5", "channel_rear_3": "q6"}[channel]
            q_values[dof], status[channel] = self.q_from_stroke(dof, float(x_by_channel[channel]))
        return q_values, status

    def wheel_angles_deg(self, q_values: Mapping[str, float]) -> dict[str, float]:
        angles = {wheel: 0.0 for wheel in WHEEL_ORDER}
        for dof, wheels in DOF_WHEELS.items():
            table = self.tables[dof]
            for wheel in wheels:
                angles[wheel] = math.degrees(table.angle(wheel, float(q_values[dof])))
        angles["axle3_left"] = 0.0
        angles["axle3_right"] = 0.0
        return angles

    def wheel_angle_jacobian(self, q_values: Mapping[str, float]
                             ) -> dict[str, dict[str, float]]:
        return {
            dof: {wheel: self.tables[dof].angle_jacobian(wheel, float(q_values[dof]))
                  for wheel in wheels}
            for dof, wheels in DOF_WHEELS.items()
        }

    def companion_stroke(self, dof: str, q_value: float) -> float:
        """Non-representative (B) cylinder stroke produced by the SAME q."""
        table = self.tables[dof]
        if not math.isfinite(float(table.length_b[0])):
            raise J0MappingError(f"{dof}: no companion cylinder for this group")
        return float(np.interp(q_value, table.q, table.length_b))

    def seven_cylinder_strokes(self, q_values: Mapping[str, float]) -> dict[str, float]:
        strokes = {FRONT_CYLINDER: self._front_stroke_per_q * float(q_values["q_front"])}
        for dof in ("q4", "q5", "q6"):
            axle = dof[1:]
            strokes[f"axle{axle}_A"] = self.tables[dof].stroke(float(q_values[dof]))
            strokes[f"axle{axle}_B"] = self.companion_stroke(dof, float(q_values[dof]))
        return strokes

    def exact_linkage(self, q_values: Mapping[str, float]) -> ExactLinkage:
        """Exact closed-chain evaluation used for the recorded constraint residuals."""
        target = np.zeros(5)
        for dof, index in DOF_TO_LEGACY_INDEX.items():
            target[index] = float(q_values[dof])
        try:
            solution = self.kinematics.solve(target)
        except Exception:
            self.kinematics.reset()
            steps = max(2, int(math.ceil(float(np.max(np.abs(target))) / 0.02)) + 1)
            solution = None
            for factor in np.linspace(0.0, 1.0, steps):
                solution = self.kinematics.solve(target * factor)
        wheel_rad = self._wheel_angles(solution)
        stroke: dict[str, float] = {
            FRONT_CYLINDER: self._front_stroke_per_q * float(q_values["q_front"])}
        for axle in REAR_AXLES:
            for side in ("A", "B"):
                name = f"axle{axle}_{side}"
                length = float(solution.actuator_lengths[f"ACTUATOR_{axle}_{side}"])
                stroke[name] = length - self._zero_lengths[name]
        return ExactLinkage(
            q_rad=dict(q_values),
            wheel_angle_rad=wheel_rad,
            wheel_angle_deg={wheel: math.degrees(value) for wheel, value in wheel_rad.items()},
            cylinder_stroke_m=stroke,
            max_link_residual_m=max(
                (abs(v) for v in solution.constraint_residuals.values()), default=0.0),
            condition_number=float(solution.status.condition_number),
            singular=bool(solution.status.singular),
            third_axle_max_abs_deg=max(abs(math.degrees(wheel_rad["axle3_left"])),
                                       abs(math.degrees(wheel_rad["axle3_right"]))),
        )

    def table_quality(self) -> dict[str, dict[str, float]]:
        return {
            dof: {
                "q_min_rad": table.q_min,
                "q_max_rad": table.q_max,
                "max_link_residual_m": float(np.max(table.residual)),
                "max_condition_number": float(np.max(table.condition)),
                "stroke_min_m": float(np.min(table.stroke_repr)),
                "stroke_max_m": float(np.max(table.stroke_repr)),
                "min_abs_stroke_jacobian_m_per_rad": float(np.min(np.abs(table.stroke_derivative))),
                "monotone": float(table.monotone),
            }
            for dof, table in self.tables.items()
        }
