"""PHASE J0-R1：液压执行器力/容积方向一致性的最小物理测试。

对应 `phase_J0_R1` 任务书第 3 节的 6 项要求。这些测试检查的是**物理**，不是实现：

1. A 腔受压 → 活塞向使 A 腔扩张的方向运动；
2. B 腔受压 → 活塞向使 B 腔扩张的方向运动；
3. 无外部流量时，容积压缩产生回复作用（`dF_hyd/dx < 0`）；
4. 液压—机械功率转换方向一致（被动执行器不得在零命令下输出净能量）；
5. 零输入平衡点附近的小扰动不自激发散（`dF_hyd/dv < 0`）；
6. 四个通道全部通过。

约定（与 `actuator.py` 的 `chamber_volumes` 一致）：

    V_a = V_a0 - A_a*x      V_b = V_b0 + A_b*x
    x 增大  ->  A 腔被压缩，B 腔扩张

因此 A 腔压力必须把活塞推向 -x，B 腔压力必须把它推向 +x：

    F_hyd = -A_a*p_a + A_b*p_b
"""
from __future__ import annotations

import numpy as np
import pytest

from steering_sim.hydraulics_lumped import (HydraulicInput, LumpedHydraulicSystem,
                                            evaluate_hydraulic)
from steering_sim.hydraulics_lumped.simulation import simulate_rk4

DT = 5.0e-4
# 修复后的中立命令：前阀改为普通对称四通后，四个通道的中立点都是 0。
NEUTRAL_COMMANDS = (0.0, 0.0, 0.0, 0.0)
CHANNEL_INDEX = {"front": 0, "rear_1": 1, "rear_2": 2, "rear_3": 3}


def _model() -> LumpedHydraulicSystem:
    return LumpedHydraulicSystem.fast_engineering()


def _pressures(model: LumpedHydraulicSystem) -> list[float]:
    """平衡压力：两腔流量同时为零的压力（p_a = p_b = P*）。"""
    return [channel.supply.regulated_return_rail_pressure for channel in model.channels]


def _loads(model: LumpedHydraulicSystem) -> tuple[float, ...]:
    """与初始液压力一致的平衡外载（符号随力的约定一起修正）。"""
    pressures = _pressures(model)
    return tuple(channel.actuator.area_b * pressure - channel.actuator.area_a * pressure
                 for channel, pressure in zip(model.channels, pressures))


def _state(model: LumpedHydraulicSystem, index: int, *, p_a=None, p_b=None,
           x: float = 0.0, v: float = 0.0) -> np.ndarray:
    state = np.zeros(model.state_count)
    for i, channel in enumerate(model.channels):
        p = _pressures(model)[i]
        state[4 * i:4 * i + 4] = (p, p, 0.0, 0.0)
    if p_a is not None:
        state[4 * index] = p_a
    if p_b is not None:
        state[4 * index + 1] = p_b
    state[4 * index + 2] = x
    state[4 * index + 3] = v
    return state


def _inputs(model: LumpedHydraulicSystem, loads, commands=NEUTRAL_COMMANDS,
            prescribed=None) -> HydraulicInput:
    speeds = tuple(channel.pump.nominal_speed for channel in model.channels)
    return HydraulicInput(tuple(commands), speeds, loads,
                          prescribed_motion_by_alias=prescribed)


@pytest.mark.parametrize("name", sorted(CHANNEL_INDEX))
def test_pressurised_chamber_a_moves_to_expand_chamber_a(name):
    """要求 1：A 腔受压时活塞必须向使 A 腔扩张的方向（x 减小）运动。"""
    model = _model()
    index = CHANNEL_INDEX[name]
    base = _pressures(model)[index]
    state = _state(model, index, p_a=base + 1.0e6, p_b=base)
    dx, _ = evaluate_hydraulic(model, 0.0, state, _inputs(model, (0.0,) * 4))
    assert dx[4 * index + 3] < 0.0, f"{name}: A 腔受压却产生非负加速度"


