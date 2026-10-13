"""Metric extraction and explainable four-level grading for D2."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Callable, Mapping

import numpy as np

from steering_sim.degradation.damage import DegradationModelConfig, DegradationState
from steering_sim.degradation.prediction import parameters_from_damage
from steering_sim.hydraulics_engineering import (EngineeringHydraulicParameters,
                                                  EngineeringHydraulicSystem)
from steering_sim.j0_coupling.config import CHANNEL_ORDER, J0CaseConfig
from steering_sim.j0_coupling.runner import J0CaseResult, J0Runner

from .config import QualityConfig

GRADE_ORDER = ("HEALTHY", "SUBHEALTHY", "DEGRADED", "DANGEROUS")


@dataclass(frozen=True, slots=True)
class AssessmentCase:
    case_id: str
    target_outer_angle_deg: float
    speed_kmh: float
    duration_s: float
    reference_time_s: float
    category: str = "standard"
    profile_factory: Callable[[], Callable[[float], tuple[float, float]]] | None = None

    def j0_case(self) -> J0CaseConfig:
        return J0CaseConfig(
            id=self.case_id,
            target_outer_angle_deg=self.target_outer_angle_deg,
            speed_kmh=self.speed_kmh,
            duration_s=self.duration_s,
            reference_time_s=self.reference_time_s,
            hold_time_s=max(0.0, self.duration_s - self.reference_time_s))


@dataclass(frozen=True, slots=True)
class AssessmentResult:
    row: Mapping[str, Any]
    dynamic: J0CaseResult


def _smooth(t: float, span: float) -> tuple[float, float]:
    x = min(max(t / span, 0.0), 1.0)
    return x * x * (3.0 - 2.0 * x), 6.0 * x * (1.0 - x) / span


def reversal_profile() -> Callable[[float], tuple[float, float]]:
    """0 -> +10 deg -> -10 deg -> 0, normalized by the case target."""
    # Keep the already accepted J1-R2 sequence definition exactly: the extra
    # case duration after this 5.5 s plan is the final zero-angle settling hold.
    legs = ((1.0, 0.90), (-1.0, 0.90), (0.0, 1.60))
    ramp = 1.00
    plan: list[tuple[float, float, float, float, bool]] = []
    clock = 0.0
    current = 0.0
    for target, hold in legs:
        plan.append((clock, current, target, ramp, True))
        clock += ramp
        plan.append((clock, target, target, hold, False))
        clock += hold
        current = target

    def profile(t: float) -> tuple[float, float]:
        for start, begin, end, span, moving in plan:
            if t < start + span:
                if not moving:
                    return end, 0.0
                fraction, rate = _smooth(t - start, span)
                return begin + (end - begin) * fraction, (end - begin) * rate
        return 0.0, 0.0
    return profile


def standard_cases() -> tuple[AssessmentCase, ...]:
    """Configurable compact suite; all cases run through the full 22-state model."""
    return (
        AssessmentCase("STD_ZERO", 0.0, 0.0, 0.60, 0.40),
        AssessmentCase("STD_L2", 2.0, 5.0, 0.75, 0.40),
        AssessmentCase("STD_R2", -2.0, 5.0, 0.75, 0.40),
        AssessmentCase("STD_L10", 10.0, 5.0, 1.25, 0.8333333333),
        AssessmentCase("STD_R10", -10.0, 5.0, 1.25, 0.8333333333),
        AssessmentCase("STD_L30", 30.0, 0.0, 3.50, 2.50),
        AssessmentCase("STD_R30", -30.0, 0.0, 3.50, 2.50),
        AssessmentCase("STD_REVERSE", 10.0, 10.0, 6.40, 1.00,
                       category="stress_diagnostic",
                       profile_factory=reversal_profile),
        AssessmentCase("STD_MID_SPEED", 10.0, 20.0, 1.35, 0.8333333333),
    )


def _worst_grade(first: str, second: str) -> str:
    return GRADE_ORDER[max(GRADE_ORDER.index(first), GRADE_ORDER.index(second))]


def grade_metrics(metrics: Mapping[str, float], config: QualityConfig,
                  *, completed: bool) -> tuple[str, tuple[str, ...]]:
    if not completed:
        return "DANGEROUS", ("22_STATE_SIMULATION_NOT_COMPLETED",)
    overall = "HEALTHY"
    causes: list[str] = []
    for name, limits in config.thresholds.items():
        value = float(metrics.get(name, math.nan))
        if not math.isfinite(value):
            return "DANGEROUS", (f"{name}:NON_FINITE",)
        direction = str(limits["direction"])
        ordered = ("healthy", "subhealthy", "degraded")
        level = "DANGEROUS"
        for index, label in enumerate(ordered):
            threshold = float(limits[label])
            passes = value <= threshold if direction == "max" else value >= threshold
            if passes:
                level = GRADE_ORDER[index]
                break
        overall = _worst_grade(overall, level)
        if level != "HEALTHY":
            causes.append(f"{name}={value:.6g}:{level}")
    return overall, tuple(causes)


def _extract_metrics(result: J0CaseResult,
                     parameters: EngineeringHydraulicParameters) -> dict[str, float]:
    summary = result.summary
    samples = result.samples
    relief_mpa = min(item.relief_pressure_pa for item in parameters.supplies.values()) / 1e6
    peak_force_capacity = max(
        0.5 * (item.cylinder.area_a_m2 + item.cylinder.area_b_m2)
        * parameters.supplies[item.supply].relief_pressure_pa
        for item in parameters.channels)
    peak_force = max((float(value) for value in
                      summary.get("peak_hydraulic_force_n", {}).values()), default=math.nan)
    margins = []
    demand_ratios = []
    available_flows = []
    pressure_margins = []
    hydraulic_system = EngineeringHydraulicSystem(parameters)
    for supply in parameters.supply_names:
        margin = np.asarray(samples.get(f"pump_capacity_margin_{supply}_m3_s", []), dtype=float)
        pressure = np.asarray(samples.get(f"supply_pressure_{supply}_mpa_g", []), dtype=float)
        if margin.size:
            minimum = float(np.min(margin))
            margins.append(minimum)
            available = np.array([
                max(1.0e-15, hydraulic_system.available_pump_flow(
                    supply, p * 1e6)) for p in pressure])
            if available.size == margin.size:
                available_flows.append(float(np.min(available)))
                demand_ratios.append(float(np.max(1.0 - margin / available)))
        if pressure.size:
            channel_peaks = []
            for channel in parameters.channels:
                if channel.supply == supply:
                    channel_peaks.extend((
                        np.asarray(samples.get(f"{channel.name}_pA_mpa_g", []), dtype=float),
                        np.asarray(samples.get(f"{channel.name}_pB_mpa_g", []), dtype=float)))
            if channel_peaks and all(item.size == pressure.size for item in channel_peaks):
                chamber = np.maximum.reduce(channel_peaks)
                pressure_margins.append(float(np.min(pressure - chamber)))
    tail_start = max(0, int(len(samples.get("time_s", ())) * 0.8))
    displacement_errors = []
    for channel in CHANNEL_ORDER:
        actual = np.asarray(samples.get(f"{channel}_x_m", []), dtype=float)
        commanded = np.asarray(samples.get(f"{channel}_x_ref_eff_m", []), dtype=float)
        if actual.size and actual.size == commanded.size:
            displacement_errors.append(float(np.max(
                np.abs(actual[tail_start:] - commanded[tail_start:]))))
    return {
        "max_tracking_error_deg": float(summary.get("max_tracking_error_vs_command_deg", math.nan)),
        "rms_tracking_error_deg": float(summary.get("rms_tracking_error_vs_command_deg", math.nan)),
        "settling_delay_s": max(0.0, float(summary.get("settling_time_to_0p5deg_s", math.nan))
                                - float(summary.get("reference_time_s", 0.0))),
        "steady_tracking_error_deg": float(summary.get("steady_max_tracking_error_vs_command_deg", math.nan)),
        "cylinder_displacement_error_mm": 1000.0 * max(
            displacement_errors, default=math.nan),
        "pump_demand_ratio": max(demand_ratios, default=math.nan),
        "minimum_available_pump_flow_lpm": 60000.0 * min(
            available_flows, default=math.nan),
        "minimum_pump_flow_margin_lpm": 60000.0 * min(margins, default=math.nan),
        "minimum_supply_pressure_margin_mpa": min(pressure_margins, default=math.nan),
        "valve_saturation_fraction": float(summary.get("control_saturation_fraction", math.nan)),
        "peak_pressure_utilization": float(summary.get("max_pressure_mpa_g", math.nan)) / relief_mpa,
        "peak_pressure_mpa_g": float(summary.get("max_pressure_mpa_g", math.nan)),
        "actuator_force_utilization": peak_force / peak_force_capacity,
        "peak_hydraulic_force_n": peak_force,
        "tail_pressure_ripple_mpa": float(summary.get("max_tail_pressure_ripple_mpa", math.nan)),
    }


class QualityAssessor:
    """Runs the authoritative coupled dynamics; no display-side degradation math."""

    def __init__(self, runner: J0Runner, config: QualityConfig) -> None:
        if runner.hydraulic.state_size != 22:
            raise ValueError("D2 requires the formal 22-state hydraulic model")
        if runner.engineering_parameters is None:
            raise ValueError("D2 requires ENGINEERING_HYDRAULIC_V1")
        self.runner = runner
        self.config = config

    def run(self, state_label: str, source: str, case: AssessmentCase) -> AssessmentResult:
        dynamic = self.runner.run_case(
            case.j0_case(),
            profile=case.profile_factory() if case.profile_factory else None)
        metrics = _extract_metrics(dynamic, self.runner.engineering_parameters)
        if case.profile_factory is not None and dynamic.completed:
            profile = case.profile_factory()
            times = dynamic.samples["time_s"]
            moving = np.asarray([abs(profile(float(t))[1]) > 1.0e-8 for t in times])
            command_end = float(times[np.flatnonzero(moving)[-1]]) if np.any(moving) else 0.0
            errors = np.maximum.reduce([
                np.abs(dynamic.samples[f"wheel_axle{axle}_{side}_actual_deg"]
                       - dynamic.samples[f"wheel_axle{axle}_{side}_command_deg"])
                for axle in range(1, 7) for side in ("left", "right")])
            after = np.flatnonzero((times >= command_end) & (errors > 0.5))
            last_outside = float(times[after[-1]]) if after.size else command_end
            metrics["settling_delay_s"] = max(0.0, last_outside - command_end)
        grade, causes = grade_metrics(metrics, self.config,
                                      completed=dynamic.completed)
        summary = dynamic.summary
        row: dict[str, Any] = {
            "state_label": state_label,
            "scenario_source": source,
            "case_id": case.case_id,
            "case_category": case.category,
            "target_outer_angle_deg": case.target_outer_angle_deg,
            "speed_kmh": case.speed_kmh,
            "completed": dynamic.completed,
            "failure_reason": dynamic.failure_reason or "",
            "quality_grade": grade,
            "grade_causes": "|".join(causes),
            "hydraulic_state_count": self.runner.hydraulic.state_size,
            "hydraulic_model": self.runner.hydraulic_model,
            "mechanical_mode": self.runner.mechanical_mode,
            "target_path_adhesion_ratio": float(summary.get("target_path_adhesion_ratio", math.nan)),
            "adhesion_risk_excluded_from_grade": bool(
                float(summary.get("target_path_adhesion_ratio", 0.0)) > 1.0),
            "mechanism_ackermann_error_deg": float(
                summary.get("max_mechanism_ackermann_error_deg", math.nan)),
            **metrics,
        }
        return AssessmentResult(row=row, dynamic=dynamic)


def parameters_for_assessment(
        healthy: EngineeringHydraulicParameters,
        degradation_config: DegradationModelConfig,
        *, damage_state: DegradationState | None = None,
        parameters: EngineeringHydraulicParameters | None = None,
        ) -> EngineeringHydraulicParameters:
    """Accept either user-specified physical parameters or a damage state.

    The two paths are intentionally exclusive.  Both return an immutable
    in-memory parameter object suitable for direct injection into J0Runner.
    """
    if damage_state is not None and parameters is not None:
        raise ValueError("specify either damage_state or parameters, not both")
    if parameters is not None:
        return parameters
    return parameters_from_damage(
        healthy, damage_state or DegradationState.healthy(CHANNEL_ORDER),
        degradation_config)


def component_health_rows(state_label: str, source: str,
                          state: DegradationState,
                          config: QualityConfig) -> list[dict[str, Any]]:
    limits = config.raw["component_damage_thresholds"]
    rows: list[dict[str, Any]] = []
    for kind, items in (("pump", state.pumps), ("valve", state.valves),
                        ("cylinder", state.cylinders)):
        for name, component in items.items():
            damage = float(component.damage)
            if damage <= float(limits["healthy"]):
                grade = "HEALTHY"
            elif damage <= float(limits["subhealthy"]):
                grade = "SUBHEALTHY"
            elif damage <= float(limits["degraded"]):
                grade = "DEGRADED"
            else:
                grade = "DANGEROUS"
            rows.append({
                "state_label": state_label, "scenario_source": source,
                "component_type": kind, "component_id": name,
                "damage": damage, "component_health_grade": grade,
                "threshold_source": config.assumption_tag,
            })
    return rows
