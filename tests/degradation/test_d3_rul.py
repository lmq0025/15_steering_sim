from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import numpy as np

from steering_sim.degradation.damage import ComponentDamageState
from steering_sim.degradation.multimode import (
    D3Config, MODE_NAMES, MultiModeDegradationState, load_d3_config,
    mode_key, parameters_from_multimode)
from steering_sim.degradation.rainflow import count_rainflow, equivalent_cycle_load
from steering_sim.degradation.rul import (
    MissionCycleProfile, MissionSegmentExposure, RepeatedMissionRULPredictor)
from steering_sim.degradation.stochastic import (gamma_damage_increment,
                                                  monte_carlo_rul)
from steering_sim.hydraulics_engineering import (EngineeringHydraulicSystem,
                                                  load_parameters)
from steering_sim.hydraulics_lumped import HydraulicInput

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs" / "degradation" / "d3_rul_models.json"
HEALTHY_PATH = ROOT / "configs" / "j1r2" / "engineering_hydraulics.json"


def _synthetic_config(*, rate: float = 0.0, failure: float = 0.9) -> D3Config:
    source = load_d3_config(CONFIG_PATH)
    raw = deepcopy(source.raw)
    for kind, modes in MODE_NAMES.items():
        for name in modes:
            raw["modes"][kind][name]["rate"] = 0.0
            raw["modes"][kind][name]["state_factor_alpha"] = 0.0
            raw["modes"][kind][name]["failure_damage"] = 1.0
    raw["modes"]["pump"]["leakage_wear"]["rate"] = rate
    raw["modes"]["pump"]["leakage_wear"]["failure_damage"] = failure
    raw["mission"]["maximum_cycles"] = 10
    raw["mission"]["maximum_service_years"] = 10
    return D3Config(raw, source.model_version, source.assumption_tag)


def _profile(exposure: float = 1.0) -> MissionCycleProfile:
    state = MultiModeDegradationState.healthy()
    values = {key: 0.0 for key in state.modes}
    values[mode_key("pump", "front", "leakage_wear")] = exposure
    segment = MissionSegmentExposure("S1", 1, 5 * 86400.0, 5.0, values)
    return MissionCycleProfile((segment,), {}, {}, ())


def test_cycle_two_inherits_cycle_one_state():
    config = _synthetic_config(rate=0.1, failure=1.0)
    result = RepeatedMissionRULPredictor(config, lambda state, angle: _profile()).predict(
        maximum_cycles=2)
    key = mode_key("pump", "front", "leakage_wear")
    assert result.state_history[1].modes[key].damage == 0.1
    assert result.state_history[2].modes[key].damage == 0.2


def test_exact_first_failure_cycle_day_and_segment():
    config = _synthetic_config(rate=0.6, failure=0.9)
    result = RepeatedMissionRULPredictor(config, lambda state, angle: _profile()).predict()
    assert result.status == "FAILURE_REACHED"
    assert result.remaining_complete_cycles == 1
    assert result.first_failure_cycle == 2
    assert result.first_failure_day_in_cycle == 5.0
    assert result.first_failure_segment_id == "S1"


def test_no_failure_is_not_reported_as_horizon_life():
    result = RepeatedMissionRULPredictor(
        _synthetic_config(), lambda state, angle: _profile()).predict(maximum_cycles=3)
    assert result.status == "NOT_REACHED_WITHIN_HORIZON"
    assert result.remaining_complete_cycles is None
    assert result.first_failure_cycle is None


def test_sparse_real_quality_failure_returns_bracket_not_fake_precision():
    result = RepeatedMissionRULPredictor(
        _synthetic_config(), lambda state, angle: _profile()).predict(
            maximum_cycles=4,
            quality_evaluator=lambda state, cycle: {
                "rated_quality_grade": "DANGEROUS" if cycle >= 2 else "HEALTHY"})
    assert result.status == "FAILURE_BRACKETED"
    assert result.remaining_complete_cycles == 1
    assert result.first_failure_cycle == 2


def test_quality_solver_error_returns_indeterminate():
    def failed_quality(state, cycle):
        raise RuntimeError("synthetic solver failure")
    result = RepeatedMissionRULPredictor(
        _synthetic_config(), lambda state, angle: _profile()).predict(
            maximum_cycles=2, quality_evaluator=failed_quality)
    assert result.status == "INDETERMINATE"
    assert result.first_failure_cycle is None


def test_component_and_mode_independence():
    config = _synthetic_config(rate=0.1, failure=1.0)
    result = RepeatedMissionRULPredictor(
        config, lambda state, angle: _profile()).predict(maximum_cycles=1)
    assert result.final_state.modes[mode_key("pump", "front", "leakage_wear")].damage > 0
    assert result.final_state.modes[mode_key("pump", "rear", "leakage_wear")].damage == 0
    assert result.final_state.modes[mode_key("pump", "front", "mechanical_loss")].damage == 0


def test_known_rainflow_sequence_and_unsplit_boundary():
    cycles = count_rainflow([0.0, 1.0, 0.0, 1.0, 0.0])
    equivalent = equivalent_cycle_load(cycles, exponent=1.0, reference=1.0)
    assert equivalent["cycle_count"] == 2.0
    assert equivalent["equivalent_exposure"] == 2.0
    # Counting joined segments retains the two middle half cycles; resetting
    # each [0,1,0] piece would lose their shared boundary identity.
    assert sum(item.count for item in cycles) == 2.0


