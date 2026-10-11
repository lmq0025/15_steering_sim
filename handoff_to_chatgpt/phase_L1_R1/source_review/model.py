from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence
import numpy as np

from .actuator import actuator_rates
from .parameters import ChannelParameters, default_channels
from .pump import pump_flow, pump_torque
from .supply import solve_shared_supply


@dataclass(frozen=True)
class SystemInputs:
    valve_commands: Sequence[float]
    pump_speeds: Sequence[float]
    load_forces: Sequence[float]


class LumpedHydraulicSystem:
    states_per_channel = 4

    def __init__(self, channels: Sequence[ChannelParameters] | None = None):
        self.channels = list(channels or default_channels())
        self.state_count = self.states_per_channel * len(self.channels)

    def initial_state(self, pressure: float = 0.0) -> np.ndarray:
        x = np.zeros(self.state_count, dtype=float)
        for i, c in enumerate(self.channels):
            x[4 * i:4 * i + 4] = [pressure, pressure, c.actuator.initial_position, 0.0]
        return x

    def _inputs(self, inputs: SystemInputs) -> None:
        n = len(self.channels)
        if not (len(inputs.valve_commands) == len(inputs.pump_speeds) == len(inputs.load_forces) == n):
            raise ValueError(f"expected {n} values for each input")

    def evaluate(self, t: float, state: np.ndarray, inputs: SystemInputs) -> tuple[np.ndarray, list[dict[str, float]]]:
        del t
        self._inputs(inputs)
        if np.asarray(state).shape != (self.state_count,):
            raise ValueError(f"state must have shape ({self.state_count},)")
        dx = np.empty_like(state, dtype=float)
        outputs: list[dict[str, float]] = []
        group_results: dict[str, tuple[float, float, list, list[int]]] = {}
        for group in sorted({c.supply_group for c in self.channels}):
            indices = [i for i, c in enumerate(self.channels) if c.supply_group == group]
            cs = [self.channels[i] for i in indices]
            # pump_speeds is per actuator channel; only one representative value is
            # required because all PU001 sources in a group have the same speed.
            pump_count = len(cs[0].pump_aliases)
            q_p = pump_count * pump_flow(float(inputs.pump_speeds[indices[0]]), 0.0,
                                         cs[0].supply.tank_pressure, cs[0].pump)
            ps, qr, flows = solve_shared_supply(q_p,
                [float(inputs.valve_commands[i]) for i in indices],
                [float(state[4*i]) for i in indices], [float(state[4*i+1]) for i in indices], cs)
            group_results[group] = (ps, qr, flows, indices)

        for i, (c, u, omega, load) in enumerate(zip(
                self.channels, inputs.valve_commands, inputs.pump_speeds, inputs.load_forces)):
            p_a, p_b, position, velocity = state[4 * i:4 * i + 4]
            ps, qr_group, flows, indices = group_results[c.supply_group]
            vf = flows[indices.index(i)]
            q_p = pump_flow(float(omega), 0.0, c.supply.tank_pressure, c.pump)
            rates = actuator_rates(p_a, p_b, position, velocity,
                                   vf.q_a, vf.q_b,
                                   float(load), c.actuator, c.fluid)
            dx[4 * i:4 * i + 4] = [rates.dp_a, rates.dp_b, rates.dx, rates.dv]
            outputs.append({
                "pump_flow": q_p, "group_pump_flow": len(c.pump_aliases)*q_p, "supply_pressure": ps,
                "relief_flow": qr_group, "pA": p_a, "pB": p_b,
                "load_pressure": p_a - p_b, "valve_opening": vf.opening,
                "QA": vf.q_a, "QB": vf.q_b,
                "position": position, "velocity": velocity,
                "hydraulic_force": rates.hydraulic_force,
                "pump_torque": pump_torque(ps, c.supply.tank_pressure, c.pump),
                "volume_A": rates.volume_a, "volume_B": rates.volume_b,
            })
        return dx, outputs

    def rhs(self, t: float, state: np.ndarray, inputs: SystemInputs) -> np.ndarray:
        return self.evaluate(t, state, inputs)[0]
