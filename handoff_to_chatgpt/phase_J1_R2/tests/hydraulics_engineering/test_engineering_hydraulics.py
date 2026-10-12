"""PHASE J1-R2：工程电液伺服模型（``ENGINEERING_HYDRAULIC_V1``）的单元与集成检查。

覆盖任务书第三节的硬性要求：状态由微分方程积分产生、符号与压力连续、行程限制、
共用供油总量约束、退化接口、命令极性实测校验。
"""
from __future__ import annotations

from dataclasses import replace
import json
import math
from pathlib import Path

import numpy as np
import pytest

from steering_sim.hydraulics_engineering.model import CHANNEL_STATE_SIZE

ROOT = Path(__file__).parents[2]
PARAMETERS = ROOT / "configs" / "j1r2" / "engineering_hydraulics.json"
SPEC = ROOT / "mechanical_model_input_spec_v1.0.yaml"
ENG_CONFIG = ROOT / "configs" / "j1" / "engineering_config.json"
ENG_DESIGN = ROOT / "configs" / "j1" / "engineering_mechanism.json"
J0_CONFIG = ROOT / "configs" / "j0" / "j0_config.json"


@pytest.fixture(scope="module")
def parameters():
    from steering_sim.hydraulics_engineering import load_parameters
    return load_parameters(PARAMETERS)


@pytest.fixture(scope="module")
def system(parameters):
    from steering_sim.hydraulics_engineering import EngineeringHydraulicSystem
    return EngineeringHydraulicSystem(parameters)


class _Inputs:
    """与 ``hydraulics_lumped.HydraulicInput`` 鸭子类型一致的最小输入。"""

    def __init__(self, commands, loads=None):
        self.valve_commands = tuple(commands)
        self.external_load_forces_n = tuple(loads or (0.0,) * len(commands))


# ------------------------------------------------------------------ 参数
def test_parameters_are_loaded_and_tagged(parameters):
    assert parameters.tag == "ENGINEERING_HYDRAULIC_V1"
    assert parameters.schema_version == "J1R2.0"
    assert parameters.degradation.is_new_unit
    assert len(parameters.channels) == 4
    assert parameters.supply_names == ("front", "rear")
    for channel in parameters.channels:
        assert channel.cylinder.symmetric, channel.name
        assert channel.polarity == 1.0


def test_parameters_reject_a_zero_valve_lag(parameters):
    """理想阀（时间常数 0）会让流量阶跃激励未建模高频模态，必须被拒绝。"""
    from steering_sim.hydraulics_engineering import ParameterError, ValveParameters
    with pytest.raises(ParameterError):
        ValveParameters(maximum_area_m2=1.0e-6, lag_time_s=0.0)


def test_parameters_reject_unknown_degradation_keys():
    from steering_sim.hydraulics_engineering import parameters_from_dict, ParameterError
    raw = json.loads(PARAMETERS.read_text(encoding="utf-8"))
    raw["degradation"] = {"not_a_real_knob": 1.0}
    with pytest.raises(ParameterError):
        parameters_from_dict(raw)


# ------------------------------------------------------------- 状态与初值
def test_state_layout_is_five_states_per_channel_plus_supplies(system):
    assert system.state_size == CHANNEL_STATE_SIZE * 4 + 2
    state = system.neutral_state()
    assert state.shape == (system.state_size,)
    assert np.allclose(state[:CHANNEL_STATE_SIZE * 4:CHANNEL_STATE_SIZE],
                       system.parameters.precharge_pressure_pa)


def test_neutral_state_is_a_true_equilibrium(system):
    """零位两腔预充压相等：零命令下状态导数必须为零，不需要任何"初始化装置"。"""
    state = system.neutral_state()
    derivative, outputs = system.evaluate(0.0, state, _Inputs((0.0, 0.0, 0.0, 0.0)))
    assert np.allclose(derivative, 0.0, atol=1.0e-6), derivative
    for channel in outputs.channels:
        assert abs(channel.velocity_m_s) < 1.0e-12
        assert abs(channel.hydraulic_force_n) < 1.0e-6


# ------------------------------------------------------------------ 符号
@pytest.mark.parametrize("index", [0, 1, 2, 3])
def test_positive_command_moves_the_piston_positive(system, index):
    commands = [0.0] * 4
    commands[index] = 0.5
    state = system.neutral_state()
    for _ in range(200):
        derivative, _out = system.evaluate(0.0, state, _Inputs(commands))
        state = state + 2.0e-4 * derivative
    assert state[CHANNEL_STATE_SIZE * index + 3] > 0.0
    assert state[CHANNEL_STATE_SIZE * index + 2] > 0.0


