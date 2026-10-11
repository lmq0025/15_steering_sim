from __future__ import annotations

from dataclasses import dataclass
import math
from scipy.optimize import brentq

from .parameters import ChannelParameters, SC1ValveParameters
from .valve import ValveFlows, four_way_flows, opening, sc1_four_port_flows


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
    pump_outlet_pressure: float | None = None
    manifold_residual: float = 0.0
    relief_node_residual: float = 0.0
    return_node_residual: float = 0.0
    valve_p_pressures: tuple[float, ...] = ()
    valve_t_pressures: tuple[float, ...] = ()


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


def solve_sc1_shared_supply(q_pump: float, commands: list[float], p_a: list[float],
                            p_b: list[float], channels: list[ChannelParameters],
                            valves: list[SC1ValveParameters],
                            spatial_path: bool = True) -> SharedSupplySolution:
    """Solve an SC_1 manifold with independent bidirectional orifice branches.

    In the spatial R3 representation the relief valve senses the manifold;
    the transferred/identified path loss is applied only when reporting pump
    outlet pressure.  It is not incorrectly placed in series with relief flow.
    """
    supply = channels[0].supply
    relief_count = len(channels[0].pump_aliases)

    def values(pm: float) -> tuple[float, float, list[ValveFlows]]:
        flows = [sc1_four_port_flows(u, pm, c.supply.tank_pressure, pa, pb, valve)
                 for u, pa, pb, c, valve in zip(commands, p_a, p_b, channels, valves)]
        if spatial_path:
            qr = relief_count * supply.relief_conductance * max(
                pm - supply.relief_cracking_pressure, 0.0)
        else:
            reff = supply.path_resistance + 1.0 / supply.relief_conductance
            qr = relief_count * max(pm - supply.relief_cracking_pressure, 0.0) / reff
        residual = sum(v.q_supply for v in flows) + qr - q_pump
        return residual, qr, flows

    lo = supply.tank_pressure - 101_325.0
    rlo, _, _ = values(lo)
    hi = max(supply.relief_cracking_pressure + 1.0e6,
             max(p_a + p_b + [0.0]) + 1.0e6)
    rhi, _, _ = values(hi)
    expansions = 0
    while rhi < 0.0 and expansions < 30:
        hi = max(2.0 * hi, hi + 1.0e6)
        rhi, _, _ = values(hi)
        expansions += 1
    if rlo > 0.0 or rhi < 0.0:
        raise SupplyConvergenceError(
            f"could not bracket SC_1 manifold root: q_pump={q_pump:.9g}, "
            f"residual_lo={rlo:.9g}, residual_hi={rhi:.9g}, hi={hi:.9g}")
    pm, root_info = brentq(lambda pressure: values(pressure)[0], lo, hi,
                           xtol=1.0e-3, rtol=1.0e-12, maxiter=80,
                           full_output=True, disp=False)
    residual, qr, flows = values(pm)
    valve_flow = sum(v.q_supply for v in flows)
    scale = max(abs(q_pump), abs(valve_flow) + abs(qr), 1.0e-12)
    tolerance = max(1.0e-9, abs(q_pump) * 1.0e-6)
    if abs(residual) > tolerance:
        raise SupplyConvergenceError(
            f"SC_1 manifold residual {residual:.9g} m3/s after {root_info.iterations} iterations")
    # The two ideal displacement pumps have separate outlet paths and equal
    # healthy baseline flow.  R_eq was identified between a pump outlet sensor
    # and the downstream manifold, so it acts on one pump's path flow.
    path_flow = q_pump / max(relief_count, 1)
    pump_outlet = pm + supply.path_resistance * path_flow if spatial_path else pm
    return SharedSupplySolution(
        pressure=pm, relief_flow=qr, valve_flows=tuple(flows), pump_flow=q_pump,
        valve_supply_flow=valve_flow, other_branch_flow=0.0,
        residual=residual, relative_residual=abs(residual) / scale,
        converged=True, iterations=int(root_info.iterations),
        pump_outlet_pressure=pump_outlet, manifold_residual=residual,
        relief_node_residual=0.0,
        return_node_residual=sum(v.q_return for v in flows) + qr,
    )


