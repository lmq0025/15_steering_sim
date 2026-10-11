from __future__ import annotations

from dataclasses import dataclass
import math
from scipy.optimize import brentq

from .parameters import ChannelParameters, SC1ValveParameters
from .valve import (ValveFlows, compile_sc1_valve, four_way_flows, opening,
                    sc1_four_port_flows, sc1_four_port_flows_compiled,
                    sc1_four_port_flows_compiled_with_derivatives)


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
    solver_method: str = "reference"
    fallback_used: bool = False
    network_evaluations: int = 0
    capacity_margin: float = 0.0
    capacity_insufficient: bool = False


class SupplyConvergenceError(RuntimeError):
    pass


@dataclass
class FastSupplyWorkspace:
    """Warm numerical state for one algebraic supply group.

    These values are numerical guesses and diagnostics only.  They are not
    hydraulic states and never alter the 16-state physical model.
    """

    low_pressure: float | None = None
    relief_high_pressure: float | None = None
    return_derivative: float | None = None
    regulator_scale: float = 1.0
    calls: int = 0
    predictor_accepts: int = 0
    correction_iterations: int = 0
    fallbacks: int = 0
    network_evaluations: int = 0
    inner_iterations: int = 0
    max_abs_return_residual: float = 0.0
    compiled_valves: tuple[tuple[tuple[int, int, int, int, float], ...], ...] | None = None

    def diagnostics(self) -> dict[str, float | int]:
        return {
            "calls": self.calls,
            "predictor_accepts": self.predictor_accepts,
            "correction_iterations": self.correction_iterations,
            "fallbacks": self.fallbacks,
            "network_evaluations": self.network_evaluations,
            "inner_iterations": self.inner_iterations,
            "max_abs_return_residual_m3_s": self.max_abs_return_residual,
        }


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


# Public numerical-reference name used by Phase L1-S1 regression tests.  The
# function above is intentionally retained unchanged as the trusted fallback.
solve_supply_reference = solve_sc1_load_sensing_network


def solve_regulated_constant_pressure(
        q_pump: float, commands: list[float], p_a: list[float], p_b: list[float],
        channels: list[ChannelParameters], valves: list[SC1ValveParameters]
        ) -> SharedSupplySolution:
    """Evaluate the L1-Fast regulated-source boundary without a root solve.

    The pump-outlet sensor, SC_1 high rail, and SC_1 return rail remain
    distinct quantities.  The fixed rail values are transferred from the
    verified S0 normal working point.  This function never clips chamber
    pressure and never invents flow when pump capacity is insufficient.
    """
    supply = channels[0].supply
    p_low = supply.regulated_return_rail_pressure
    flows: list[ValveFlows] = []
    t_rails: list[float] = []
    for alias, command, pa, pb, valve in zip(
            (v.alias for v in valves), commands, p_a, p_b, valves):
        # J0-R1 F2 修正：dirvalve_6 原被单独处理成 local_pa = p_high（SC_1 的 A 口
        # 挂在高压轨上、不接缸腔），与后三只主阀不同构，也是 F2 的一部分。
        # 按 IR V3 的工作口换位证据，前阀与后三只主阀统一按同一支路处理。
        if alias in {"dirvalve_6", "dirvalve_1", "dirvalve_8", "dirvalve_11"}:
            p_high = supply.regulated_high_rail_pressure
            local_pa, local_pb = pa, pb
        else:
            # The redundant two-orifice wrappers have P and T on the return
            # rail in IR V3/R3; they are not fed from the regulated high rail.
            p_high = p_low
            local_pa, local_pb = pa, pb
        vf = sc1_four_port_flows_compiled(
            command, p_low, p_high, local_pa, local_pb,
            compile_sc1_valve(valve))
        flows.append(vf)
        t_rails.append(p_high)

    high_rail_demand = sum(-vf.q_return for vf in flows)
    total_demand = high_rail_demand + supply.auxiliary_flow
    margin = q_pump - total_demand
    relief = max(margin, 0.0)
    deficit = max(-margin, 0.0)
    # When there is no deficit the residual closes exactly through the ideal
    # regulator/relief boundary.  A deficit is deliberately exposed rather
    # than hidden by an algebraic pressure adjustment.
    residual = q_pump - total_demand - relief
    scale = max(abs(q_pump), abs(total_demand), 1.0e-12)
    return SharedSupplySolution(
        pressure=supply.regulated_pump_outlet_pressure,
        relief_flow=relief, valve_flows=tuple(flows), pump_flow=q_pump,
        valve_supply_flow=high_rail_demand,
        other_branch_flow=supply.auxiliary_flow,
        residual=residual, relative_residual=abs(residual) / scale,
        converged=True, iterations=0,
        pump_outlet_pressure=supply.regulated_pump_outlet_pressure,
        manifold_residual=-deficit, relief_node_residual=-deficit,
        return_node_residual=0.0,
        valve_p_pressures=tuple(p_low for _ in flows),
        valve_t_pressures=tuple(t_rails),
        solver_method="regulated_constant_pressure", fallback_used=False,
        network_evaluations=1, capacity_margin=margin,
        capacity_insufficient=deficit > max(1.0e-9, abs(q_pump) * 1.0e-3),
    )


