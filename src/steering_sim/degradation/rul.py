"""Fast repeated-mission RUL advancement with traceable first-failure rules."""
from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Any, Callable, Mapping, Sequence

from steering_sim.j0_coupling.config import CHANNEL_ORDER

from .damage import ComponentDamageState
from .multimode import (D3Config, MODE_NAMES, PUMP_IDS,
                        MultiModeDegradationState, mode_key)
from .rainflow import RainflowCycle, count_rainflow, equivalent_cycle_load


@dataclass(frozen=True, slots=True)
class MissionSegmentExposure:
    segment_id: str
    repeat_index: int
    elapsed_s: float
    elapsed_day: float
    exposures: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class MissionCycleProfile:
    segments: tuple[MissionSegmentExposure, ...]
    rainflow_cycles: Mapping[str, tuple[RainflowCycle, ...]]
    rainflow_equivalents: Mapping[str, Mapping[str, float]]
    source_records: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True, slots=True)
class FailureEvent:
    cycle: int
    day_in_cycle: float
    segment_id: str
    limiting_factors: tuple[str, ...]
    reasons: tuple[str, ...]
    source: str


@dataclass(frozen=True, slots=True)
class RULPrediction:
    status: str
    remaining_complete_cycles: int | None
    first_failure_cycle: int | None
    first_failure_day_in_cycle: float | None
    first_failure_segment_id: str | None
    remaining_time_days: float | None
    limiting_factors: tuple[str, ...]
    failure_reasons: tuple[str, ...]
    termination_basis: str
    final_state: MultiModeDegradationState
    cycle_history: tuple[Mapping[str, Any], ...]
    state_history: tuple[MultiModeDegradationState, ...]
    quality_history: tuple[Mapping[str, Any], ...]
    runtime_s: float


def build_cycle_profile(records: Sequence[Mapping[str, Any]], config: D3Config
                        ) -> MissionCycleProfile:
    """Build ordered mode exposures; rainflow is counted over the joined sequence."""
    if not records:
        raise ValueError("mission profile has no segment records")
    friction_cfg = config.mode("cylinder", "friction_growth")
    rainflow_by_channel: dict[str, tuple[RainflowCycle, ...]] = {}
    equivalents: dict[str, Mapping[str, float]] = {}
    rainflow_by_end: dict[str, dict[int, float]] = {}
    for name in CHANNEL_ORDER:
        # Initial zero is a real pre-mission boundary.  Segment loads are not
        # counted separately, so residual half cycles naturally span boundaries.
        values = [0.0] + [float(row[f"{name}_signed_load_force_n"])
                          for row in records]
        cycles = count_rainflow(values)
        rainflow_by_channel[name] = cycles
        equivalent = equivalent_cycle_load(
            cycles, exponent=float(friction_cfg["rainflow_exponent"]),
            reference=float(friction_cfg["rainflow_reference_range_n"]))
        equivalents[name] = equivalent
        allocation: dict[int, float] = {}
        for cycle in cycles:
            # values index 1 corresponds to records index 0.
            target = min(len(records) - 1, max(0, cycle.end_index - 1))
            dose = (cycle.count
                    * (cycle.range_value
                       / float(friction_cfg["rainflow_reference_range_n"]))
                    ** float(friction_cfg["rainflow_exponent"])
                    * float(friction_cfg["rainflow_weight"]))
            allocation[target] = allocation.get(target, 0.0) + dose
        rainflow_by_end[name] = allocation

    segments: list[MissionSegmentExposure] = []
    for index, row in enumerate(records):
        exposures: dict[str, float] = {}
        for supply in PUMP_IDS:
            base = float(row[f"equivalent_exposure_pump_{supply}"])
            demand = min(3.0, max(0.0, float(
                row.get(f"pump_{supply}_pump_demand_ratio", 0.0))))
            exposures[mode_key("pump", supply, "leakage_wear")] = base
            exposures[mode_key("pump", supply, "mechanical_loss")] = (
                base * (1.0 + 0.35 * demand))
        for name in CHANNEL_ORDER:
            valve = float(row[f"equivalent_exposure_valve_{name}"])
            cylinder = float(row[f"equivalent_exposure_cylinder_{name}"])
            cycles = float(row[f"{name}_valve_cycles"])
            exposures[mode_key("valve", name, "leakage_wear")] = valve
            exposures[mode_key("valve", name, "response_lag")] = (
                0.65 * valve + 0.35 * cycles)
            exposures[mode_key("cylinder", name, "leakage_wear")] = cylinder
            # Sliding/load abrasion and force-reversal fatigue are separate
            # additive mechanisms inside the friction mode.  Rainflow is not
            # also added to leakage wear, avoiding double counting.
            exposures[mode_key("cylinder", name, "friction_growth")] = (
                0.60 * cylinder + rainflow_by_end[name].get(index, 0.0))
        segments.append(MissionSegmentExposure(
            segment_id=str(row["segment_id"]),
            repeat_index=int(row.get("repeat_index", 1)),
            elapsed_s=float(row["elapsed_s"]),
            elapsed_day=float(row["elapsed_day"]), exposures=exposures))
    return MissionCycleProfile(tuple(segments), rainflow_by_channel,
                               equivalents, tuple(records))