def solve_sc1_load_sensing_network(q_pump: float, commands: list[float],
                                   p_a: list[float], p_b: list[float],
                                   channels: list[ChannelParameters],
                                   valves: list[SC1ValveParameters],
                                   initial_low_pressure: float | None = None) -> SharedSupplySolution:
    """Minimal R3 algebraic network matching the installed reverse-fed SC_1s.

    Amesim port evidence shows that local T is the high rail and local P is
    the return rail.  Rear primary T rails are supplied through HYDPRV0 load-
    sensing reducers (p3-pilot ~= pmin=10 bar).  The P return pressure is
    solved from the transferred path resistance; no hydraulic state is added.
    """
    supply = channels[0].supply
    aliases = [v.alias for v in valves]
    relief_count = len(channels[0].pump_aliases)

    def network_at_low(p_low: float) -> tuple[list[ValveFlows], list[float], float, float, float]:
        # Front T is upstream of the main relief.  Iterate its algebraic value;
        # rear T rails are independent HYDPRV0 downstream nodes.
        relief_high = p_low + supply.relief_cracking_pressure
        flows: list[ValveFlows] = []
        t_rails: list[float] = []
        high_draw = 0.0
        def build(regulator_scale: float, front_relief_high: float
                  ) -> tuple[list[ValveFlows], list[float], float]:
            candidate_flows: list[ValveFlows] = []
            candidate_t: list[float] = []
            candidate_draw = 0.0
            for alias, command, pa, pb, channel, valve in zip(
                    aliases, commands, p_a, p_b, channels, valves):
                if alias == "dirvalve_6":
                    pt = front_relief_high + supply.valve_feed_resistance * q_pump
                    # External variableorifice is closed: local A is isolated
                    # from HJ021 chamber 1 and follows the upstream T node.
                    local_pa, local_pb = pt, pb
                elif alias in {"dirvalve_1", "dirvalve_8", "dirvalve_11"}:
                    # pprv pilot is local A; p3-p2 lies in [pmin,pmin+padd].
                    pt = pa + regulator_scale * supply.reducing_valve_margin
                    local_pa, local_pb = pa, pb
                else:
                    pt = p_low
                    local_pa, local_pb = pa, pb
                vf = sc1_four_port_flows(command, p_low, pt, local_pa, local_pb, valve)
                candidate_flows.append(vf)
                candidate_t.append(pt)
                candidate_draw += max(-vf.q_return, 0.0)
            return candidate_flows, candidate_t, candidate_draw

        for _ in range(4):
            flows, t_rails, high_draw = build(1.0, relief_high)
            available = q_pump - supply.auxiliary_flow
            if high_draw > available:
                # When the pumps cannot maintain pmin+padd the pressure reducer
                # droops; solve its common opening margin instead of returning
                # a false high-pressure solution or hard clipping pressure.
                zero_draw = build(0.0, relief_high)[2]
                if zero_draw > available + max(1e-9, abs(q_pump)*1e-6):
                    raise SupplyConvergenceError(
                        f"minimum valve demand {zero_draw + supply.auxiliary_flow:.9g} "
                        f"exceeds pump flow {q_pump:.9g}")
                scale = brentq(lambda factor: build(factor, relief_high)[2] - available,
                               0.0, 1.0, xtol=1e-10, rtol=1e-12, maxiter=60)
                flows, t_rails, high_draw = build(scale, relief_high)
            qr = q_pump - high_draw - supply.auxiliary_flow
            qr = max(qr, 0.0)
            updated = (p_low + supply.relief_cracking_pressure
                       + qr / max(relief_count * supply.relief_conductance, 1.0e-30))
            if abs(updated - relief_high) <= 1.0e-3:
                relief_high = updated
                break
            relief_high = updated
        # q_supply is P -> work.  Hence -sum(q_supply) is flow returned into P.
        return_flow = qr + supply.auxiliary_flow - sum(v.q_supply for v in flows)
        return flows, t_rails, high_draw, qr, return_flow

    def return_residual(p_low: float) -> float:
        _, _, _, _, return_flow = network_at_low(p_low)
        return p_low - supply.tank_pressure - supply.return_path_resistance * return_flow

    lo, hi = supply.tank_pressure - 101_325.0, 5.0e6
    p_low = min(max(float(initial_low_pressure if initial_low_pressure is not None
                          else supply.return_path_resistance * q_pump), lo), hi)
    iterations = 0
    converged_root = False
    # Warm-started safeguarded Newton.  The low-return node is local and
    # changes smoothly between RK stages; this avoids a cold Brent solve in
    # every RHS call while retaining an explicit residual gate and fallback.
    for iterations in range(1, 7):
        value = return_residual(p_low)
        if abs(value) / supply.return_path_resistance <= 1.0e-9:
            converged_root = True
            break
        step = max(10.0, abs(p_low) * 1.0e-5)
        derivative = (return_residual(min(p_low + step, hi))
                      - return_residual(max(p_low - step, lo))) / (2.0 * step)
        if not math.isfinite(derivative) or abs(derivative) < 1.0e-8:
            break
        candidate = p_low - value / derivative
        if not math.isfinite(candidate) or candidate <= lo or candidate >= hi:
            break
        p_low = candidate
    if not converged_root:
        flo, fhi = return_residual(lo), return_residual(hi)
        while fhi < 0.0 and hi < 100.0e6:
            hi *= 2.0
            fhi = return_residual(hi)
        if flo > 0.0 or fhi < 0.0:
            raise SupplyConvergenceError(
                f"could not bracket SC_1 return node: residual_lo={flo:.9g}, "
                f"residual_hi={fhi:.9g}")
        p_low, root_info = brentq(return_residual, lo, hi, xtol=1.0e-3,
                                 rtol=1.0e-12, maxiter=80, full_output=True,
                                 disp=False)
        iterations += int(root_info.iterations)
    flows, t_rails, high_draw, qr, return_flow = network_at_low(p_low)
    relief_node = (p_low + supply.relief_cracking_pressure
                   + qr / max(relief_count * supply.relief_conductance, 1.0e-30))
    pump_outlet = relief_node + supply.path_resistance * q_pump / max(relief_count, 1)
    balance = q_pump - high_draw - supply.auxiliary_flow - qr
    return_residual_value = (return_flow
        - (p_low - supply.tank_pressure) / supply.return_path_resistance)
    return SharedSupplySolution(
        pressure=relief_node, relief_flow=qr, valve_flows=tuple(flows),
        pump_flow=q_pump, valve_supply_flow=high_draw,
        other_branch_flow=supply.auxiliary_flow,
        residual=balance, relative_residual=abs(balance) / max(abs(q_pump), 1e-12),
        converged=abs(balance) <= max(1e-9, abs(q_pump)*1e-6),
        iterations=iterations, pump_outlet_pressure=pump_outlet,
        manifold_residual=balance, relief_node_residual=balance,
        return_node_residual=return_residual_value,
        valve_p_pressures=tuple(p_low for _ in flows),
        valve_t_pressures=tuple(t_rails),
    )


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
