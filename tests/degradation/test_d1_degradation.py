from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from steering_sim.degradation.damage import (ComponentDamageState,
                                              DegradationState,
                                              load_degradation_config)
from steering_sim.degradation.prediction import D1Predictor, parameters_from_damage
from steering_sim.degradation.spectrum import SpectrumError, load_task_spectrum
from steering_sim.degradation.spectrum import TaskSegment, TaskSpectrum
from steering_sim.demo import degradation as compatibility
from steering_sim.hydraulics_engineering import (
    CylinderDegradationParameters, DegradationParameters,
    EngineeringHydraulicSystem, PumpDegradationParameters,
    ValveDegradationParameters, load_parameters, with_component_degradation)
from steering_sim.hydraulics_lumped import HydraulicInput

from scripts.d1.run_phase_d1 import CHANNELS, CONFIG, HEALTHY, build_runner, make_spectra


def test_demo_uses_the_unique_formal_parameter_class():
    assert compatibility.DegradationParameters is DegradationParameters
    assert "hydraulics_lumped" not in " ".join(compatibility.INTERFACE_MAP.values())


def test_component_injection_is_independent_and_healthy_is_immutable():
    healthy = load_parameters(HEALTHY)
    worn = with_component_degradation(
        healthy,
        pumps={"front": PumpDegradationParameters(
            internal_leakage_m3_s_per_pa=1e-12)},
        valves={"channel_rear_1": ValveDegradationParameters(
            internal_leakage_m3_s_per_pa=2e-12)},
        cylinders={"channel_rear_2": CylinderDegradationParameters(
            internal_leakage_m3_s_per_pa=3e-12)})
    assert healthy.degradation.is_new_unit
    assert worn.degradation.pump("front").internal_leakage_m3_s_per_pa == 1e-12
    assert worn.degradation.pump("rear").internal_leakage_m3_s_per_pa == 0.0
    assert worn.degradation.valve("channel_rear_1").internal_leakage_m3_s_per_pa == 2e-12
    assert worn.degradation.valve("channel_front").internal_leakage_m3_s_per_pa == 0.0
    assert worn.degradation.cylinder("channel_rear_2").internal_leakage_m3_s_per_pa == 3e-12


def test_pump_leakage_equilibrium_initialises_without_false_transient():
    healthy = load_parameters(HEALTHY)
    worn = with_component_degradation(
        healthy, pumps={"front": PumpDegradationParameters(
            internal_leakage_m3_s_per_pa=2e-12),
                        "rear": PumpDegradationParameters()})
    system = EngineeringHydraulicSystem(worn)
    state = system.neutral_state()
    derivative, _ = system.evaluate(0.0, state, HydraulicInput(
        (0.0,) * 4, (157.08,) * 4, (0.0,) * 4))
    assert abs(derivative[20]) < 1.0
    assert abs(derivative[21]) < 1.0


def test_valve_and_cylinder_leaks_enter_different_conservation_equations():
    healthy = load_parameters(HEALTHY)
    worn = with_component_degradation(
        healthy,
        valves={"channel_rear_1": ValveDegradationParameters(
            internal_leakage_m3_s_per_pa=2e-12)},
        cylinders={"channel_rear_2": CylinderDegradationParameters(
            internal_leakage_m3_s_per_pa=2e-12)})
    system = EngineeringHydraulicSystem(worn)
    state = system.neutral_state()
    state[10], state[11] = 12e6, 3e6
    _, output = system.evaluate(0.0, state, HydraulicInput(
        (0.0,) * 4, (157.08,) * 4, (0.0,) * 4))
    assert output.channels[1].valve_leakage_flow_m3_s > 0.0
    assert output.channels[1].cylinder_leakage_flow_m3_s == 0.0
    assert output.channels[2].valve_leakage_flow_m3_s == 0.0
    assert output.channels[2].cylinder_leakage_flow_m3_s > 0.0


def test_zero_exposure_is_zero_damage_and_split_is_invariant():
    state = ComponentDamageState()
    unchanged, increment = state.advanced(rate=0.2, equivalent_exposure=0.0,
                                          state_factor_alpha=0.4,
                                          maximum_damage=1.0)
    assert increment == 0.0 and unchanged.damage == 0.0
    whole, _ = state.advanced(rate=0.02, equivalent_exposure=10.0,
                              state_factor_alpha=0.4, maximum_damage=1.0)
    half, _ = state.advanced(rate=0.02, equivalent_exposure=4.0,
                             state_factor_alpha=0.4, maximum_damage=1.0)
    split, _ = half.advanced(rate=0.02, equivalent_exposure=6.0,
                             state_factor_alpha=0.4, maximum_damage=1.0)
    assert split.damage == pytest.approx(whole.damage, rel=1e-13, abs=1e-15)


def test_short_spectrum_is_not_mislabeled_as_30_days():
    row = {"segment_id": "short", "speed_kmh": 0,
           "target_outer_angle_deg": 0, "segment_duration_s": 10,
           "friction_coefficient": 0.8, "pump_running": False}
    row.update({f"axle_mass_{i}_t": 11.5 for i in range(1, 7)})
    path = Path("outputs/degradation/phase_D1/test_short_spectrum.csv")
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([row]).to_csv(path, index=False)
    with pytest.raises(SpectrumError, match="不会自动补足"):
        load_task_spectrum(path, expected_days=30)


