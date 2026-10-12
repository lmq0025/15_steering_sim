"""J0 hydraulic-stroke <-> mechanism-coordinate mapping.

The adapter owns one monotone table per mechanism degree of freedom, built by
continuation outward from the ``q = 0`` reference through the mechanism model's
``mechanism_state`` entry point.  Nothing here re-implements closed-chain
geometry and nothing here reads a private model attribute.

PHASE M3 adds a second mechanism: the adapter is mechanism-agnostic, so the same
J0 loop, road-load conversion and reported ``dq``/``ds`` Jacobians serve both the
CUSTOMER as-built linkage and the REDESIGNED_ACKERMANN_TRANSMISSION.

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

from .config import J0Config, CHANNEL_ORDER

DOF_ORDER = ("q_front", "q4", "q5", "q6")
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
    """Adapter around a rigid-link mechanism (AS_BUILT or REDESIGNED).

    The adapter never re-implements closed-chain geometry: it obtains every
    wheel angle, cylinder stroke, residual, and condition number from the
    mechanism model's ``mechanism_state`` entry point.  That entry point exists
    on both ``PhaseM1Model`` (CUSTOMER as-built linkage) and
    ``RedesignedAckermannModel`` (PHASE M3 engineering redesign), so the J0
    loop, the road-load conversion, and the reported Jacobians automatically
    follow whichever mechanism is selected.
    """

    def __init__(self, model, config: J0Config, mechanical_mode: str | None = None
                 ) -> None:
        self.model = model
        self.config = config
        self.reference = model.reference
        self.mechanical_mode = str(mechanical_mode or getattr(
            model, "tag", "AS_BUILT_REFERENCE"))
        self._step = float(config.mapping["table_step_rad"])
        #: 行程反解在机构包络端点处允许的数值容差（m）。只用于把"缸正好走到
        #: 机构包络的端点"与"机构不可解"区分开；超出该容差仍然显式失败。
        self._envelope_tolerance_m = float(
            config.mapping.get("envelope_tolerance_m", 2.0e-3))
        self._front_stroke_per_q = float(config.mapping["front_stroke_per_q_m_per_rad"])
        self._representative_side = str(config.mapping["rear_representative_cylinder"])
        if self._representative_side != "A":
            raise J0MappingError("J0 first release only defines the A cylinder as representative")
        envelopes = getattr(model, "q_envelopes", None)
        if envelopes is None:
            envelopes = model.config["geometry"]["q_envelopes_rad"]
        self._envelopes = {dof: (float(bounds[0]), float(bounds[1]))
                           for dof, bounds in envelopes.items()}
        self.tables = {dof: self._build_table(dof) for dof in DOF_ORDER}

    # ------------------------------------------------------------------ build
    def _zero_q(self) -> dict[str, float]:
        return {dof: 0.0 for dof in DOF_ORDER}

    def _state(self, dof: str, value: float):
        q_values = self._zero_q()
        q_values[dof] = float(value)
        return self.model.mechanism_state(q_values)

    def _scan(self, dof: str, bound: float) -> list[tuple[float, object]]:
        """Continuously extend the assembly branch from q=0 toward ``bound``."""
        count = max(1, int(math.ceil(abs(bound) / self._step)))
        rows: list[tuple[float, object]] = []
        for q_value in np.linspace(0.0, bound, count + 1):
            try:
                state = self._state(dof, float(q_value))
            except Exception:
                break
            rows.append((float(q_value), state))
        return rows

    def _build_table(self, dof: str) -> _DofTable:
        lower, upper = self._envelopes[dof]
        negative = self._scan(dof, lower)
        positive = self._scan(dof, upper)
        rows = list(reversed(negative[1:])) + positive
        if len(rows) < 5:
            raise J0MappingError(f"{dof}: insufficient continuous kinematic table")
        q = np.array([value for value, _ in rows], dtype=float)
        angles = {wheel: np.empty_like(q) for wheel in WHEEL_ORDER}
        stroke_a = np.empty_like(q)
        stroke_b = np.empty_like(q)
        residual = np.empty_like(q)
        condition = np.empty_like(q)
        axle = dof[1:] if dof.startswith("q") and dof != "q_front" else None
        for index, (_, state) in enumerate(rows):
            for wheel in WHEEL_ORDER:
                angles[wheel][index] = float(state.wheel_angles_rad[wheel])
            residual[index] = float(state.max_residual_m)
            condition[index] = float(state.condition_number)
            if axle is not None:
                # PHASE M3：J0 单通道用"对称双缸推程缸"等效代表行程；
                # 逐只缸的真实几何行程仍由 mechanism_state 单独给出。
                stroke_a[index] = float(
                    state.representative_stroke_m[f"axle{axle}"])
                stroke_b[index] = state.cylinder_stroke_m[f"axle{axle}_B"]
            else:
                stroke_a[index] = math.nan
                stroke_b[index] = math.nan
        # The grid spans [q_min, q_max] and contains q = 0 exactly (it is the
        # seed of both continuation scans); the stroke reference is taken there.
        zero_index = int(np.argmin(np.abs(q)))
        if abs(q[zero_index]) > 1.0e-15:
            raise J0MappingError(f"{dof}: continuation grid does not contain q = 0")
        if axle is None:
            stroke = self._front_stroke_per_q * q
        else:
            stroke = stroke_a
        return _DofTable(dof, q, angles, stroke, stroke_a, stroke_b, residual,
                         condition)

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
        if x < low - self._envelope_tolerance_m or \
                x > high + self._envelope_tolerance_m:
            bounded = float(np.clip(x, low, high))
            return table.q_from_stroke(bounded), MappingStatus(False, ("MAPPING_OUT_OF_ENVELOPE",))
        if x < low or x > high:
            # PHASE J1-R2：**碰到机械行程端点**与"机构不可解"是两件不同的事。
            # 前者是真实物理事件（缸走到头了），后者才是求解失败。这里只在
            # 极小的数值容差内（默认 2 mm）把坐标夹到端点，并返回一个**独立且
            # 会被逐点记录**的标志，绝不静默 —— 调用方把它计入
            # envelope_limit_samples，并在结果里如实报出。
            bounded = float(np.clip(x, low, high))
            return table.q_from_stroke(bounded), MappingStatus(
                False, ("MAPPING_AT_ENVELOPE_LIMIT",))
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
        state = self.model.mechanism_state(dict(q_values))
        wheel_rad = {wheel: float(state.wheel_angles_rad[wheel]) for wheel in WHEEL_ORDER}
        stroke = {name: float(value)
                  for name, value in state.cylinder_stroke_m.items()}
        return ExactLinkage(
            q_rad=dict(q_values),
            wheel_angle_rad=wheel_rad,
            wheel_angle_deg={wheel: math.degrees(value) for wheel, value in wheel_rad.items()},
            cylinder_stroke_m=stroke,
            max_link_residual_m=float(state.max_residual_m),
            condition_number=float(state.condition_number),
            singular=bool(state.singular),
            third_axle_max_abs_deg=float(state.third_axle_max_abs_deg),
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
