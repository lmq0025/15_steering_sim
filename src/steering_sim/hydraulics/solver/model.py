from __future__ import annotations

from dataclasses import dataclass
import numpy as np
from numpy.typing import NDArray
from scipy.integrate import solve_ivp

from ..elements.cylinder import DoubleActingCylinder
from ..elements.line import ComplianceLine
from ..elements.pump import PU001
from ..elements.restriction import FixedOrifice


@dataclass(frozen=True, slots=True)
class SimulationResult:
    time_s: NDArray[np.float64]
    state: NDArray[np.float64]
    success: bool
    message: str


@dataclass(frozen=True, slots=True)
class MinimalHydraulicLoop:
    pump: PU001
    angular_speed_rad_s: float
    line: ComplianceLine
    return_restriction: FixedOrifice
    tank_pressure_pa: float

    def rhs(self, _t: float, y: NDArray[np.float64]) -> NDArray[np.float64]:
        p = float(y[0])
        q_pump = self.pump.flow_m3_s(self.angular_speed_rad_s, self.tank_pressure_pa)
        q_return = self.return_restriction.flow_m3_s(p, self.tank_pressure_pa)
        return np.array([self.line.pressure_rhs_pa_s(q_pump - q_return)])

    def simulate(self, duration_s: float, initial_pressure_pa: float) -> SimulationResult:
        sol = solve_ivp(self.rhs, (0.0, duration_s), [initial_pressure_pa], method="BDF", rtol=1e-7, atol=1e-4)
        return SimulationResult(sol.t, sol.y, sol.success, sol.message)


@dataclass(frozen=True, slots=True)
class ActuatorLoop:
    cylinder: DoubleActingCylinder
    supply_orifice: FixedOrifice
    return_orifice: FixedOrifice
    supply_pressure_pa: float
    tank_pressure_pa: float
    mass_kg: float
    load_force_n: float = 0.0

    def rhs(self, _t: float, y: NDArray[np.float64]) -> NDArray[np.float64]:
        p1, p2, x, v = map(float, y)
        q1 = self.supply_orifice.flow_m3_s(self.supply_pressure_pa, p1)
        q_return = self.return_orifice.flow_m3_s(p2, self.tank_pressure_pa)
        dp1, dp2 = self.cylinder.pressure_rhs_pa_s(p1, p2, q1, -q_return, x, v)
        force = self.cylinder.force_n(p1, p2, v, x)
        return np.array([dp1, dp2, v, (force - self.load_force_n) / self.mass_kg])

    def simulate(self, duration_s: float, initial_state: NDArray[np.float64]) -> SimulationResult:
        # Stop before leaving the physical stroke; Phase 1 does not model end-stop events.
        def lower(_t, y): return y[2]
        def upper(_t, y): return self.cylinder.stroke_m - y[2]
        lower.terminal = upper.terminal = True
        lower.direction = upper.direction = -1
        sol = solve_ivp(self.rhs, (0.0, duration_s), np.asarray(initial_state, dtype=float), method="BDF", rtol=1e-6, atol=np.array([1e-2, 1e-2, 1e-9, 1e-8]), events=(lower, upper), max_step=max(duration_s / 100.0, 1e-6))
        return SimulationResult(sol.t, sol.y, sol.success, sol.message)