def solve_supply_fast(q_pump: float, commands: list[float],
                      p_a: list[float], p_b: list[float],
                      channels: list[ChannelParameters],
                      valves: list[SC1ValveParameters],
                      workspace: FastSupplyWorkspace | None = None,
                      use_analytic: bool = True
                      ) -> SharedSupplySolution:
    """Warm-started predictor/corrector for the unchanged R3 network.

    The original solver repeatedly rebuilt the same four-port flows for a
    centred finite-difference derivative.  This implementation reuses the
    previous local derivative and high-rail solution, validates every returned
    node residual, and falls back to the retained reference solver whenever a
    safe correction cannot be established.
    """
    ws = workspace if workspace is not None else FastSupplyWorkspace()
    ws.calls += 1
    supply = channels[0].supply
    aliases = tuple(v.alias for v in valves)
    relief_count = len(channels[0].pump_aliases)
    available = q_pump - supply.auxiliary_flow
    flow_tolerance = max(1.0e-9, abs(q_pump) * 1.0e-6)
    lo = supply.tank_pressure - 101_325.0
    hi = 5.0e6
    if ws.compiled_valves is None:
        ws.compiled_valves = tuple(compile_sc1_valve(valve) for valve in valves)
    compiled_valves = ws.compiled_valves

    def analytic_build(p_low: float, relief_high: float
                       ) -> tuple[list[ValveFlows], list[float], float, float,
                                  float, float, float, float, float]:
        flows: list[ValveFlows] = []
        t_rails: list[float] = []
        high_draw = ddraw_low = ddraw_high = 0.0
        supply_flow = dsupply_low = dsupply_high = 0.0
        for alias, command, pa, pb, compiled in zip(
                aliases, commands, p_a, p_b, compiled_valves):
            if alias == "dirvalve_6":
                pt = relief_high + supply.valve_feed_resistance * q_pump
                local_pa, local_pb = pt, pb
                dlow = (1.0, 0.0, 0.0, 0.0)
                dhigh = (0.0, 1.0, 1.0, 0.0)
            elif alias in {"dirvalve_1", "dirvalve_8", "dirvalve_11"}:
                pt = pa + supply.reducing_valve_margin
                local_pa, local_pb = pa, pb
                dlow = (1.0, 0.0, 0.0, 0.0)
                dhigh = (0.0, 0.0, 0.0, 0.0)
            else:
                pt = p_low
                local_pa, local_pb = pa, pb
                dlow = (1.0, 1.0, 0.0, 0.0)
                dhigh = (0.0, 0.0, 0.0, 0.0)
            item = sc1_four_port_flows_compiled_with_derivatives(
                command, (p_low, pt, local_pa, local_pb), dlow, dhigh,
                compiled)
            vf, dqs_low, dqs_high, dqr_low, dqr_high = item
            flows.append(vf)
            t_rails.append(pt)
            supply_flow += vf.q_supply
            dsupply_low += dqs_low
            dsupply_high += dqs_high
            draw = -vf.q_return
            if draw > 0.0:
                high_draw += draw
                ddraw_low -= dqr_low
                ddraw_high -= dqr_high
        return (flows, t_rails, high_draw, ddraw_low, ddraw_high,
                supply_flow, dsupply_low, dsupply_high, 1.0)

    # Normal operating region: solve the return and relief equations together
    # with an analytic 2x2 Jacobian.  Regulator droop is uncommon and remains
    # on the safeguarded scalar path below.
    direct_low = float(ws.low_pressure if ws.low_pressure is not None
                       else supply.return_path_resistance * q_pump)
    direct_high = float(ws.relief_high_pressure if ws.relief_high_pressure is not None
                        else direct_low + supply.relief_cracking_pressure)
    direct_low = min(max(direct_low, lo), hi)
    direct_ok = False
    direct_data = None
    direct_iterations = 0
    total_relief_conductance = relief_count * supply.relief_conductance
    for direct_iterations in range(1, 7) if use_analytic else ():
        direct_data = analytic_build(direct_low, direct_high)
        ws.network_evaluations += 1
        ws.inner_iterations += 1
        (direct_flows, direct_t, direct_draw, ddraw_low, ddraw_high,
         direct_supply, dsupply_low, dsupply_high, _) = direct_data
        # HYDPRV0 droop requires a third unknown.  Preserve the old safeguarded
        # path for that switching region rather than returning an approximation.
        if direct_draw > available + flow_tolerance:
            break
        direct_qr = total_relief_conductance * (
            direct_high - direct_low - supply.relief_cracking_pressure)
        if direct_qr < -flow_tolerance:
            break
        f_high = direct_qr - (q_pump - direct_draw - supply.auxiliary_flow)
        f_return = (direct_qr + supply.auxiliary_flow - direct_supply
                    - (direct_low - supply.tank_pressure) /
                    supply.return_path_resistance)
        if max(abs(f_high), abs(f_return)) <= flow_tolerance:
            direct_ok = True
            break
        a11 = -total_relief_conductance + ddraw_low
        a12 = total_relief_conductance + ddraw_high
        a21 = (-total_relief_conductance - dsupply_low
               - 1.0 / supply.return_path_resistance)
        a22 = total_relief_conductance - dsupply_high
        determinant = a11 * a22 - a12 * a21
        if not math.isfinite(determinant) or abs(determinant) < 1.0e-30:
            break
        delta_low = (-f_high * a22 + a12 * f_return) / determinant
        delta_high = (-a11 * f_return + a21 * f_high) / determinant
        candidate_low = direct_low + delta_low
        candidate_high = direct_high + delta_high
        if (not math.isfinite(candidate_low) or not math.isfinite(candidate_high)
                or candidate_low <= lo or candidate_low >= hi
                or candidate_high <= candidate_low):
            break
        direct_low, direct_high = candidate_low, candidate_high
        ws.correction_iterations += 1

    if direct_ok and direct_data is not None:
        direct_qr = total_relief_conductance * (
            direct_high - direct_low - supply.relief_cracking_pressure)
        direct_qr = max(direct_qr, 0.0)
        direct_return_flow = (direct_qr + supply.auxiliary_flow
                              - direct_data[5])
        direct_balance = (q_pump - direct_data[2]
                          - supply.auxiliary_flow - direct_qr)
        direct_return_residual = (direct_return_flow
            - (direct_low - supply.tank_pressure) /
            supply.return_path_resistance)
        pump_outlet = (direct_high + supply.path_resistance * q_pump /
                       max(relief_count, 1))
        if (abs(direct_balance) <= flow_tolerance
                and abs(direct_return_residual) <= 1.0e-9):
            ws.low_pressure = direct_low
            ws.relief_high_pressure = direct_high
            ws.max_abs_return_residual = max(
                ws.max_abs_return_residual, abs(direct_return_residual))
            return SharedSupplySolution(
                pressure=direct_high, relief_flow=direct_qr,
                valve_flows=tuple(direct_data[0]), pump_flow=q_pump,
                valve_supply_flow=direct_data[2],
                other_branch_flow=supply.auxiliary_flow,
                residual=direct_balance,
                relative_residual=abs(direct_balance) /
                    max(abs(q_pump), 1.0e-12),
                converged=True, iterations=direct_iterations,
                pump_outlet_pressure=pump_outlet,
                manifold_residual=direct_balance,
                relief_node_residual=direct_balance,
                return_node_residual=direct_return_residual,
                valve_p_pressures=tuple(direct_low for _ in direct_data[0]),
                valve_t_pressures=tuple(direct_data[1]),
                solver_method="fast_analytic", fallback_used=False,
                network_evaluations=direct_iterations)

    def build(p_low: float, regulator_scale: float, relief_high: float
              ) -> tuple[list[ValveFlows], list[float], float]:
        candidate_flows: list[ValveFlows] = []
        candidate_t: list[float] = []
        candidate_draw = 0.0
        for alias, command, pa, pb, compiled in zip(
                aliases, commands, p_a, p_b, compiled_valves):
            if alias == "dirvalve_6":
                pt = relief_high + supply.valve_feed_resistance * q_pump
                local_pa, local_pb = pt, pb
            elif alias in {"dirvalve_1", "dirvalve_8", "dirvalve_11"}:
                pt = pa + regulator_scale * supply.reducing_valve_margin
                local_pa, local_pb = pa, pb
            else:
                pt = p_low
                local_pa, local_pb = pa, pb
            vf = sc1_four_port_flows_compiled(
                command, p_low, pt, local_pa, local_pb, compiled)
            candidate_flows.append(vf)
            candidate_t.append(pt)
            candidate_draw += max(-vf.q_return, 0.0)
        return candidate_flows, candidate_t, candidate_draw

    def network_at_low_fast(p_low: float, high_guess: float | None,
                            scale_guess: float
                            ) -> tuple[list[ValveFlows], list[float], float, float,
                                       float, float, float, int]:
        relief_high = (high_guess if high_guess is not None else
                       p_low + supply.relief_cracking_pressure)
        regulator_scale = min(1.0, max(0.0, scale_guess))
        inner = 0
        flows: list[ValveFlows] = []
        t_rails: list[float] = []
        high_draw = 0.0
        for inner in range(1, 13):
            flows, t_rails, high_draw = build(p_low, regulator_scale, relief_high)
            if high_draw > available:
                zero_draw = build(p_low, 0.0, relief_high)[2]
                if zero_draw > available + flow_tolerance:
                    raise SupplyConvergenceError(
                        f"minimum valve demand {zero_draw + supply.auxiliary_flow:.9g} "
                        f"exceeds pump flow {q_pump:.9g}")
                regulator_scale = brentq(
                    lambda factor: build(p_low, factor, relief_high)[2] - available,
                    0.0, 1.0, xtol=1.0e-10, rtol=1.0e-12, maxiter=60)
                flows, t_rails, high_draw = build(
                    p_low, regulator_scale, relief_high)
            else:
                regulator_scale = 1.0
            qr = max(q_pump - high_draw - supply.auxiliary_flow, 0.0)
            updated = (p_low + supply.relief_cracking_pressure
                       + qr / max(relief_count * supply.relief_conductance, 1.0e-30))
            if abs(updated - relief_high) <= 1.0e-3:
                relief_high = updated
                break
            relief_high = updated
        # Re-evaluate once at the accepted high rail only if the last update
        # changed it materially.  This makes the returned flows and pressures
        # correspond to the same algebraic point.
        flows, t_rails, high_draw = build(
            p_low, regulator_scale, relief_high)
        if high_draw > available:
            regulator_scale = brentq(
                lambda factor: build(p_low, factor, relief_high)[2] - available,
                0.0, 1.0, xtol=1.0e-10, rtol=1.0e-12, maxiter=60)
            flows, t_rails, high_draw = build(
                p_low, regulator_scale, relief_high)
        qr = max(q_pump - high_draw - supply.auxiliary_flow, 0.0)
        return_flow = qr + supply.auxiliary_flow - sum(v.q_supply for v in flows)
        pressure_residual = (p_low - supply.tank_pressure
                             - supply.return_path_resistance * return_flow)
        return (flows, t_rails, high_draw, qr, return_flow, pressure_residual,
                regulator_scale, inner)

    evaluations = 0
    high_guess = ws.relief_high_pressure
    scale_guess = ws.regulator_scale

    def evaluate_low(p_low: float):
        nonlocal evaluations, high_guess, scale_guess
        result = network_at_low_fast(p_low, high_guess, scale_guess)
        evaluations += 1
        high_guess = p_low + supply.relief_cracking_pressure + result[3] / max(
            relief_count * supply.relief_conductance, 1.0e-30)
        scale_guess = result[6]
        ws.inner_iterations += result[7]
        return result

    p0 = float(ws.low_pressure if ws.low_pressure is not None
               else supply.return_path_resistance * q_pump)
    p0 = min(max(p0, lo), hi)
    result0 = evaluate_low(p0)
    r0 = result0[5]
    accepted = abs(r0) / supply.return_path_resistance <= 1.0e-9
    final_result = result0
    p_low = p0
    iterations = 0

    if accepted:
        ws.predictor_accepts += 1
    else:
        derivative = ws.return_derivative
        previous_p, previous_r = p0, r0
        for iterations in range(1, 9):
            if derivative is None or not math.isfinite(derivative) or abs(derivative) < 1.0e-8:
                # One centred difference seeds the derivative.  Subsequent
                # calls normally use the stored derivative and skip this path.
                step = max(10.0, abs(previous_p) * 1.0e-5)
                low_probe_p = max(previous_p - step, lo)
                high_probe_p = min(previous_p + step, hi)
                low_probe = evaluate_low(low_probe_p)
                high_probe = evaluate_low(high_probe_p)
                derivative = ((high_probe[5] - low_probe[5]) /
                              (high_probe_p - low_probe_p))
            candidate = previous_p - previous_r / derivative
            if not math.isfinite(candidate) or candidate <= lo or candidate >= hi:
                derivative = None
                continue
            candidate_result = evaluate_low(candidate)
            candidate_r = candidate_result[5]
            ws.correction_iterations += 1
            if abs(candidate_r) / supply.return_path_resistance <= 1.0e-9:
                p_low, final_result, accepted = candidate, candidate_result, True
                if candidate != previous_p:
                    ws.return_derivative = (candidate_r - previous_r) / (candidate - previous_p)
                break
            if candidate != previous_p:
                secant = (candidate_r - previous_r) / (candidate - previous_p)
                if math.isfinite(secant) and abs(secant) >= 1.0e-8:
                    derivative = secant
            previous_p, previous_r = candidate, candidate_r

    if not accepted:
        ws.fallbacks += 1
        reference = solve_supply_reference(
            q_pump, commands, p_a, p_b, channels, valves, p0)
        ws.low_pressure = (reference.valve_p_pressures[0]
                           if reference.valve_p_pressures else p0)
        ws.relief_high_pressure = reference.pressure
        ws.network_evaluations += evaluations
        return SharedSupplySolution(
            **{**reference.__dict__, "solver_method": "reference_fallback",
               "fallback_used": True, "network_evaluations": evaluations})

    flows, t_rails, high_draw, qr, return_flow, pressure_residual, scale, _ = final_result
    relief_node = (p_low + supply.relief_cracking_pressure
                   + qr / max(relief_count * supply.relief_conductance, 1.0e-30))
    pump_outlet = relief_node + supply.path_resistance * q_pump / max(relief_count, 1)
    balance = q_pump - high_draw - supply.auxiliary_flow - qr
    return_residual_value = (return_flow
        - (p_low - supply.tank_pressure) / supply.return_path_resistance)
    if (abs(balance) > flow_tolerance or abs(return_residual_value) > 1.0e-9
            or not all(math.isfinite(v) for v in (p_low, relief_node, pump_outlet))):
        ws.fallbacks += 1
        reference = solve_supply_reference(
            q_pump, commands, p_a, p_b, channels, valves, p0)
        ws.low_pressure = reference.valve_p_pressures[0]
        ws.relief_high_pressure = reference.pressure
        ws.network_evaluations += evaluations
        return SharedSupplySolution(
            **{**reference.__dict__, "solver_method": "reference_fallback",
               "fallback_used": True, "network_evaluations": evaluations})

    ws.low_pressure = p_low
    ws.relief_high_pressure = relief_node
    ws.regulator_scale = scale
    ws.network_evaluations += evaluations
    ws.max_abs_return_residual = max(
        ws.max_abs_return_residual, abs(return_residual_value))
    return SharedSupplySolution(
        pressure=relief_node, relief_flow=qr, valve_flows=tuple(flows),
        pump_flow=q_pump, valve_supply_flow=high_draw,
        other_branch_flow=supply.auxiliary_flow, residual=balance,
        relative_residual=abs(balance) / max(abs(q_pump), 1.0e-12),
        converged=True, iterations=iterations,
        pump_outlet_pressure=pump_outlet, manifold_residual=balance,
        relief_node_residual=balance,
        return_node_residual=return_residual_value,
        valve_p_pressures=tuple(p_low for _ in flows),
        valve_t_pressures=tuple(t_rails), solver_method="fast",
        fallback_used=False, network_evaluations=evaluations)


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
