"""Minimal SC_1 + HJ020 prescribed-motion assembly boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
import numpy as np
from numpy.typing import NDArray
from .cylinder import HJ020Cylinder
from .valve import SC1StaticValve

ScalarBoundary = float | Callable[[float], float]


def _at(value: ScalarBoundary, t: float) -> float:
    return float(value(t) if callable(value) else value)


@dataclass(frozen=True, slots=True)
class PrescribedBoundary:
    command: ScalarBoundary
    supply_pressure_pa: ScalarBoundary
    return_pressure_pa: ScalarBoundary
    displacement_m: ScalarBoundary
    velocity_mps: ScalarBoundary


class SingleActuatorPrescribedMotionRig:
    state_names = ("p1_pa", "p2_pa")

    def __init__(self, valve: SC1StaticValve, cylinder: HJ020Cylinder) -> None:
        self.valve, self.cylinder = valve, cylinder

    def rhs(self, t: float, state: NDArray[np.float64], boundary: PrescribedBoundary) -> NDArray[np.float64]:
        values = np.asarray(state, dtype=float)
        if values.shape != (2,):
            raise ValueError("Rig state must be [p1, p2]")
        p1, p2 = map(float, values)
        valve = self.valve.evaluate(_at(boundary.command, t), _at(boundary.supply_pressure_pa, t), _at(boundary.return_pressure_pa, t), p1, p2)
        return self.cylinder.rhs(values, -valve.port_flows_into_valve_m3_s["A"], -valve.port_flows_into_valve_m3_s["B"], _at(boundary.displacement_m, t), _at(boundary.velocity_mps, t))

