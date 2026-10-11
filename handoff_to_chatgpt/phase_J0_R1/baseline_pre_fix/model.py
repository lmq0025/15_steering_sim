from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence
import numpy as np

from .actuator import actuator_rates
from .parameters import ChannelParameters, default_channels, default_sc1_valves
from .pump import pump_flow, pump_torque
from .supply import (FastSupplyWorkspace, solve_sc1_load_sensing_network,
                     solve_regulated_constant_pressure,
                     solve_sc1_shared_supply, solve_shared_supply,
                     solve_supply_fast)


SUPPLY_MODE = "regulated_constant_pressure"


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

    @classmethod
    def fast_engineering(cls, channels: Sequence[ChannelParameters] | None = None
                         ) -> "LumpedHydraulicSystem":
        """Build the Phase L1-Fast 16-state regulated-source model."""
        return cls(channels=channels, valve_mode="sc1", supply_mode=SUPPLY_MODE)

    def __init__(self, channels: Sequence[ChannelParameters] | None = None,
                 valve_mode: str = "sc1", supply_mode: str = "spatial",
                 algebraic_solver: str = "fast"):
        self.channels = list(channels or default_channels())
        self.state_count = self.states_per_channel * len(self.channels)
        if valve_mode not in {"legacy", "sc1"}:
            raise ValueError("valve_mode must be 'legacy' or 'sc1'")
        if supply_mode not in {"legacy", "spatial", "regulated_constant_pressure"}:
            raise ValueError(
                "supply_mode must be 'legacy', 'spatial', or "
                "'regulated_constant_pressure'")
        if algebraic_solver not in {"reference", "fast_scalar", "fast"}:
            raise ValueError(
                "algebraic_solver must be 'reference', 'fast_scalar', or 'fast'")
        self.valve_mode = valve_mode
        self.supply_mode = supply_mode
        self.algebraic_solver = algebraic_solver
        self.sc1_valves = default_sc1_valves()
        self._low_pressure_guess: dict[str, float] = {}
        self._supply_workspaces: dict[str, FastSupplyWorkspace] = {}
        self._group_specs: dict[str, tuple] = {}
        for group in sorted({c.supply_group for c in self.channels}):
            indices = tuple(i for i, c in enumerate(self.channels)
                            if c.supply_group == group)
            cs = tuple(self.channels[i] for i in indices)
            branches = tuple(
                (i, swap, alias, c, self.sc1_valves[alias])
                for i, c in zip(indices, cs)
                for alias, swap in zip(c.valve_aliases, c.valve_work_port_swaps)
            )
            self._group_specs[group] = (indices, cs, cs[0].pump_aliases, branches)
            self._supply_workspaces[group] = FastSupplyWorkspace()

    def reset_fast_solver(self) -> None:
        self._low_pressure_guess.clear()
        self._supply_workspaces = {
            group: FastSupplyWorkspace() for group in self._group_specs
        }

    def fast_solver_diagnostics(self) -> dict[str, dict[str, float | int]]:
        return {group: workspace.diagnostics()
                for group, workspace in self._supply_workspaces.items()}

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

    def evaluate(self, t: float, state: np.ndarray, inputs: SystemInputs,
                 *, _build_outputs: bool = True
                 ) -> tuple[np.ndarray, list[dict[str, float]]]:
        del t
        self._inputs(inputs)
        if np.asarray(state).shape != (self.state_count,):
            raise ValueError(f"state must have shape ({self.state_count},)")
        dx = np.empty_like(state, dtype=float)
        outputs: list[dict[str, float]] = []
        group_results: dict[str, tuple] = {}
        for group, (indices, cs, pump_aliases, compiled_branches) in self._group_specs.items():
            q_p = sum(pump_flow(self._pump_speed(inputs, alias, inputs.pump_speeds[indices[0]]),
                                0.0, cs[0].supply.tank_pressure, cs[0].pump)
                      for alias in pump_aliases)
            branch_commands: list[float] = []
            branch_pa: list[float] = []
            branch_pb: list[float] = []
            branch_channels: list[ChannelParameters] = []
            branch_valves = []
            branch_owners: list[tuple[int, bool, str]] = []
            for i, swap, alias, c, valve in compiled_branches:
                pa, pb = float(state[4*i]), float(state[4*i+1])
                # The channel-level compatibility input addresses the primary
                # SC_1.  Redundant wrappers retain independent commands.
                fallback = (inputs.valve_commands[i]
                            if alias in {"dirvalve_1", "dirvalve_6",
                                         "dirvalve_8", "dirvalve_11"}
                            else 0.0)
                command = self._valve_command(inputs, alias, fallback)
                branch_commands.append(command)
                branch_pa.append(pb if swap else pa)
                branch_pb.append(pa if swap else pb)
                branch_channels.append(c)
                branch_valves.append(valve)
                branch_owners.append((i, swap, alias))
            if self.valve_mode == "legacy":
                solution = solve_shared_supply(q_p, branch_commands, branch_pa, branch_pb, branch_channels)
            elif self.supply_mode == "legacy":
                solution = solve_sc1_shared_supply(
                    q_p, branch_commands, branch_pa, branch_pb, branch_channels,
                    branch_valves, spatial_path=False)
            elif self.supply_mode == "regulated_constant_pressure":
                solution = solve_regulated_constant_pressure(
                    q_p, branch_commands, branch_pa, branch_pb,
                    branch_channels, branch_valves)
            else:
                if self.algebraic_solver in {"fast", "fast_scalar"}:
                    solution = solve_supply_fast(
                        q_p, branch_commands, branch_pa, branch_pb,
                        branch_channels, branch_valves,
                        self._supply_workspaces[group],
                        use_analytic=self.algebraic_solver == "fast")
                else:
                    solution = solve_sc1_load_sensing_network(
                        q_p, branch_commands, branch_pa, branch_pb,
                        branch_channels, branch_valves,
                        self._low_pressure_guess.get(group))
                if solution.valve_p_pressures:
                    self._low_pressure_guess[group] = solution.valve_p_pressures[0]
            group_results[group] = (solution, indices, branch_owners)

        for i, (c, u, omega, load) in enumerate(zip(
                self.channels, inputs.valve_commands, inputs.pump_speeds, inputs.load_forces)):
            p_a, p_b, position, velocity = state[4 * i:4 * i + 4]
            prescribed = (inputs.prescribed_motion_by_alias or {}).get(c.actuator_alias)
            if prescribed is not None:
                position, velocity, acceleration = map(float, prescribed)
            solution, indices, branch_owners = group_results[c.supply_group]
            physical_flows = []
            for bi, (vf_local, (owner, swap, alias)) in enumerate(zip(solution.valve_flows, branch_owners)):
                if owner != i:
                    continue
                if alias == "dirvalve_6":
                    # SC_1 local A is an upstream circulation node; only local
                    # B is directly the HJ021 chamber represented here.
                    physical_a, physical_b = 0.0, vf_local.q_b
                else:
                    physical_a = vf_local.q_b if swap else vf_local.q_a
                    physical_b = vf_local.q_a if swap else vf_local.q_b
                physical_flows.append((
                    physical_a, physical_b, vf_local.q_supply, vf_local.opening,
                    alias, vf_local, bi))
            q_a = sum(v[0] for v in physical_flows)
            q_b = sum(v[1] for v in physical_flows)
            rates = actuator_rates(p_a, p_b, position, velocity,
                                   q_a, q_b,
                                   float(load), c.actuator, c.fluid)
            dx[4 * i:4 * i + 4] = [rates.dp_a, rates.dp_b,
                                    velocity if prescribed is not None else rates.dx,
                                    acceleration if prescribed is not None else rates.dv]
            if not _build_outputs:
                continue
            q_p = sum(pump_flow(self._pump_speed(inputs, alias, omega), 0.0,
                                c.supply.tank_pressure, c.pump) for alias in c.pump_aliases)
            outputs.append({
                "pump_flow": q_p, "group_pump_flow": solution.pump_flow,
                "supply_pressure": solution.pump_outlet_pressure or solution.pressure,
                "pump_outlet_pressure": solution.pump_outlet_pressure or solution.pressure,
                "manifold_pressure": solution.pressure,
                "valve_high_rail_pressure": (solution.valve_t_pressures[physical_flows[0][6]]
                    if physical_flows and solution.valve_t_pressures else solution.pressure),
                "valve_return_rail_pressure": (solution.valve_p_pressures[physical_flows[0][6]]
                    if physical_flows and solution.valve_p_pressures else c.supply.tank_pressure),
                "relief_flow": solution.relief_flow, "pA": p_a, "pB": p_b,
                "load_pressure": p_a - p_b,
                "valve_opening": max((v[3] for v in physical_flows), default=0.0),
                "QA": q_a, "QB": q_b,
                "valve_branch_count": float(len(physical_flows)),
                "supply_balance_residual": solution.residual,
                "supply_balance_relative_residual": solution.relative_residual,
                "supply_iterations": float(solution.iterations),
                "manifold_balance_residual": solution.manifold_residual,
                "return_absorbed_flow": solution.return_node_residual,
                "pump_capacity_margin": solution.capacity_margin,
                "pump_capacity_insufficient": float(solution.capacity_insufficient),
                "supply_solver_iterations": float(solution.iterations),
                "q_PA": sum(v[5].q_pa for v in physical_flows),
                "q_PB": sum(v[5].q_pb for v in physical_flows),
                "q_AT": sum(v[5].q_at for v in physical_flows),
                "q_BT": sum(v[5].q_bt for v in physical_flows),
                "position": position, "velocity": velocity,
                "hydraulic_force": rates.hydraulic_force,
                "pump_torque": pump_torque(solution.pressure, c.supply.tank_pressure, c.pump),
                "volume_A": rates.volume_a, "volume_B": rates.volume_b,
            })
        return dx, outputs

    def rhs(self, t: float, state: np.ndarray, inputs: SystemInputs) -> np.ndarray:
        return self.evaluate(t, state, inputs, _build_outputs=False)[0]
