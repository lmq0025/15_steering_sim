from __future__ import annotations

from pathlib import Path

import pytest

from scripts.d2.run_phase_d2 import D1_CONFIG, D2_CONFIG, HEALTHY, build_runner
from steering_sim.degradation import ComponentDamageState, DegradationState
from steering_sim.degradation.damage import load_degradation_config
from steering_sim.hydraulics_engineering import load_parameters
from steering_sim.j0_coupling.config import CHANNEL_ORDER
from steering_sim.quality_assessment import (
    AssessmentCase, QualityAssessor, component_health_rows, grade_metrics,
    load_quality_config, parameters_for_assessment)
from steering_sim.quality_assessment.assessment import reversal_profile


def test_thresholds_are_central_and_marked_as_assumptions():
    config = load_quality_config(D2_CONFIG)
    assert config.assumption_tag == "ENGINEERING_DESIGN_ASSUMPTION"
    assert "max_tracking_error_deg" in config.thresholds


def test_explainable_four_level_grading_and_adhesion_is_not_a_metric():
    config = load_quality_config(D2_CONFIG)
    healthy = {
        name: (float(item["healthy"]) - 1e-9
               if item["direction"] == "max"
               else float(item["healthy"]) + 1e-9)
        for name, item in config.thresholds.items()}
    grade, causes = grade_metrics(healthy, config, completed=True)
    assert grade == "HEALTHY" and not causes
    dangerous = dict(healthy)
    dangerous["max_tracking_error_deg"] = 100.0
    grade, causes = grade_metrics(dangerous, config, completed=True)
    assert grade == "DANGEROUS"
    assert any("max_tracking_error_deg" in cause for cause in causes)
    assert "adhesion" not in " ".join(config.thresholds)


def test_direct_parameters_and_damage_state_are_supported_exclusively():
    healthy = load_parameters(HEALTHY)
    degradation = load_degradation_config(D1_CONFIG)
    state = DegradationState.healthy(CHANNEL_ORDER)
    assert parameters_for_assessment(
        healthy, degradation, parameters=healthy) is healthy
    mapped = parameters_for_assessment(
        healthy, degradation, damage_state=state)
    assert mapped.degradation.pump("front").internal_leakage_m3_s_per_pa == 0.0
    assert mapped.degradation.valve("channel_front").internal_leakage_m3_s_per_pa == 0.0
    with pytest.raises(ValueError, match="either"):
        parameters_for_assessment(
            healthy, degradation, damage_state=state, parameters=healthy)


def test_component_health_is_independent():
    config = load_quality_config(D2_CONFIG)
    state = DegradationState.healthy(CHANNEL_ORDER)
    valves = dict(state.valves)
    valves["channel_rear_1"] = ComponentDamageState(0.55)
    state = DegradationState(pumps=state.pumps, valves=valves,
                             cylinders=state.cylinders)
    rows = component_health_rows("test", "DIRECT", state, config)
    by_id = {(row["component_type"], row["component_id"]): row for row in rows}
    assert by_id[("valve", "channel_rear_1")]["component_health_grade"] == "DEGRADED"
    assert by_id[("valve", "channel_front")]["component_health_grade"] == "HEALTHY"
    assert by_id[("pump", "front")]["component_health_grade"] == "HEALTHY"


def test_reversal_profile_has_no_command_discontinuity():
    profile = reversal_profile()
    epsilon = 1.0e-7
    for boundary in (1.0, 1.9, 2.9, 3.8, 4.8):
        before = profile(boundary - epsilon)[0]
        after = profile(boundary + epsilon)[0]
        assert abs(after - before) < 1.0e-5


def test_specified_degradation_runs_real_22_state_dynamics():
    quality = load_quality_config(D2_CONFIG)
    degradation = load_degradation_config(D1_CONFIG)
    healthy_parameters = load_parameters(HEALTHY)
    healthy_state = DegradationState.healthy(CHANNEL_ORDER)
    pumps = dict(healthy_state.pumps)
    pumps["front"] = ComponentDamageState(0.90)
    worn_state = DegradationState(pumps=pumps, valves=healthy_state.valves,
                                  cylinders=healthy_state.cylinders)
    case = AssessmentCase("TEST_REAL_DYNAMICS", 10.0, 5.0, 1.25,
                          0.8333333333)
    rows = []
    for label, state in (("healthy", healthy_state), ("worn", worn_state)):
        parameters = parameters_for_assessment(
            healthy_parameters, degradation, damage_state=state)
        assessor = QualityAssessor(build_runner(parameters, accelerated=True), quality)
        assessed = assessor.run(label, "TEST", case)
        assert assessed.dynamic.completed
        assert assessed.row["hydraulic_state_count"] == 22
        rows.append(assessed.row)
    assert rows[1]["minimum_pump_flow_margin_lpm"] < rows[0]["minimum_pump_flow_margin_lpm"]
    assert rows[1]["pump_demand_ratio"] > rows[0]["pump_demand_ratio"]
    assert rows[1]["max_tracking_error_deg"] != pytest.approx(
        rows[0]["max_tracking_error_deg"], abs=1e-8)