def advance_mode(item: ComponentDamageState, exposure: float,
                 mode_config: Mapping[str, Any]) -> tuple[ComponentDamageState, float]:
    return item.advanced(
        rate=float(mode_config["rate"]), equivalent_exposure=exposure,
        state_factor_alpha=float(mode_config["state_factor_alpha"]),
        maximum_damage=float(mode_config["maximum_damage"]))


def advance_segment(state: MultiModeDegradationState,
                    segment: MissionSegmentExposure, config: D3Config
                    ) -> tuple[MultiModeDegradationState, dict[str, float]]:
    updated = dict(state.modes)
    increments: dict[str, float] = {}
    for key, exposure in segment.exposures.items():
        kind, _, mode = key.split(":")
        updated[key], increments[key] = advance_mode(
            updated[key], float(exposure), config.mode(kind, mode))
    return MultiModeDegradationState(updated), increments


def hard_failure_factors(state: MultiModeDegradationState,
                         config: D3Config) -> tuple[tuple[str, ...], tuple[str, ...]]:
    factors: list[str] = []
    reasons: list[str] = []
    for key, item in state.modes.items():
        kind, component_id, mode = key.split(":")
        threshold = float(config.mode(kind, mode)["failure_damage"])
        if item.damage + 1.0e-15 >= threshold:
            factors.append(f"{kind}:{component_id}")
            reasons.append(f"{key} damage {item.damage:.6g} >= hard limit {threshold:.6g}")
    return tuple(factors), tuple(reasons)


ProfileFactory = Callable[[MultiModeDegradationState, float], MissionCycleProfile]
QualityEvaluator = Callable[[MultiModeDegradationState, int], Mapping[str, Any]]


