"""PHASE J0-DEMO 三项演示前检查的回归测试。

这些测试同时锁住本轮修复的三个缺陷，避免回退：

* F-D1 五、六桥左右轮反号被误当成理想阿克曼结果；
* F-D2 供油余量只有 4% 却显示"供油能力完全正常"；
* F-D3 图与摘要来自不同仿真（时间轴 3 s vs 5 s）、结果字段名与单位不符。
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from steering_sim.demo.assessment import (NEAR_LIMIT_MARGIN_FRACTION,
                                          assess_mechanism, assess_supply,
                                          check_run_consistency)
from steering_sim.demo.scenario import (reference_time_s, recommended_duration_s,  # noqa: F401
    CUSTOMER_LIMITS, ENGINEERING_DEFAULTS,
                                        VERIFIED_LIMITS, DemoScenario,
                                        preset_scenarios)


# ------------------------------------------------------------------ 工况
def test_defaults_are_flagged_as_engineering_assumptions():
    assert ENGINEERING_DEFAULTS["friction_coefficient"] == 0.75
    assert ENGINEERING_DEFAULTS["axle_mass_t"] == 11.5
    assert "ASSUMED" in ENGINEERING_DEFAULTS["source"]


def test_customer_range_is_wider_than_the_verified_range():
    for field, (low, high) in VERIFIED_LIMITS.items():
        c_low, c_high = CUSTOMER_LIMITS[field]
        assert c_low <= low and high <= c_high, field


def test_the_presets_cover_the_j1r2_acceptance_envelope():
    """PHASE J1-R2：预设覆盖直行、正负小角、中等角、±30° 最大角与高速极限工况。"""
    presets = preset_scenarios()
    assert [p.key for p in presets] == [f"R2-0{i}" for i in range(1, 8)]
    angles = [p.scenario.target_outer_angle_deg for p in presets]
    assert angles == [0.0, 2.0, -2.0, 10.0, 30.0, -30.0, 30.0]
    speeds = [p.scenario.speed_kmh for p in presets]
    assert speeds[-1] == 80.0
    for preset in presets:
        assert preset.scenario.friction_coefficient == 0.75
        assert preset.scenario.axle_mass_t == (11.5,) * 6
        # 时长必须覆盖指令斜坡 + 保持段，否则末段稳态指标没有采样点。
        ramp = reference_time_s(preset.scenario.target_outer_angle_deg)
        assert preset.scenario.duration_s > ramp + 0.85
    # 高速大角度的预设必须显式声明它是"计算完成但目标轨迹不可行"。
    assert "附着" in presets[-1].note


def test_reference_time_follows_the_rated_steering_rate():
    assert reference_time_s(0.0) == pytest.approx(0.4)
    assert reference_time_s(2.0) == pytest.approx(0.4)
    assert reference_time_s(30.0) == pytest.approx(30.0 / 12.0)
    assert recommended_duration_s(30.0) > reference_time_s(30.0)


def test_signature_round_trips_through_the_cache_parser():
    from steering_sim.demo.service import _scenario_from_signature
    for scenario in (DemoScenario(2.0, 5.0), DemoScenario(-5.0, 10.0),
                     DemoScenario(0.0, 0.0, friction_coefficient=0.78,
                                  axle_mass_t=(10.0, 11.0, 12.0, 13.0, 11.5, 10.5),
                                  duration_s=3.0)):
        restored = _scenario_from_signature(scenario.signature())
        assert restored.signature() == scenario.signature()


def test_invalid_inputs_are_rejected_loudly():
    with pytest.raises(ValueError):
        DemoScenario(0.0, 0.0, axle_mass_t=(1.0, 2.0))
    with pytest.raises(ValueError):
        DemoScenario(0.0, 0.0, duration_s=0.0)
    with pytest.raises(ValueError):
        DemoScenario(float("nan"), 0.0)


# --------------------------------------------------------- 机械轮角方向
@pytest.mark.slow
def test_axles_five_and_six_really_do_turn_left_and_right_oppositely(runner):
    """F-D1：这是 M1 闭链的真解，不是符号错误，必须被显式标记。"""
    report = assess_mechanism(runner.target(_case(5.0, 10.0)),
                              runner.geometry.model)
    # PHASE M2：五六桥的反号被识别为真实机构的物理限制，而不是笼统的"几何不可行"。
    assert report.status in ("PHYSICAL_LINKAGE_LIMIT", "ACKERMANN_GEOMETRY_DEVIATION")
    assert "ACKERMANN_GEOMETRY_DEVIATION" in report.flags
    assert "PHYSICAL_LINKAGE_LIMIT" in report.flags
    assert set(report.opposite_sign_wheels) == {"axle5_left", "axle5_right",
                                                "axle6_left", "axle6_right"}
    by_axle = {item.axle: item for item in report.axles}
    assert by_axle[5].left_right_opposite and by_axle[6].left_right_opposite
    # 四桥两轮同向，前桥也同向：说明不是"后桥一律反号"，而是 5/6 桥的真实几何。
    assert not by_axle[4].left_right_opposite
    assert not by_axle[1].left_right_opposite
    assert report.max_abs_deviation_deg > 6.0


@pytest.mark.slow
def test_straight_ahead_is_free_of_the_deviation_flag(runner):
    report = assess_mechanism(runner.target(_case(0.0, 0.0)), runner.geometry.model)
    assert report.status == "OK"
    assert report.opposite_sign_wheels == ()
    assert report.max_abs_deviation_deg < 1.0e-9


@pytest.mark.slow
def test_large_target_angle_is_infeasible_rather_than_silently_extrapolated(runner):
    from steering_sim.demo.assessment import assess_preflight
    report = assess_preflight(DemoScenario(30.0, 80.0), runner)
    assert not report.runnable
    assert "BEYOND_VERIFIED_MECHANISM_RANGE" in report.flags
    assert any("可解范围" in item for item in report.blockers)
    # 界面允许录入甲方范围，但必须同时给出外推提示。
    assert any(flag.startswith("EXTRAPOLATION:") for flag in report.flags)


# ------------------------------------------------------------- 供油
@pytest.mark.slow
def test_front_group_neutral_margin_is_small_but_not_a_shortage(runner):
    report = assess_supply(runner.hydraulic, list(runner.neutral_commands), runner.state0)
    groups = {group.name: group for group in report.groups}
    front = groups["front"]
    assert front.q_pump_m3_s == pytest.approx(27.0 / 60000.0, rel=1e-9)
    assert front.high_rail_demand_m3_s == pytest.approx(25.84 / 60000.0, rel=2e-3)
    assert not front.insufficient
    assert front.margin_fraction < NEAR_LIMIT_MARGIN_FRACTION
    assert report.status == "SUPPLY_CAPACITY_NEAR_LIMIT"
    assert "SUPPLY_CAPACITY_OUT_OF_RANGE" not in report.flags


@pytest.mark.slow
def test_shortage_is_reported_when_the_front_chamber_pressure_collapses(runner):
    """低压工况下前端确实供油不足，必须报 SUPPLY_CAPACITY_OUT_OF_RANGE。"""
    state = runner.state0.copy()
    state[0] = state[1] = 0.5e6           # channel_front 的两腔压力降到 0.5 MPa
    report = assess_supply(runner.hydraulic, list(runner.neutral_commands), state)
    assert report.status == "SUPPLY_CAPACITY_OUT_OF_RANGE"
    front = {group.name: group for group in report.groups}["front"]
    assert front.insufficient and front.margin_m3_s < 0.0


@pytest.mark.slow
def test_high_rail_accounting_matches_an_independent_orifice_evaluation(runner):
    """用未编译的孔口路径独立复算高压轨取流量，与模型内部核算一致。"""
    from steering_sim.hydraulics_lumped.valve import (compile_sc1_valve,
                                                      sc1_four_port_flows,
                                                      sc1_four_port_flows_compiled)
    hydraulic = runner.hydraulic
    channel = hydraulic.channels[0]
    supply = channel.supply
    valve = hydraulic.sc1_valves[channel.valve_aliases[0]]
    for pressure in (0.5e6, 9.3941e6, 17.4e6):
        for command in (0.0, 0.5, -1.0):
            fast = sc1_four_port_flows_compiled(
                command, supply.regulated_return_rail_pressure,
                supply.regulated_high_rail_pressure, pressure, pressure,
                compile_sc1_valve(valve))
            direct = sc1_four_port_flows(
                command, supply.regulated_return_rail_pressure,
                supply.regulated_high_rail_pressure, pressure, pressure, valve)
            assert -fast.q_return == pytest.approx(-direct.q_return, abs=1e-12)


# ------------------------------------------------------- 结果一致性
def _samples(duration_last: float = 5.0):
    time = np.linspace(0.0, duration_last, 101)
    data = {"time_s": time}
    for tag in ("channel_front", "channel_rear_1", "channel_rear_2", "channel_rear_3"):
        data[f"{tag}_x_m"] = np.zeros_like(time)
        data[f"{tag}_x_ref_m"] = np.full_like(time, 1.0e-3)
        data[f"{tag}_pA_mpa_g"] = np.full_like(time, 9.0)
        data[f"{tag}_pB_mpa_g"] = np.full_like(time, 9.0)
    data["supply_pressure_front_mpa_g"] = np.full_like(time, 17.6)
    data["supply_pressure_rear_mpa_g"] = np.full_like(time, 2.75)
    data["third_axle_max_abs_deg"] = np.zeros_like(time)
    data["max_link_residual_m"] = np.zeros_like(time)
    for axle in range(1, 7):
        for side in ("left", "right"):
            name = f"axle{axle}_{side}"
            data[f"wheel_{name}_actual_deg"] = np.linspace(0.0, 1.0, time.size)
            data[f"wheel_{name}_target_mechanism_deg"] = np.full_like(time, 1.0)
            data[f"wheel_{name}_target_deg"] = np.full_like(time, 1.0)
    return data


def test_consistency_passes_for_a_single_source_run():
    scenario = DemoScenario(5.0, 10.0, duration_s=5.0)
    report = check_run_consistency(_samples(), {"status": "PASS"}, ["a.png"], "a.csv",
                                   scenario)
    assert report.ok, report.flags


def test_consistency_catches_a_figure_time_axis_shorter_than_the_summary():
    """F-D3：3 s 的图配 5 s 的摘要必须被判为不同源。"""
    scenario = DemoScenario(5.0, 10.0, duration_s=5.0)
    report = check_run_consistency(_samples(3.0), {"status": "PASS"}, ["a.png"], "a.csv",
                                   scenario)
    assert "TIME_AXIS_SHORTER_THAN_REQUESTED" in report.flags


def test_consistency_catches_nan_and_unphysical_pressure():
    scenario = DemoScenario(0.0, 0.0, duration_s=5.0)
    samples = _samples()
    samples["channel_front_pA_mpa_g"][7] = float("nan")
    assert "NON_FINITE_SAMPLE" in check_run_consistency(
        samples, {"status": "PASS"}, ["a.png"], "a.csv", scenario).flags
    samples = _samples()
    samples["channel_front_pA_mpa_g"][:] = 130.0
    assert "PRESSURE_UNPHYSICAL" in check_run_consistency(
        samples, {"status": "PASS"}, ["a.png"], "a.csv", scenario).flags


def test_consistency_catches_a_wheel_angle_copied_from_the_target():
    scenario = DemoScenario(5.0, 10.0, duration_s=5.0)
    samples = _samples()
    samples["wheel_axle1_left_actual_deg"][0] = 1.0     # 首点即等于目标
    report = check_run_consistency(samples, {"status": "PASS"}, ["a.png"], "a.csv",
                                   scenario)
    assert "WHEEL_ANGLE_COPIED_FROM_TARGET" in report.flags


def test_consistency_catches_a_unlocked_third_axle():
    scenario = DemoScenario(5.0, 10.0, duration_s=5.0)
    samples = _samples()
    samples["third_axle_max_abs_deg"][:] = 0.4
    report = check_run_consistency(samples, {"status": "PASS"}, ["a.png"], "a.csv",
                                   scenario)
    assert "THIRD_AXLE_NOT_LOCKED" in report.flags


def _case(angle: float, speed: float):
    from steering_sim.j0_coupling.config import J0CaseConfig
    return J0CaseConfig(id="T", target_outer_angle_deg=angle, speed_kmh=speed,
                        duration_s=1.0)
