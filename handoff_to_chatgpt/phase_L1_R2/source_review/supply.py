from __future__ import annotations

from dataclasses import dataclass
import math
from scipy.optimize import brentq

from .parameters import ChannelParameters
from .valve import ValveFlows, four_way_flows, opening


@dataclass(frozen=True)
class SupplySolution:
    pressure: float
    relief_flow: float
    valve_flows: ValveFlows


@dataclass(frozen=True)
class SharedSupplySolution:
    pressure: float
    relief_flow: float
    valve_flows: tuple[ValveFlows, ...]
    pump_flow: float
    valve_supply_flow: float
    other_branch_flow: float
    residual: float
    relative_residual: float
    converged: bool
    iterations: int


class SupplyConvergenceError(RuntimeError):
    pass


def solve_shared_supply(q_pump: float, commands: list[float], p_a: list[float], p_b: list[float],
                        channels: list[ChannelParameters]) -> SharedSupplySolution:
    """Solve one shared supply junction without adding a hydraulic state."""
    supply = channels[0].supply
    reff = supply.path_resistance + 1.0 / supply.relief_conductance

    relief_count = len(channels[0].pump_aliases)

    def values(ps: float) -> tuple[float, float, list[ValveFlows]]:
        flows = [four_way_flows(u, ps, c.supply.tank_pressure, pa, pb, c.valve, c.fluid)
                 for u, pa, pb, c in zip(commands, p_a, p_b, channels)]
        # The frozen network has one pressure-control branch per parallel PU001.
        qr = relief_count * max(ps - supply.relief_cracking_pressure, 0.0) / reff
        return sum(v.q_supply for v in flows) + qr - q_pump, qr, flows

    def result_at(ps: float, iterations: int) -> SharedSupplySolution:
        residual, qr, flows = values(ps)
        valve_flow = sum(v.q_supply for v in flows)
        relative = abs(residual) / max(abs(q_pump), abs(valve_flow) + abs(qr), 1.0e-12)
        converged = abs(residual) <= max(1.0e-9, abs(q_pump) * 1.0e-6)
        if not converged:
            raise SupplyConvergenceError(
                f"supply solve residual {residual:.9g} m3/s after {iterations} iterations")
        return SharedSupplySolution(ps, qr, tuple(flows), q_pump, valve_flow, 0.0,
                                    residual, relative, True, iterations)

    areas = [opening(u, c.valve) for u, c in zip(commands, channels)]
    active = [i for i, area in enumerate(areas) if area > 0.0]
    if not active:
        ps = supply.relief_cracking_pressure + q_pump * reff / relief_count
        return result_at(ps, 0)
    if len(active) == 1:
        i = active[0]
        c, u = channels[i], commands[i]
        chamber = p_a[i] if u >= 0.0 else p_b[i]
        k = c.valve.discharge_coefficient * areas[i] * math.sqrt(2.0 / c.fluid.density)
        q_at_crack = k * math.sqrt(max(supply.relief_cracking_pressure - chamber, 0.0))
        reff_total = reff / relief_count
        if q_pump <= q_at_crack:
            ps = chamber + (q_pump / k) ** 2
        else:
            b = reff_total * k
            cc = chamber - supply.relief_cracking_pressure - reff_total * q_pump
            y = max(0.0, 0.5 * (-b + math.sqrt(max(b*b - 4.0*cc, 0.0))))
            ps = chamber + y*y
        return result_at(ps, 0)

    # Residual is monotone.  Bracket the physical root and use safeguarded
    # bisection: pressure bounds guide the search but are never returned as a
    # false solution.  A failed bracket or residual check is explicit.
    # Gauge pressure may transiently fall below tank pressure; the physical
    # lower search boundary is zero absolute pressure, not zero gauge.  This
    # is a bracket limit only and is never used as an output clamp.
    lo = supply.tank_pressure - 101_325.0
    rlo, _, _ = values(lo)
    hi = max(supply.relief_cracking_pressure + q_pump * reff / max(relief_count, 1),
             max(p_a + p_b + [0.0]) + 1.0e5, 1.0e5)
    rhi, _, _ = values(hi)
    expansions = 0
    while rhi < 0.0 and expansions < 20:
        hi *= 2.0
        rhi, _, _ = values(hi)
        expansions += 1
    if rlo > 0.0 or rhi < 0.0:
        raise SupplyConvergenceError(
            f"could not bracket supply root: q_pump={q_pump:.9g}, "
            f"residual_lo={rlo:.9g}, residual_hi={rhi:.9g}, hi={hi:.9g}")
    flow_tol = max(1.0e-9, abs(q_pump) * 1.0e-6)
    def scalar_residual(pressure: float) -> float:
        return values(pressure)[0]

    ps, root_info = brentq(scalar_residual, lo, hi, xtol=1.0e-3,
                           rtol=1.0e-12, maxiter=60, full_output=True,
                           disp=False)
    iterations = int(root_info.iterations)
    return result_at(ps, iterations)


def relief_flow(pressure: float, cracking_pressure: float, conductance: float) -> float:
    return conductance * max(pressure - cracking_pressure, 0.0)


def solve_supply(q_pump: float, command: float, p_a: float, p_b: float,
                 p: ChannelParameters) -> SupplySolution:
    # The active supply metering edge is one square-root restriction in parallel
    # with the relief path.  Substitution y=sqrt(ps-p_chamber) gives a quadratic,
    # avoiding an iterative algebraic solve in the simulation loop.
    g = p.supply.relief_conductance
    r = p.supply.path_resistance
    reff = r + 1.0 / g
    area = opening(command, p.valve)
    chamber = p_a if command >= 0.0 else p_b
    k = p.valve.discharge_coefficient * area * math.sqrt(2.0 / p.fluid.density)
    q_at_crack = k * math.sqrt(max(p.supply.relief_cracking_pressure - chamber, 0.0))
    if k > 0.0 and q_pump <= q_at_crack:
        ps = chamber + (q_pump / k) ** 2
        qr = 0.0
    elif k == 0.0:
        qr = max(q_pump, 0.0)
        ps = p.supply.relief_cracking_pressure + reff * qr
    else:
        # y^2 + reff*k*y + chamber-pcrack-reff*qp = 0
        b = reff * k
        c = chamber - p.supply.relief_cracking_pressure - reff * q_pump
        y = max(0.0, 0.5 * (-b + math.sqrt(max(b * b - 4.0 * c, 0.0))))
        ps = chamber + y * y
        qr = max((ps - p.supply.relief_cracking_pressure) / reff, 0.0)
    vf = four_way_flows(command, ps, p.supply.tank_pressure, p_a, p_b, p.valve, p.fluid)
    return SupplySolution(ps, qr, vf)