def test_gamma_increment_nonnegative_reproducible_and_mean():
    first = np.random.default_rng(42)
    second = np.random.default_rng(42)
    a = np.array([gamma_damage_increment(0.02, 0.001, first) for _ in range(5000)])
    b = np.array([gamma_damage_increment(0.02, 0.001, second) for _ in range(5000)])
    assert np.array_equal(a, b)
    assert np.all(a >= 0.0)
    assert abs(float(np.mean(a)) - 0.02) < 8.0e-4


def test_gamma_process_statistics_are_exposure_split_invariant():
    whole_rng = np.random.default_rng(7)
    split_rng = np.random.default_rng(8)
    whole = np.array([gamma_damage_increment(0.04, 0.001, whole_rng)
                      for _ in range(10000)])
    split = np.array([gamma_damage_increment(0.015, 0.001, split_rng)
                      + gamma_damage_increment(0.025, 0.001, split_rng)
                      for _ in range(10000)])
    assert abs(float(whole.mean() - split.mean())) < 5.0e-4
    assert abs(float(whole.var() - split.var())) < 5.0e-6


def test_monte_carlo_right_censoring_is_explicit():
    result = monte_carlo_rul(
        MultiModeDegradationState.healthy(), _profile(), _synthetic_config(),
        sample_count=8, random_seed=9, maximum_cycles=2)
    assert result.censored_count == 8
    assert result.censored_fraction == 1.0
    assert all(row["status"] == "RIGHT_CENSORED" for row in result.sample_rows)


def test_monte_carlo_can_be_stopped_by_state_based_quality_rule():
    key = mode_key("pump", "front", "leakage_wear")
    config = _synthetic_config(rate=0.1, failure=1.0)
    result = monte_carlo_rul(
        MultiModeDegradationState.healthy(), _profile(), config,
        sample_count=4, random_seed=3, maximum_cycles=5,
        system_failure=lambda state: (
            state.modes[key].damage >= 0.12, "calibrated quality boundary"))
    assert result.censored_count == 0
    assert all(row["limiting_factors"] == "system_quality_surrogate"
               for row in result.sample_rows)


def test_six_modes_reach_distinct_engineering_parameters_and_22_state_rhs():
    config = load_d3_config(CONFIG_PATH)
    healthy = load_parameters(HEALTHY_PATH)
    base = MultiModeDegradationState.healthy()
    base_parameters = parameters_from_multimode(healthy, base, config)
    base_system = EngineeringHydraulicSystem(base_parameters)
    assert base_system.state_size == 22
    vector = base_system.neutral_state()
    for index in range(4):
        vector[5 * index] = 12e6
        vector[5 * index + 1] = 3e6
        vector[5 * index + 3] = 0.02
        vector[5 * index + 4] = 0.2
    inputs = HydraulicInput((0.8,) * 4, (157.08,) * 4, (5000.0,) * 4)
    base_rhs, base_output = base_system.evaluate(0.0, vector, inputs)
    for kind, component, mode in (
            ("pump", "front", "leakage_wear"),
            ("pump", "front", "mechanical_loss"),
            ("valve", "channel_front", "leakage_wear"),
            ("valve", "channel_front", "response_lag"),
            ("cylinder", "channel_front", "leakage_wear"),
            ("cylinder", "channel_front", "friction_growth")):
        key = mode_key(kind, component, mode)
        state = base.with_mode(key, ComponentDamageState(0.8))
        system = EngineeringHydraulicSystem(parameters_from_multimode(healthy, state, config))
        rhs, output = system.evaluate(0.0, vector, inputs)
        assert (not np.array_equal(rhs, base_rhs)
                or output.pump_input_power_w != base_output.pump_input_power_w)


def test_pump_mechanical_loss_does_not_duplicate_volumetric_loss():
    config = load_d3_config(CONFIG_PATH)
    healthy = load_parameters(HEALTHY_PATH)
    base = MultiModeDegradationState.healthy()
    mechanical = base.with_mode(
        mode_key("pump", "front", "mechanical_loss"), ComponentDamageState(0.8))
    leakage = base.with_mode(
        mode_key("pump", "front", "leakage_wear"), ComponentDamageState(0.8))
    mechanical_wear = parameters_from_multimode(healthy, mechanical, config).degradation.pump("front")
    leakage_wear = parameters_from_multimode(healthy, leakage, config).degradation.pump("front")
    assert mechanical_wear.internal_leakage_m3_s_per_pa == 0.0
    assert mechanical_wear.mechanical_efficiency < 1.0
    assert leakage_wear.mechanical_efficiency == 1.0
    assert leakage_wear.internal_leakage_m3_s_per_pa > 0.0


def test_healthy_parameter_file_is_not_modified():
    before = HEALTHY_PATH.read_bytes()
    config = load_d3_config(CONFIG_PATH)
    healthy = load_parameters(HEALTHY_PATH)
    parameters_from_multimode(healthy, MultiModeDegradationState.healthy(), config)
    assert HEALTHY_PATH.read_bytes() == before


def test_d3_zero_modes_preserve_healthy_rhs_exactly():
    config = load_d3_config(CONFIG_PATH)
    healthy = load_parameters(HEALTHY_PATH)
    mapped = parameters_from_multimode(
        healthy, MultiModeDegradationState.healthy(), config)
    original_system = EngineeringHydraulicSystem(healthy)
    mapped_system = EngineeringHydraulicSystem(mapped)
    state = original_system.neutral_state()
    inputs = HydraulicInput((0.3,) * 4, (157.08,) * 4, (5000.0,) * 4)
    original_rhs, original_output = original_system.evaluate(0.0, state, inputs)
    mapped_rhs, mapped_output = mapped_system.evaluate(0.0, state, inputs)
    assert np.array_equal(original_rhs, mapped_rhs)
    assert original_output.pump_flow_m3_s == mapped_output.pump_flow_m3_s
