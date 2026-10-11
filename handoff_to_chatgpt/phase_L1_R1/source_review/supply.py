from __future__ import annotations

from dataclasses import dataclass
import math

from .parameters import ChannelParameters
from .valve import ValveFlows, four_way_flows, opening


@dataclass(frozen=True)
class SupplySolution:
    pressure: float
    relief_flow: float
    valve_flows: ValveFlows


def solve_shared_supply(q_pump: float, commands: list[float], p_a: list[float], p_b: list[float],
                        channels: list[ChannelParameters]) -> tuple[float, float, list[ValveFlows]]:
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

    areas = [opening(u, c.valve) for u, c in zip(commands, channels)]
    if not any(areas):
        ps = supply.relief_cracking_pressure + q_pump * reff / relief_count
    elif len(channels) == 1:
        c = channels[0]; u = commands[0]
        chamber = p_a[0] if u >= 0.0 else p_b[0]
        k = c.valve.discharge_coefficient * areas[0] * math.sqrt(2.0 / c.fluid.density)
        q_at_crack = k * math.sqrt(max(supply.relief_cracking_pressure - chamber, 0.0))
        reff_total = reff / relief_count
        if q_pump <= q_at_crack:
            ps = chamber + (q_pump / k) ** 2
        else:
            b = reff_total * k
            cc = chamber - supply.relief_cracking_pressure - reff_total * q_pump
            y = max(0.0, 0.5 * (-b + math.sqrt(max(b*b - 4.0*cc, 0.0))))
            ps = chamber + y*y
    else:
        # Monotone Newton solve.  The derivative is assembled analytically from
        # the active square-root metering edges and linear relief branches.
        ps = supply.relief_cracking_pressure + q_pump * reff / relief_count
        for _ in range(8):
            residual, _, _ = values(ps)
            derivative = relief_count / reff if ps > supply.relief_cracking_pressure else 0.0
            for u, pa, pb, area, c in zip(commands, p_a, p_b, areas, channels):
                chamber = pa if u >= 0.0 else pb
                dp = ps - chamber
                if area > 0.0 and dp > 1.0:
                    k = c.valve.discharge_coefficient * area * math.sqrt(2.0 / c.fluid.density)
                    derivative += 0.5 * k / math.sqrt(dp)
            if derivative <= 0.0:
                break
            ps = min(100.0e6, max(0.0, ps - residual / derivative))
    _, qr, flows = values(ps)
    return ps, qr, flows


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