def test_command_polarity_probe_matches_the_physics(system):
    from steering_sim.hydraulics_engineering import probe_engineering_authority
    authorities = probe_engineering_authority(system, force_samples=5,
                                              settle_duration_s=0.15)
    assert len(authorities) == 4
    for authority in authorities:
        assert authority.command_polarity == 1
        assert authority.bidirectional
        assert authority.balanced_force_window, authority.channel
        low, high = authority.force_window_n
        assert high > 5.0e4 and low < -5.0e4, (authority.channel, low, high)


def test_the_static_force_window_covers_the_design_load(system):
    """执行器静态力窗口必须覆盖最不利工况的需求推力（第二关选型）。"""
    sizing = json.loads((ROOT / "outputs" / "j1r2"
                         / "hydraulic_sizing.json").read_text(encoding="utf-8"))
    from steering_sim.hydraulics_engineering import probe_engineering_authority
    authorities = {item.channel: item for item in
                   probe_engineering_authority(system, force_samples=5,
                                               settle_duration_s=0.15)}
    for name, item in sizing["groups"].items():
        window = authorities[name].force_window_n
        available = min(abs(window[0]), abs(window[1]))
        assert available >= item["required_force_n"], (name, available)


# --------------------------------------------------------- 行程与限位
def test_chamber_volumes_stay_positive_and_the_end_stop_limits_travel(system):
    """把命令打到极限：行程被机械限位挡住，且腔容积始终为正。"""
    channel = system.parameters.channels[0]
    commands = [1.0, 0.0, 0.0, 0.0]
    state = system.neutral_state()
    peak_utilisation = 0.0
    for _ in range(12000):
        derivative, outputs = system.evaluate(0.0, state, _Inputs(commands))
        state = state + 2.0e-4 * derivative
        peak_utilisation = max(peak_utilisation, outputs.channels[0].stroke_utilisation)
    offset = channel.cylinder.stroke_offset_m
    half = channel.cylinder.half_stroke_m
    displacement = state[CHANNEL_STATE_SIZE * 0 + 2] - offset
    assert displacement <= half + 2.0e-3, displacement
    assert displacement > 0.9 * half, displacement
    assert peak_utilisation > 0.9


def test_the_cylinder_travel_agrees_with_the_mechanism_envelope(parameters):
    """缸的机械限位必须与机构包络端点重合：不允许出现"表里查不到、缸还能走"的空档。"""
    import sys
    sys.path.insert(0, str(ROOT / "src"))
    from steering_sim.engineering.model import EngineeringSteeringModel
    from steering_sim.j0_coupling.config import load_j0_config
    from steering_sim.j0_coupling.geometry import J0GeometryAdapter
    model = EngineeringSteeringModel(SPEC, ENG_CONFIG, ENG_DESIGN)
    adapter = J0GeometryAdapter(model, load_j0_config(J0_CONFIG),
                                mechanical_mode="ENGINEERING_STEERING_MODEL")
    dof_of = {"channel_front": "q_front", "channel_rear_1": "q4",
              "channel_rear_2": "q5", "channel_rear_3": "q6"}
    for channel in parameters.channels:
        table = adapter.tables[dof_of[channel.name]]
        low, high = sorted((table.stroke(table.q_min), table.stroke(table.q_max)))
        cylinder = channel.cylinder
        assert cylinder.stroke_min_m <= low + 1.0e-5
        assert cylinder.stroke_max_m >= high - 1.0e-5
        assert abs(cylinder.stroke_min_m - low) < 1.0e-5, channel.name


# --------------------------------------------------------------- 供油
def test_supply_pressure_droops_when_demand_exceeds_the_pump(system):
    """共用供油总量是真约束：需求超过泵流量时供压必须下跌，不是无限流量。"""
    weak = replace(system.parameters, supplies={
        name: replace(pump, displacement_m3_per_rad=pump.displacement_m3_per_rad * 0.05)
        for name, pump in system.parameters.supplies.items()})
    from steering_sim.hydraulics_engineering import EngineeringHydraulicSystem
    limited = EngineeringHydraulicSystem(weak)
    commands = [1.0, 1.0, 1.0, 1.0]
    state = limited.neutral_state()
    for _ in range(1500):
        derivative, outputs = limited.evaluate(0.0, state, _Inputs(commands))
        state = state + 2.0e-4 * derivative
    assert any(outputs.pump_capacity_insufficient)
    assert outputs.supply_pressures_pa_g[0] < \
        0.9 * weak.supplies["front"].relief_pressure_pa


# --------------------------------------------------------------- 退化接口
def test_degradation_hooks_change_the_response_without_touching_the_code(parameters):
    from steering_sim.hydraulics_engineering import (EngineeringHydraulicSystem,
                                                     with_degradation)
    worn = with_degradation(
        parameters, pump_volumetric_efficiency=0.55,
        cylinder_internal_leakage_m3_s_per_pa=2.0e-11,
        valve_flow_coefficient_scale=0.6,
        cylinder_friction_scale=1.8, supply_pressure_scale=0.85)
    assert not worn.degradation.is_new_unit
    healthy = EngineeringHydraulicSystem(parameters)
    degraded = EngineeringHydraulicSystem(worn)
    commands = [0.6, 0.0, 0.0, 0.0]
    results = []
    for system in (healthy, degraded):
        state = system.neutral_state()
        for _ in range(1500):
            derivative, _ = system.evaluate(0.0, state, _Inputs(commands))
            state = state + 2.0e-4 * derivative
        results.append(float(state[CHANNEL_STATE_SIZE * 0 + 2]))
    assert results[1] < results[0], results


