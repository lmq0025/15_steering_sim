"""PHASE J0-R1 F2 验收：前桥执行器必须双向、有量级正确的静态作动力。

背景（`docs/handoff/J0_claude/05_J0_PLANT_DEFECT_AND_KNOWN_RISKS.md` F2）：
修复前 `model.py` 对 `dirvalve_6` 特判 ``physical_a = 0.0``，前缸 A 腔没有阀口流量，
只能靠 `actuator002` 上被单独写入的 0.5 L/min@100 bar 人工内泄漏补油，两腔压力被强制
拉平，静态作动力窗口只有约 33 N，而前端组在 J0-02 需要约 6.2 kN。

修复依据：
* `phase_L1_R2_macro_mapping_report.md`：IR V3 记录 dirvalve_6 相对 actuator002 的
  A/B 工作口换位；
* `audit_parameters.py`：dirvalve_6 与 dirvalve_8 的 SUBMODEL 外端口暴露映射相同；
* `R03B15_AMESim_manual_execution_guide.md:60` / `R03B1_implementation_report.md:70`：
  缸的 leakage 源参数为 0。
"""
from __future__ import annotations

import numpy as np
import pytest

from steering_sim.hydraulics_lumped import (LumpedHydraulicSystem, precharged_state)
from steering_sim.hydraulics_lumped.simulation import simulate_rk4
from steering_sim.j0_coupling.authority import steady_force

FRONT_INDEX = 0
NEUTRAL = (0.0, 0.0, 0.0, 0.0)
# M1 工程假设道路负载对前端组的需求量级（+2° 时约 6.2 kN）。这是量级门槛，
# 不是实车标定值，不要求精确匹配。
REQUIRED_FRONT_FORCE_N = 6.0e3


@pytest.fixture
def model():
    return LumpedHydraulicSystem.fast_engineering()


def test_front_valve_uses_a_symmetric_four_way_topology(model):
    """前阀必须与后三只主阀同构：SC_1 两个工作口都接缸腔。"""
    channel = model.channels[FRONT_INDEX]
    assert channel.actuator_alias == "actuator002"
    assert channel.valve_aliases == ("dirvalve_6",)
    assert channel.valve_work_port_swaps == (True,)


def test_front_actuator_has_no_artificial_internal_leakage(model):
    """人工内泄漏必须撤除，与 Amesim 源参数和后三通道一致。"""
    for channel in model.channels:
        assert channel.actuator.leakage == 0.0, channel.name


def test_front_neutral_command_is_zero_not_one(model):
    """J0-R1 后前阀中立点回到 0.0；原 +1.0 不得再被当作双向阀零位。"""
    state, loads, pressures = precharged_state(model, NEUTRAL)
    lo, hi = sorted(
        (model.channels[FRONT_INDEX].supply.regulated_return_rail_pressure,
         model.channels[FRONT_INDEX].supply.regulated_high_rail_pressure))
    # 中立位四个孔口全开 -> 两腔稳态压力是两条轨的均值。
    assert pressures[FRONT_INDEX][0] == pytest.approx(0.5 * (lo + hi), rel=1e-6)
    assert pressures[FRONT_INDEX][1] == pytest.approx(0.5 * (lo + hi), rel=1e-6)
    # 中立命令下液压力为零（双杆等面积），因此平衡外载为零。
    assert abs(loads[FRONT_INDEX]) < 1.0e-9


def test_front_static_force_window_is_bidirectional_and_large_enough(model):
    """要求：正反两个方向都有非零作动力，且量级与 6.2 kN 负载需求匹配。"""
    window = [steady_force(model, FRONT_INDEX, float(u), NEUTRAL, duration_s=0.5)
              for u in np.linspace(-1.0, 1.0, 9)]
    low, high = float(min(window)), float(max(window))
    assert low < 0.0 < high, "前桥仍然是单向作动"
    assert -low >= REQUIRED_FRONT_FORCE_N * 0.75
    assert high >= REQUIRED_FRONT_FORCE_N * 0.75
    # 原缺陷只有约 33 N；修复后必须高出两个数量级。
    assert (high - low) > 100.0 * 33.0
    # 中立点附近力应当过零。
    assert abs(steady_force(model, FRONT_INDEX, 0.0, NEUTRAL, duration_s=0.5)) < 50.0


@pytest.mark.parametrize("command,expected_sign", ((0.05, 1.0), (-0.05, -1.0)))
def test_front_moves_in_both_directions_without_load(model, command, expected_sign):
    """无载时两个方向都必须能够运动。"""
    state, loads, _ = precharged_state(model, NEUTRAL)
    loads = (0.0,) * 4
    from steering_sim.hydraulics_lumped import HydraulicInput
    speeds = tuple(channel.pump.nominal_speed for channel in model.channels)
    commands = [0.0] * 4
    commands[FRONT_INDEX] = command
    inputs = HydraulicInput(tuple(commands), speeds, loads).to_system_inputs()
    _, states = simulate_rk4(model, 0.2, 5.0e-4, lambda _t: inputs, state)
    assert np.all(np.isfinite(states))
    moved = states[-1, 4 * FRONT_INDEX + 2]
    assert np.sign(moved) == expected_sign, f"command {command:+.2f} 产生位移 {moved:.4e} m"


def test_front_pressure_stays_inside_the_supply_envelope(model):
    """前桥不得产生人为的异常压力。

    门槛取前组高压轨的 1.5 倍：活塞运动时为了让油液经阀口排出，腔压会短暂高于
    供油轨，这是正常的液压峰值；而修复前该通道的异常表现为数百 MPa。
    """
    channel = model.channels[FRONT_INDEX]
    rail = channel.supply.regulated_high_rail_pressure
    state, loads, _ = precharged_state(model, NEUTRAL)
    from steering_sim.hydraulics_lumped import HydraulicInput
    speeds = tuple(c.pump.nominal_speed for c in model.channels)
    peaks: list[float] = []
    for command in (-1.0, -0.5, 0.0, 0.5, 1.0):
        commands = [0.0] * 4
        commands[FRONT_INDEX] = command
        inputs = HydraulicInput(tuple(commands), speeds, (0.0,) * 4).to_system_inputs()
        _, states = simulate_rk4(model, 0.5, 5.0e-4, lambda _t: inputs, state)
        assert np.all(np.isfinite(states))
        peak = float(np.max(np.abs(states[:, 4 * FRONT_INDEX:4 * FRONT_INDEX + 2])))
        peaks.append(peak)
        assert peak < 1.5 * rail, f"command {command:+.2f} 产生 {peak/1e6:.1f} MPa"
        assert peak < 100.0e6
    # 全行程峰值必须明显低于供油轨的 1.5 倍，而不是刚好卡在门槛上。
    assert max(peaks) < 1.35 * rail, f"峰值 {max(peaks)/1e6:.1f} MPa 过于接近门槛"
