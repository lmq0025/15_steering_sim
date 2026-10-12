"""工程液压模型的命令极性与静态力窗口实测探针。

任务书第四节要求"**自动验证正负方向控制极性**"。这里不去"相信设计意图"，而是
在零位健康状态上真的走一遍：

* **极性**：把活塞运动冻结在零位，只给一小段阀命令，看**活塞速度的符号**。
  这是可观测量，和 L1-Fast 验收测试用的是同一类判据。
* **力窗口**：把活塞位移与速度都钉死，让两腔压力自然弛豫到稳态，读出
  ``F = pA·Aa − pB·Ab``。窗口宽度决定该通道能不能顶住转向负载。

探针对模型只读：它自己复制状态积分，不回写任何东西。
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping, Sequence

import numpy as np

from .model import CHANNEL_STATE_SIZE, EngineeringHydraulicSystem

#: 极性扰动幅度（归一化命令）。
POLARITY_DELTA = 0.05
#: 极性观测时长（s）。必须明显长于阀芯时间常数。
POLARITY_DURATION_S = 0.02
#: 力窗口弛豫时长（s）。
FORCE_SETTLE_S = 0.30
#: 积分步长（s）。
PROBE_STEP_S = 2.5e-4


@dataclass(frozen=True, slots=True)
class EngineeringAuthority:
    index: int
    channel: str
    neutral_command: float
    command_window: tuple[float, float]
    velocity_at_plus_delta_m_s: float
    velocity_at_minus_delta_m_s: float
    d_velocity_over_d_command: float
    force_window_n: tuple[float, float]
    reachable_x_signs: tuple[int, ...]
    notes: tuple[str, ...]

    @property
    def command_polarity(self) -> int:
        return 1 if self.d_velocity_over_d_command > 0.0 else -1

    @property
    def bidirectional(self) -> bool:
        return set(self.reachable_x_signs) == {-1, 1}

    @property
    def balanced_force_window(self) -> bool:
        low, high = self.force_window_n
        smaller = min(abs(low), abs(high))
        larger = max(abs(low), abs(high))
        return larger <= 1.0e-9 or smaller / larger >= 0.8

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "neutral_command": self.neutral_command,
            "command_window": list(self.command_window),
            "command_polarity": self.command_polarity,
            "d_velocity_over_d_command": self.d_velocity_over_d_command,
            "velocity_at_plus_delta_m_s": self.velocity_at_plus_delta_m_s,
            "velocity_at_minus_delta_m_s": self.velocity_at_minus_delta_m_s,
            "force_window_n": list(self.force_window_n),
            "reachable_x_signs": list(self.reachable_x_signs),
            "bidirectional": self.bidirectional,
            "balanced_force_window": self.balanced_force_window,
            "notes": list(self.notes),
        }


class _Inputs:
    __slots__ = ("valve_commands", "external_load_forces_n")

    def __init__(self, commands, loads) -> None:
        self.valve_commands = tuple(commands)
        self.external_load_forces_n = tuple(loads)


def _rk4(system: EngineeringHydraulicSystem, state: np.ndarray, commands, loads,
         duration_s: float, pin_piston: bool) -> np.ndarray:
    """定步长 RK4；``pin_piston`` 时把 x、v 的导数钉为 0。"""
    inputs = _Inputs(commands, loads)
    steps = max(1, int(round(duration_s / PROBE_STEP_S)))
    dt = PROBE_STEP_S

    def rhs(current: np.ndarray) -> np.ndarray:
        derivative, _ = system.evaluate(0.0, current, inputs)
        if pin_piston:
            for index in range(len(system.parameters.channels)):
                base = CHANNEL_STATE_SIZE * index
                derivative[base + 2] = 0.0
                derivative[base + 3] = 0.0
        return derivative

    for _ in range(steps):
        k1 = rhs(state)
        k2 = rhs(state + 0.5 * dt * k1)
        k3 = rhs(state + 0.5 * dt * k2)
        k4 = rhs(state + dt * k3)
        state = state + dt * (k1 + 2.0 * k2 + 2.0 * k3 + k4) / 6.0
    return state


def _force_n(system: EngineeringHydraulicSystem, state: np.ndarray, index: int) -> float:
    channel = system.parameters.channels[index]
    base = CHANNEL_STATE_SIZE * index
    return float(state[base] * channel.cylinder.area_a_m2
                 - state[base + 1] * channel.cylinder.area_b_m2)


def probe_engineering_authority(system: EngineeringHydraulicSystem, *,
                                force_samples: int = 7,
                                polarity_duration_s: float = POLARITY_DURATION_S,
                                settle_duration_s: float = FORCE_SETTLE_S
                                ) -> tuple[EngineeringAuthority, ...]:
    """逐通道实测命令极性、可达方向与静态力窗口。"""
    parameters = system.parameters
    results: list[EngineeringAuthority] = []
    for index, channel in enumerate(parameters.channels):
        neutral = 0.0
        window = (-channel.command_limit, channel.command_limit)
        responses: list[float] = []
        for sign in (1.0, -1.0):
            state = system.neutral_state()
            commands = [neutral] * len(parameters.channels)
            commands[index] = neutral + sign * POLARITY_DELTA
            final = _rk4(system, state, commands, (0.0,) * len(parameters.channels),
                         polarity_duration_s, pin_piston=False)
            responses.append(float(final[CHANNEL_STATE_SIZE * index + 3]))
        plus, minus = responses
        slope = (plus - minus) / (2.0 * POLARITY_DELTA)

        samples = np.linspace(window[0], window[1], force_samples)
        forces: list[float] = []
        for command in samples:
            state = system.neutral_state()
            commands = [neutral] * len(parameters.channels)
            commands[index] = float(command)
            settled = _rk4(system, state, commands,
                           (0.0,) * len(parameters.channels), settle_duration_s,
                           pin_piston=True)
            forces.append(_force_n(system, settled, index))
        force_low, force_high = float(min(forces)), float(max(forces))

        signs: set[int] = set()
        for reach in (window[1] - neutral, window[0] - neutral):
            value = slope * reach
            if value > 0.0:
                signs.add(1)
            elif value < 0.0:
                signs.add(-1)
        notes: list[str] = []
        if not signs:
            notes.append("ZERO_COMMAND_AUTHORITY")
        elif len(signs) == 1:
            notes.append("ONE_QUADRANT_AUTHORITY")
        if force_high - force_low < 100.0:
            notes.append("NEGLIGIBLE_STATIC_FORCE_AUTHORITY")
        if not math.isfinite(slope) or abs(slope) < 1.0e-12:
            notes.append("NON_FINITE_SLOPE")
        results.append(EngineeringAuthority(
            index=index, channel=channel.name, neutral_command=neutral,
            command_window=window,
            velocity_at_plus_delta_m_s=plus, velocity_at_minus_delta_m_s=minus,
            d_velocity_over_d_command=slope,
            force_window_n=(force_low, force_high),
            reachable_x_signs=tuple(sorted(signs, reverse=True)),
            notes=tuple(notes)))
    return tuple(results)


def assert_engineering_authority(authorities: tuple[EngineeringAuthority, ...],
                                 expected: Sequence[float],
                                 required_force_n: Mapping[str, float] | None = None
                                 ) -> None:
    """实测与配置矛盾、或双向力窗口不足时**显式失败**。"""
    for authority, polarity in zip(authorities, expected):
        if authority.command_polarity != int(math.copysign(1.0, polarity)):
            raise ValueError(
                f"{authority.channel}: 配置极性 {polarity:+.0f} 与实测 "
                f"{authority.command_polarity:+.0f} 矛盾")
        if not authority.bidirectional:
            raise ValueError(
                f"{authority.channel}: 实测只能单向作动 "
                f"{authority.reachable_x_signs}")
        if required_force_n is not None:
            need = float(required_force_n[authority.channel])
            low, high = authority.force_window_n
            available = min(abs(low), abs(high))
            if available < need:
                raise ValueError(
                    f"{authority.channel}: 静态力窗口 ±{available:.0f} N 不足以承担"
                    f"需求 {need:.0f} N")
