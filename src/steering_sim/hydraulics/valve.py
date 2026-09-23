"""Configuration-driven representative SC_1 static solenoid valve."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .expressions import SafeExpression
from .orifice import HYDVORF0
from .valve_dynamics import StaticValveDynamics

FLOW_PATHS = ("P-B", "P-A", "T-A", "T-B")


@dataclass(frozen=True, slots=True)
class ValveOpeningObservation:
    fractional_spool_position: float
    openings: Mapping[str, float]
    spool_clipped: bool


@dataclass(frozen=True, slots=True)
class ValveObservation(ValveOpeningObservation):
    path_flows_m3_s: Mapping[str, float]
    port_flows_into_valve_m3_s: Mapping[str, float]
    flow_residual_m3_s: float


class SC1StaticValve:
    def __init__(self, spool_mapping: SafeExpression, opening_functions: Mapping[str, SafeExpression], dynamics: StaticValveDynamics, orifices: Mapping[str, HYDVORF0]) -> None:
        if set(opening_functions) != set(FLOW_PATHS) or set(orifices) != set(FLOW_PATHS):
            raise ValueError(f"SC_1 requires exactly the four flow paths {FLOW_PATHS}")
        self.spool_mapping = spool_mapping
        self.opening_functions = dict(opening_functions)
        self.dynamics = dynamics
        self.orifices = dict(orifices)

    def openings(self, command: float) -> ValveOpeningObservation:
        mapped = self.spool_mapping.evaluate(x=float(command))
        dyn = self.dynamics.evaluate(mapped)
        openings = {name: expression.evaluate(x=dyn.spool) for name, expression in self.opening_functions.items()}
        return ValveOpeningObservation(dyn.spool, openings, dyn.clipped)

    def evaluate(self, command: float, p_p_pa: float, p_t_pa: float, p_a_pa: float, p_b_pa: float) -> ValveObservation:
        op = self.openings(command)
        pressures = {"P-B": (p_p_pa, p_b_pa), "P-A": (p_p_pa, p_a_pa), "T-A": (p_t_pa, p_a_pa), "T-B": (p_t_pa, p_b_pa)}
        flows = {name: self.orifices[name].flow(*pressures[name], op.openings[name]).flow_m3_s for name in FLOW_PATHS}
        ports = {
            "P": -flows["P-B"] - flows["P-A"], "T": -flows["T-A"] - flows["T-B"],
            "A": flows["P-A"] + flows["T-A"], "B": flows["P-B"] + flows["T-B"],
        }
        return ValveObservation(op.fractional_spool_position, op.openings, op.spool_clipped, flows, ports, sum(ports.values()))