@pytest.fixture(scope="module")
def prediction():
    example, _ = make_spectra()
    spectrum = load_task_spectrum(example, expected_days=30)
    model = load_degradation_config(CONFIG)
    return D1Predictor(build_runner(), model).predict(spectrum), model


def test_mission_drivers_are_not_confused(prediction):
    result, _ = prediction
    parked = result.segment_records[0]
    assert parked["damage_increment_pump_front"] == 0.0
    assert all(parked[f"{name}_sliding_distance_m"] == 0.0 for name in CHANNELS)
    running_straight = result.segment_records[1]
    assert running_straight["damage_increment_pump_front"] > 0.0
    hold = next(row for row in result.segment_records if "大角保持" in row["segment_id"])
    assert all(hold[f"{name}_sliding_distance_m"] == 0.0 for name in CHANNELS)
    assert all(hold[f"{name}_valve_cycles"] == 0.0 for name in CHANNELS)


def test_prediction_is_finite_nonnegative_and_parameters_physical(prediction):
    result, _ = prediction
    frame = pd.DataFrame(result.segment_records)
    numeric = frame.select_dtypes(include=[np.number]).to_numpy()
    assert np.all(np.isfinite(numeric))
    damage = frame.filter(regex="^(damage_increment|cumulative_damage)")
    assert (damage.to_numpy() >= 0.0).all()
    for supply in ("front", "rear"):
        wear = result.final_parameters.degradation.pump(supply)
        assert wear.internal_leakage_m3_s_per_pa >= 0.0
    assert result.runtime_s < 60.0


def test_prediction_is_deterministic(prediction):
    first, model = prediction
    example, _ = make_spectra()
    second = D1Predictor(build_runner(), model).predict(
        load_task_spectrum(example, expected_days=30))
    assert second.curve_records[-1] == first.curve_records[-1]


def test_damage_maps_to_real_22_state_dynamics(prediction):
    result, _ = prediction
    healthy = EngineeringHydraulicSystem(load_parameters(HEALTHY))
    worn = EngineeringHydraulicSystem(result.final_parameters)
    state = healthy.neutral_state()
    for index in range(4):
        state[5 * index], state[5 * index + 1], state[5 * index + 4] = 12e6, 3e6, 0.3
    inputs = HydraulicInput((0.3,) * 4, (157.08,) * 4, (5000.0,) * 4)
    dh, oh = healthy.evaluate(0.0, state.copy(), inputs)
    dw, ow = worn.evaluate(0.0, state.copy(), inputs)
    assert healthy.state_size == worn.state_size == 22
    assert not np.array_equal(dh, dw)
    assert ow.pump_flow_m3_s[0] < oh.pump_flow_m3_s[0]
    assert ow.channels[0].valve_leakage_flow_m3_s > 0.0
    assert ow.channels[0].cylinder_leakage_flow_m3_s > 0.0


def test_health_file_stays_read_only_during_mapping(prediction):
    before = hashlib.sha256(HEALTHY.read_bytes()).hexdigest()
    result, model = prediction
    _ = parameters_from_damage(load_parameters(HEALTHY), result.final_state, model)
    after = hashlib.sha256(HEALTHY.read_bytes()).hexdigest()
    assert before == after


def _one_segment_spectrum(angle: float) -> TaskSpectrum:
    segment = TaskSegment(
        segment_id=f"load_{angle:g}", speed_kmh=5.0,
        target_outer_angle_deg=angle, segment_duration_s=60.0,
        friction_coefficient=0.8, axle_mass_t=(11.5,) * 6,
        pump_running=True, repeats=1, contamination_severity=1.0,
        oil_temperature_c=40.0)
    return TaskSpectrum((segment,), source=Path("synthetic.csv"))


def test_pump_exposure_responds_to_load_at_equal_runtime():
    model = load_degradation_config(CONFIG)
    straight = D1Predictor(build_runner(), model).predict(
        _one_segment_spectrum(0.0)).segment_records[0]
    loaded = D1Predictor(build_runner(), model).predict(
        _one_segment_spectrum(30.0)).segment_records[0]
    assert loaded["pump_front_load_pressure_pa"] > straight["pump_front_load_pressure_pa"]
    assert (loaded["equivalent_exposure_pump_front"]
            > straight["equivalent_exposure_pump_front"])


def test_wear_refresh_changes_supply_features_for_same_condition():
    model = load_degradation_config(CONFIG)
    healthy_state = DegradationState.healthy(CHANNELS)
    pumps = dict(healthy_state.pumps)
    pumps["front"] = ComponentDamageState(damage=0.8)
    worn_state = replace(healthy_state, pumps=pumps)
    healthy_record = D1Predictor(build_runner(), model).predict(
        _one_segment_spectrum(10.0), healthy_state).segment_records[0]
    worn_record = D1Predictor(build_runner(), model).predict(
        _one_segment_spectrum(10.0), worn_state).segment_records[0]
    assert (worn_record["pump_front_available_pump_flow_m3_s"]
            < healthy_record["pump_front_available_pump_flow_m3_s"])
    assert (worn_record["pump_front_pump_demand_ratio"]
            > healthy_record["pump_front_pump_demand_ratio"])