# --------------------------------------------------------- 与 J0 集成层
def test_the_runner_uses_the_engineering_hydraulic_model_by_default():
    from steering_sim.engineering.model import EngineeringSteeringModel
    from steering_sim.j0_coupling.config import load_j0_config
    from steering_sim.j0_coupling.runner import J0Runner
    config = load_j0_config(J0_CONFIG)
    assert config.hydraulic_model == "ENGINEERING_HYDRAULIC_V1"
    model = EngineeringSteeringModel(SPEC, ENG_CONFIG, ENG_DESIGN)
    runner = J0Runner(config, model, probe_authority=False)
    assert runner.hydraulic_model == "ENGINEERING_HYDRAULIC_V1"
    assert runner.state_stride == CHANNEL_STATE_SIZE
    assert runner.speeds[0] == pytest.approx(
        runner.engineering_parameters.supplies["front"].nominal_speed_rad_s)


def test_a_straight_ahead_case_is_not_treated_as_outside_the_envelope():
    """PHASE J1 的明确缺陷：0° 直行被误判为超出机构包络，必须修复。"""
    from steering_sim.engineering.model import EngineeringSteeringModel
    geometry = EngineeringSteeringModel(SPEC, ENG_CONFIG, ENG_DESIGN).solve_geometry(0.0)
    assert geometry.geometry_class == "OK"
    assert not any(geometry.q_boundary_limited.values())
    assert geometry.geometry_reachable


def test_the_mapping_tolerates_only_the_mechanical_end_stop():
    """行程反解只在极小容差内把"缸走到头"当成限位事件；超出仍然显式失败。"""
    from steering_sim.engineering.model import EngineeringSteeringModel
    from steering_sim.j0_coupling.config import load_j0_config
    from steering_sim.j0_coupling.geometry import J0GeometryAdapter
    model = EngineeringSteeringModel(SPEC, ENG_CONFIG, ENG_DESIGN)
    adapter = J0GeometryAdapter(model, load_j0_config(J0_CONFIG),
                                mechanical_mode="ENGINEERING_STEERING_MODEL")
    table = adapter.tables["q6"]
    low, high = sorted((table.stroke(table.q_min), table.stroke(table.q_max)))
    _q, status = adapter.q_from_stroke("q6", high + 1.0e-3)
    assert status.flags == ("MAPPING_AT_ENVELOPE_LIMIT",)
    _q, status = adapter.q_from_stroke("q6", high + 1.0)
    assert status.flags == ("MAPPING_OUT_OF_ENVELOPE",)


# ------------------------------------------------------------- 闭环跟踪
@pytest.mark.slow
@pytest.mark.parametrize("angle,speed", [(0.0, 0.0), (2.0, 5.0), (-5.0, 5.0),
                                         (10.0, 10.0), (30.0, 10.0), (-30.0, 10.0)])
def test_closed_loop_tracks_the_mechanism_command(angle, speed):
    from steering_sim.engineering.model import EngineeringSteeringModel
    from steering_sim.j0_coupling.config import J0CaseConfig, load_j0_config
    from steering_sim.j0_coupling.runner import J0Runner
    config = load_j0_config(J0_CONFIG)
    model = EngineeringSteeringModel(SPEC, ENG_CONFIG, ENG_DESIGN)
    runner = J0Runner(config, model, probe_authority=False)
    ramp = max(0.4, abs(angle) / 12.0)
    case = J0CaseConfig(id=f"{angle:+.0f}", target_outer_angle_deg=angle,
                        speed_kmh=speed, duration_s=ramp + max(0.9, 0.5 * ramp))
    result = runner.run_case(case)
    summary = result.summary
    assert summary["NUMERICAL_COMPLETED"]
    assert summary["TRACKING_PASS"], summary.get("status_notes")
    assert summary["TRANSIENT_TRACKING_PASS"], summary.get("status_notes")
    assert summary["steady_max_tracking_error_vs_command_deg"] < 0.25
    assert summary["max_tracking_error_vs_command_deg"] < 1.0
    assert summary["control_saturation_fraction"] < 0.05
    assert summary["third_axle_max_abs_deg"] < 1.0e-9
    assert summary["max_link_residual_m"] < 1.0e-9
    assert not summary["envelope_limit_samples"]
    assert summary["max_pump_demand_ratio"] < 1.0
