from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence
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
    pump_speeds_by_alias: Mapping[str, float] | None = None
    valve_commands_by_alias: Mapping[str, float] | None = None
    # Optional hydraulic-test boundary supplied by a mechanical oracle:
    # alias -> (position [m], velocity [m/s], acceleration [m/s2]).
    # This does not change hydraulic state count and is deliberately explicit
    # so prescribed motion cannot be mistaken for an independent prediction.
    prescribed_motion_by_alias: Mapping[str, tuple[float, float, float]] | None = None


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

    @staticmethod
    def _pump_speed(inputs: SystemInputs, alias: str, fallback: float) -> float:
        if inputs.pump_speeds_by_alias is not None and alias in inputs.pump_speeds_by_alias:
            return float(inputs.pump_speeds_by_alias[alias])
        return float(fallback)

    @staticmethod
    def _valve_command(inputs: SystemInputs, alias: str, fallback: float) -> float:
        if inputs.valve_commands_by_alias is not None and alias in inputs.valve_commands_by_alias:
            return float(inputs.valve_commands_by_alias[alias])
        return float(fallback)

    def evaluate(self, t: float, state: np.ndarray, inputs: SystemInputs) -> tuple[np.ndarray, list[dict[str, float]]]:
        del t
        self._inputs(inputs)
        if np.asarray(state).shape != (self.state_count,):
            raise ValueError(f"state must have shape ({self.state_count},)")
        dx = np.empty_like(state, dtype=float)
        outputs: list[dict[str, float]] = []
        group_results: dict[str, tuple] = {}
        for group in sorted({c.supply_group for c in self.channels}):
            indices = [i for i, c in enumerate(self.channels) if c.supply_group == group]
            cs = [self.channels[i] for i in indices]
            pump_aliases = cs[0].pump_aliases
            q_p = sum(pump_flow(self._pump_speed(inputs, alias, inputs.pump_speeds[indices[0]]),
                                0.0, cs[0].supply.tank_pressure, cs[0].pump)
                      for alias in pump_aliases)
            branch_commands: list[float] = []
            branch_pa: list[float] = []
            branch_pb: list[float] = []
            branch_channels: list[ChannelParameters] = []
            branch_owners: list[tuple[int, bool, str]] = []
            for i, c in zip(indices, cs):
                pa, pb = float(state[4*i]), float(state[4*i+1])
                for alias, swap in zip(c.valve_aliases, c.valve_work_port_swaps):
                    command = self._valve_command(inputs, alias, inputs.valve_commands[i])
                    branch_commands.append(command)
                    branch_pa.append(pb if swap else pa)
                    branch_pb.append(pa if swap else pb)
                    branch_channels.append(c)
                    branch_owners.append((i, swap, alias))
            solution = solve_shared_supply(q_p, branch_commands, branch_pa, branch_pb, branch_channels)
            group_results[group] = (solution, indices, branch_owners)

        for i, (c, u, omega, load) in enumerate(zip(
                self.channels, inputs.valve_commands, inputs.pump_speeds, inputs.load_forces)):
            p_a, p_b, position, velocity = state[4 * i:4 * i + 4]
            prescribed = (inputs.prescribed_motion_by_alias or {}).get(c.actuator_alias)
            if prescribed is not None:
                position, velocity, acceleration = map(float, prescribed)
            solution, indices, branch_owners = group_results[c.supply_group]
            physical_flows = []
            for vf_local, (owner, swap, alias) in zip(solution.valve_flows, branch_owners):
                if owner != i:
                    continue
                physical_flows.append((
                    vf_local.q_b if swap else vf_local.q_a,
                    vf_local.q_a if swap else vf_local.q_b,
                    vf_local.q_supply, vf_local.opening, alias))
            q_a = sum(v[0] for v in physical_flows)
            q_b = sum(v[1] for v in physical_flows)
            q_p = sum(pump_flow(self._pump_speed(inputs, alias, omega), 0.0,
                                c.supply.tank_pressure, c.pump) for alias in c.pump_aliases)
            rates = actuator_rates(p_a, p_b, position, velocity,
                                   q_a, q_b,
                                   float(load), c.actuator, c.fluid)
            dx[4 * i:4 * i + 4] = [rates.dp_a, rates.dp_b,
                                    velocity if prescribed is not None else rates.dx,
                                    acceleration if prescribed is not None else rates.dv]
            outputs.append({
                "pump_flow": q_p, "group_pump_flow": solution.pump_flow,
                "supply_pressure": solution.pressure,
                "pump_outlet_pressure": solution.pressure,
                "manifold_pressure": solution.pressure,
                "relief_flow": solution.relief_flow, "pA": p_a, "pB": p_b,
                "load_pressure": p_a - p_b,
                "valve_opening": max((v[3] for v in physical_flows), default=0.0),
                "QA": q_a, "QB": q_b,
                "valve_branch_count": float(len(physical_flows)),
                "supply_balance_residual": solution.residual,
                "supply_balance_relative_residual": solution.relative_residual,
                "supply_iterations": float(solution.iterations),
                "position": position, "velocity": velocity,
                "hydraulic_force": rates.hydraulic_force,
                "pump_torque": pump_torque(solution.pressure, c.supply.tank_pressure, c.pump),
                "volume_A": rates.volume_a, "volume_B": rates.volume_b,
            })
        return dx, outputs

    def rhs(self, t: float, state: np.ndarray, inputs: SystemInputs) -> np.ndarray:
        return self.evaluate(t, state, inputs)[0]