@pytest.mark.parametrize("name", sorted(CHANNEL_INDEX))
def test_pressurised_chamber_b_moves_to_expand_chamber_b(name):
    """要求 2：B 腔受压时活塞必须向使 B 腔扩张的方向（x 增大）运动。"""
    model = _model()
    index = CHANNEL_INDEX[name]
    base = _pressures(model)[index]
    state = _state(model, index, p_a=base, p_b=base + 1.0e6)
    dx, _ = evaluate_hydraulic(model, 0.0, state, _inputs(model, (0.0,) * 4))
    assert dx[4 * index + 3] > 0.0, f"{name}: B 腔受压却产生非正加速度"


@pytest.mark.parametrize("name", sorted(CHANNEL_INDEX))
def test_compression_is_restored_not_reinforced(name):
    """要求 3：无外部流量时容积压缩必须产生回复力，即 dF_hyd/dx < 0。

    用给定的缓慢正弦位移（运动由边界给定）线性回归 F = k*x + c*v + b；
    被动执行器必须给出 k < 0。
    """
    from steering_sim.j0_coupling.diagnostics import characterise_channel

    model = _model()
    index = CHANNEL_INDEX[name]
    d_f_d_v, d_f_d_x, _ = characterise_channel(model, index, NEUTRAL_COMMANDS[index],
                                               amplitude_m=1.0e-4, frequency_hz=1.0,
                                               cycles=4.0)
    assert d_f_d_x < 0.0, f"{name}: dF_hyd/dx = {d_f_d_x:.4e} N/m，压缩被强化而不是回复"
    assert d_f_d_v < 0.0, f"{name}: dF_hyd/dv = {d_f_d_v:.4e} N/(m/s)，阻尼符号仍为发散"


@pytest.mark.parametrize("name", sorted(CHANNEL_INDEX))
def test_passive_actuator_absorbs_energy_under_prescribed_motion(name):
    """要求 4：零命令下被动执行器不得输出净液压功率。

    ∫F_hyd·v dt 必须 <= 0（吸收机械能），否则液压—机械功率转换方向不一致。
    """
    model = _model()
    index = CHANNEL_INDEX[name]
    alias = model.channels[index].actuator_alias
    amplitude, frequency = 1.0e-4, 1.0
    loads = _loads(model)
    state = _state(model, index)

    def inputs(t: float) -> HydraulicInput:
        x = amplitude * np.sin(2.0 * np.pi * frequency * t)
        v = amplitude * 2.0 * np.pi * frequency * np.cos(2.0 * np.pi * frequency * t)
        a = -(2.0 * np.pi * frequency) ** 2 * x
        return _inputs(model, loads, NEUTRAL_COMMANDS, {alias: (x, v, a)})

    duration = 2.0 / frequency
    times, states = simulate_rk4(model, duration, DT,
                                 lambda t: inputs(t).to_system_inputs(), state)
    work = 0.0
    for k, t in enumerate(times):
        _, outputs = evaluate_hydraulic(model, t, states[k], inputs(t))
        v = amplitude * 2.0 * np.pi * frequency * np.cos(2.0 * np.pi * frequency * t)
        if k:
            work += outputs.channels[index].hydraulic_force_n * v * DT
    assert work < 0.0, f"{name}: 被动执行器净输出功率 {work:.4e} J，方向不一致"


@pytest.mark.parametrize("name", sorted(CHANNEL_INDEX))
def test_small_velocity_perturbation_decays(name):
    """要求 5：零输入平衡点附近的小扰动不得自激发散（dF_hyd/dv < 0）。"""
    model = _model()
    index = CHANNEL_INDEX[name]
    loads = _loads(model)
    state = _state(model, index, v=1.0e-4)
    inputs = _inputs(model, loads).to_system_inputs()
    _, states = simulate_rk4(model, 0.2, DT, lambda _t: inputs, state)
    assert np.all(np.isfinite(states))
    assert abs(states[-1, 4 * index + 3]) <= abs(1.0e-4) * 1.001, (
        f"{name}: 小扰动被放大到 {states[-1, 4 * index + 3]:.4e} m/s")


def test_all_four_channels_are_checked():
    """要求 6：四个通道都在上述参数化覆盖范围内。"""
    assert set(CHANNEL_INDEX) == {"front", "rear_1", "rear_2", "rear_3"}