class RepeatedMissionRULPredictor:
    def __init__(self, config: D3Config, profile_factory: ProfileFactory) -> None:
        self.config = config
        self.profile_factory = profile_factory

    def predict(self, initial_state: MultiModeDegradationState | None = None,
                *, quality_evaluator: QualityEvaluator | None = None,
                mission_days: float = 30.0,
                maximum_cycles: int | None = None) -> RULPrediction:
        started = time.perf_counter()
        state = initial_state or MultiModeDegradationState.healthy()
        mission_cfg = self.config.raw["mission"]
        cycle_limit = int(maximum_cycles or mission_cfg["maximum_cycles"])
        years_limit = int(math.floor(
            float(mission_cfg["maximum_service_years"]) * 365.25 / mission_days))
        cycle_limit = max(1, min(cycle_limit, years_limit))
        refresh_interval = float(mission_cfg["refresh_damage_interval"])
        refresh_bucket = -1
        profile: MissionCycleProfile | None = None
        initial_angle = 0.0
        history: list[Mapping[str, Any]] = []
        states: list[MultiModeDegradationState] = [state]
        component_event: FailureEvent | None = None

        for cycle in range(1, cycle_limit + 1):
            bucket = int(state.max_damage / refresh_interval)
            if profile is None or bucket != refresh_bucket:
                profile = self.profile_factory(state, initial_angle)
                refresh_bucket = bucket
            cycle_start = state
            total_increments = {key: 0.0 for key in state.modes}
            for segment in profile.segments:
                state, increments = advance_segment(state, segment, self.config)
                for key, value in increments.items():
                    total_increments[key] += value
                factors, reasons = hard_failure_factors(state, self.config)
                if factors:
                    component_event = FailureEvent(
                        cycle=cycle, day_in_cycle=segment.elapsed_day,
                        segment_id=segment.segment_id,
                        limiting_factors=tuple(dict.fromkeys(factors)),
                        reasons=reasons, source="COMPONENT_HARD_LIMIT")
                    break
            end_row: dict[str, Any] = {
                "mission_cycle": cycle,
                "mission_days_elapsed": (cycle - 1) * mission_days
                                        + (component_event.day_in_cycle
                                           if component_event else mission_days),
                "cycle_completed": component_event is None,
                "maximum_damage": state.max_damage,
                **state.flat_damage(),
            }
            for key, value in total_increments.items():
                end_row[f"increment_{key.replace(':', '_')}"] = value
            history.append(end_row)
            states.append(state)
            if component_event:
                break
            # Repeated mission boundary inherits the last target angle.  The
            # profile factory can use it when a spectrum does not end at zero.
            if profile.source_records:
                next_angle = float(profile.source_records[-1]["target_outer_angle_deg"])
                if abs(next_angle - initial_angle) > 1.0e-12:
                    initial_angle = next_angle
                    profile = None

        quality_rows: list[Mapping[str, Any]] = []
        system_upper: int | None = None
        system_lower = 0
        quality_error: str | None = None
        if quality_evaluator is not None:
            last_cycle = len(states) - 1
            maximum_checks = max(2, int(mission_cfg["maximum_dynamic_checkpoints"]))
            if last_cycle > 0:
                candidates = sorted(set(
                    [0, last_cycle]
                    + [int(round(last_cycle * fraction))
                       for fraction in (0.25, 0.5, 0.75)]))
                candidates = candidates[:maximum_checks]
                for cycle in candidates:
                    try:
                        row = dict(quality_evaluator(states[cycle], cycle))
                    except Exception as exc:  # preserve a reportable terminal state
                        quality_error = f"{type(exc).__name__}: {exc}"
                        break
                    row["mission_cycle"] = cycle
                    quality_rows.append(row)
                    if str(row.get("rated_quality_grade")) == str(
                            mission_cfg["system_failure_grade"]):
                        system_upper = cycle
                        break
                    system_lower = cycle

        event = component_event
        status: str
        basis: str
        if quality_error is not None:
            status = "INDETERMINATE"
            basis = f"22-state quality verification failed: {quality_error}"
            complete = None
            event = None
        elif system_upper is not None and (event is None or system_upper < event.cycle):
            # Sparse authoritative checks prove an interval, not a fictitious
            # exact crossing.  No monotonicity/binary-search assumption is used.
            status = "FAILURE_BRACKETED"
            event = FailureEvent(
                cycle=system_upper, day_in_cycle=mission_days,
                segment_id="DYNAMIC_CHECKPOINT",
                limiting_factors=("system_quality",),
                reasons=(f"rated D2 quality reached {mission_cfg['system_failure_grade']} "
                         f"between verified cycles {system_lower} and {system_upper}",),
                source="D2_22_STATE_QUALITY")
            basis = f"authoritative 22-state quality bracket ({system_lower}, {system_upper}]"
            complete = system_lower
        elif event is not None:
            status = "FAILURE_REACHED"
            basis = "configured component hard failure threshold"
            complete = event.cycle - 1
        else:
            status = "NOT_REACHED_WITHIN_HORIZON"
            basis = (f"no configured component/system failure within {cycle_limit} "
                     "calculated mission cycles")
            complete = None

        return RULPrediction(
            status=status, remaining_complete_cycles=complete,
            first_failure_cycle=event.cycle if event else None,
            first_failure_day_in_cycle=event.day_in_cycle if event else None,
            first_failure_segment_id=event.segment_id if event else None,
            remaining_time_days=((event.cycle - 1) * mission_days
                                 + event.day_in_cycle if event else None),
            limiting_factors=event.limiting_factors if event else (),
            failure_reasons=event.reasons if event else (),
            termination_basis=basis, final_state=state,
            cycle_history=tuple(history), state_history=tuple(states),
            quality_history=tuple(quality_rows),
            runtime_s=time.perf_counter() - started)
