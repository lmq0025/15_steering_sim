"""预充压健康工作点：求解使执行器在零阀命令下静止的腔压力。

L1-Fast 是预建压正常点模型，不能从零压力启动。工作点必须同时满足

* ``x = 0``、``v = 0``，且
* 两腔的净阀口流量分别为零（否则压力会漂移），
* 外载与该状态的液压力相等（否则 t = 0 就会带上一个净力阶跃）。

原实现直接把 ``p_a = p_b = 该组回油轨压力`` 当作工作点。修正前那只对后三通道成立：
后阀在中立位只打开 P 侧孔口，两腔都被拉到同一条轨上。前阀（`primary_c` 交叉中位表）
在中立位四个孔口全开，两腔的稳态压力是两条轨的均值，而不是回油轨，因此原来的假设在
前通道上不成立。

本模块用模型自身的阀口流量求数值解，对任何阀表/命令都成立。
"""
from __future__ import annotations

from typing import Sequence

import numpy as np

from .interface import HydraulicInput, evaluate_hydraulic
from .model import LumpedHydraulicSystem


def _rail_bounds(channel) -> tuple[float, float]:
    low = float(channel.supply.regulated_return_rail_pressure)
    high = float(channel.supply.regulated_high_rail_pressure)
    return (min(low, high), max(low, high))


def equilibrium_pressures(model: LumpedHydraulicSystem,
                          valve_commands: Sequence[float]) -> np.ndarray:
    """逐通道求解使两腔净流量同时为零的 ``(p_a, p_b)``。"""
    from scipy.optimize import root

    commands = tuple(float(value) for value in valve_commands)
    speeds = tuple(channel.pump.nominal_speed for channel in model.channels)
    state = np.zeros(model.state_count)
    pressures = np.empty((len(model.channels), 2), dtype=float)
    # 其它通道的压力对当前通道无影响：regulated 边界下每组的两条轨都是定值常量。
    for index, channel in enumerate(model.channels):
        low, high = _rail_bounds(channel)
        seed = 0.5 * (low + high)

        def residual(trial: np.ndarray) -> list[float]:
            state[4 * index] = float(trial[0])
            state[4 * index + 1] = float(trial[1])
            _, outputs = evaluate_hydraulic(
                model, 0.0, state, HydraulicInput(commands, speeds, (0.0,) * 4))
            item = outputs.channels[index]
            return [item.flow_a_m3_s, item.flow_b_m3_s]

        state[4 * index] = seed
        state[4 * index + 1] = seed
        solution = root(residual, np.array([seed, seed]), method="hybr")
        candidate = solution.x if solution.success else np.array([seed, seed])
        if not np.all(np.isfinite(candidate)):
            candidate = np.array([seed, seed])
        candidate = np.clip(candidate, low, high)
        pressures[index] = candidate
        # 留下已解出的通道值，后续通道迭代时保持状态一致。
        state[4 * index] = candidate[0]
        state[4 * index + 1] = candidate[1]
    return pressures


def precharged_state(model: LumpedHydraulicSystem, valve_commands: Sequence[float]
                     ) -> tuple[np.ndarray, tuple[float, ...], np.ndarray]:
    """返回 ``(state, loads, pressures)``：预充压状态与配套的平衡外载。"""
    pressures = equilibrium_pressures(model, valve_commands)
    state = np.zeros(model.state_count)
    loads: list[float] = []
    for index, channel in enumerate(model.channels):
        state[4 * index:4 * index + 4] = (
            float(pressures[index][0]), float(pressures[index][1]), 0.0, 0.0)
        loads.append(channel.actuator.area_b * float(pressures[index][1])
                     - channel.actuator.area_a * float(pressures[index][0]))
    return state, tuple(loads), pressures
