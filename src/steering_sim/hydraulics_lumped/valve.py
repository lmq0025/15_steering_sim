from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

from .parameters import (FluidParameters, SC1OrificeParameters,
                         SC1ValveParameters, ValveParameters)


def signed_orifice_flow(p_up: float, p_down: float, area: float, cd: float, rho: float) -> float:
    dp = p_up - p_down
    if area <= 0.0 or dp == 0.0:
        return 0.0
    return cd * area * math.copysign(math.sqrt(2.0 * abs(dp) / rho), dp)


def opening(command: float, p: ValveParameters) -> float:
    u = max(-1.0, min(1.0, p.command_gain * command))
    magnitude = max(abs(u) - p.deadzone, 0.0) / max(1.0 - p.deadzone, 1e-12)
    return min(p.maximum_area, p.area_gradient * magnitude)


@dataclass(frozen=True)
class ValveFlows:
    q_a: float
    q_b: float
    q_supply: float
    opening: float
    q_pa: float = 0.0
    q_pb: float = 0.0
    q_at: float = 0.0
    q_bt: float = 0.0
    q_return: float = 0.0
    spool_position: float = 0.0


def four_way_flows(command: float, p_supply: float, p_tank: float, p_a: float, p_b: float,
                   valve: ValveParameters, fluid: FluidParameters) -> ValveFlows:
    area = opening(command, valve)
    if command >= 0.0:
        q_sa = max(signed_orifice_flow(p_supply, p_a, area, valve.discharge_coefficient, fluid.density), 0.0)
        q_bt = signed_orifice_flow(p_b, p_tank, area, valve.discharge_coefficient, fluid.density)
        return ValveFlows(q_a=q_sa, q_b=-q_bt, q_supply=q_sa, opening=area)
    q_sb = max(signed_orifice_flow(p_supply, p_b, area, valve.discharge_coefficient, fluid.density), 0.0)
    q_at = signed_orifice_flow(p_a, p_tank, area, valve.discharge_coefficient, fluid.density)
    return ValveFlows(q_a=-q_at, q_b=q_sb, q_supply=q_sb, opening=area)


def fractional_area_percent(spool: float, curve: str) -> float:
    """Evaluate the transferred SC_1 FX00 expressions, bounded to 0..100 %."""
    x = max(-1.0, min(1.0, spool))
    if curve == "ramp_minus_to_zero_then_full":
        value = 100.0 * (x + 1.0) if x <= 0.0 else 100.0
    elif curve == "full_to_zero_on_positive":
        value = 100.0 if x <= 0.0 else 100.0 * (1.0 - x)
    elif curve == "open_on_negative":
        value = -100.0 * x if x <= 0.0 else 0.0
    elif curve == "open_on_positive":
        value = 0.0 if x <= 0.0 else 100.0 * x
    elif curve == "positive_linear":
        value = 100.0 * x
    else:
        raise ValueError(f"unsupported SC_1 area curve {curve!r}")
    return max(0.0, min(100.0, value))


def characteristic_orifice_flow(p_from: float, p_to: float, fraction: float,
                                branch: SC1OrificeParameters) -> float:
    """Engineering reproduction of HYDVORF0 method 1 in its turbulent range.

    The law is symmetric: reverse pressure produces reverse flow.  A 1 Pa
    regularization removes the square-root derivative singularity without
    changing the engineering operating range.  ``orif3f_`` remains the exact
    low-flow equivalence boundary.
    """
    f = max(0.0, min(1.0, fraction))
    if f == 0.0:
        return 0.0
    dp = p_from - p_to
    eps = 1.0
    signed_root = dp / ((dp * dp + eps * eps) ** 0.25)
    return (f * branch.amesim_operating_range_scale * branch.q_characteristic
            * signed_root / math.sqrt(branch.dp_characteristic))


def sc1_four_port_flows(command: float, p_supply: float, p_tank: float,
                        p_a: float, p_b: float,
                        valve: SC1ValveParameters) -> ValveFlows:
    """Evaluate the actual independent P-A/P-B/A-T/B-T SC_1 branches."""
    spool = max(-1.0, min(1.0, command))
    flows = {"P-A": 0.0, "P-B": 0.0, "T-A": 0.0, "T-B": 0.0}
    pressures = {"P": p_supply, "T": p_tank, "A": p_a, "B": p_b}
    maximum_fraction = 0.0
    for branch in valve.orifices:
        fraction = fractional_area_percent(spool, branch.curve) / 100.0
        maximum_fraction = max(maximum_fraction, fraction)
        left, right = branch.branch.split("-")
        flows[branch.branch] = characteristic_orifice_flow(
            pressures[left], pressures[right], fraction, branch)
    q_pa, q_pb = flows["P-A"], flows["P-B"]
    # Stored T-A/T-B flows are oriented tank -> work port.  Positive chamber
    # inflow is therefore their direct sign; positive tank return is opposite.
    q_ta, q_tb = flows["T-A"], flows["T-B"]
    return ValveFlows(
        q_a=q_pa + q_ta,
        q_b=q_pb + q_tb,
        q_supply=q_pa + q_pb,
        opening=maximum_fraction * 20.0e-6,
        q_pa=q_pa, q_pb=q_pb, q_at=-q_ta, q_bt=-q_tb,
        q_return=-(q_ta + q_tb), spool_position=spool,
    )


_CURVE_CODE = {
    "ramp_minus_to_zero_then_full": 0,
    "full_to_zero_on_positive": 1,
    "open_on_negative": 2,
    "open_on_positive": 3,
    "positive_linear": 4,
}
_BRANCH_CODE = {"P-A": 0, "P-B": 1, "T-A": 2, "T-B": 3}
_PORT_CODE = {"P": 0, "T": 1, "A": 2, "B": 3}


@lru_cache(maxsize=16)
def compile_sc1_valve(valve: SC1ValveParameters) -> tuple[tuple[int, int, int, int, float], ...]:
    """Compile string metadata once for the numerical inner loop."""
    compiled = []
    for branch in valve.orifices:
        left, right = branch.branch.split("-")
        coefficient = (branch.amesim_operating_range_scale *
                       branch.q_characteristic / math.sqrt(branch.dp_characteristic))
        compiled.append((_BRANCH_CODE[branch.branch], _PORT_CODE[left],
                         _PORT_CODE[right], _CURVE_CODE[branch.curve], coefficient))
    return tuple(compiled)


def _fraction_from_code(spool: float, code: int) -> float:
    if code == 0:
        return spool + 1.0 if spool <= 0.0 else 1.0
    if code == 1:
        return 1.0 if spool <= 0.0 else 1.0 - spool
    if code == 2:
        return -spool if spool <= 0.0 else 0.0
    if code in (3, 4):
        return spool if spool > 0.0 else 0.0
    raise ValueError(f"unsupported compiled curve code {code}")


def sc1_four_port_flows_compiled(
        command: float, p_supply: float, p_tank: float, p_a: float, p_b: float,
        compiled: tuple[tuple[int, int, int, int, float], ...]) -> ValveFlows:
    """Allocation-light equivalent of :func:`sc1_four_port_flows`."""
    spool = max(-1.0, min(1.0, command))
    pressures = (p_supply, p_tank, p_a, p_b)
    q0 = q1 = q2 = q3 = 0.0
    maximum_fraction = 0.0
    for branch_code, left, right, curve_code, coefficient in compiled:
        fraction = _fraction_from_code(spool, curve_code)
        if fraction > maximum_fraction:
            maximum_fraction = fraction
        if fraction <= 0.0:
            flow = 0.0
        else:
            dp = pressures[left] - pressures[right]
            flow = coefficient * fraction * dp / ((dp * dp + 1.0) ** 0.25)
        if branch_code == 0:
            q0 = flow
        elif branch_code == 1:
            q1 = flow
        elif branch_code == 2:
            q2 = flow
        else:
            q3 = flow
    return ValveFlows(
        q_a=q0 + q2, q_b=q1 + q3, q_supply=q0 + q1,
        opening=maximum_fraction * 20.0e-6,
        q_pa=q0, q_pb=q1, q_at=-q2, q_bt=-q3,
        q_return=-(q2 + q3), spool_position=spool)


def sc1_four_port_flows_compiled_with_derivatives(
        command: float, pressures: tuple[float, float, float, float],
        dpressure_low: tuple[float, float, float, float],
        dpressure_high: tuple[float, float, float, float],
        compiled: tuple[tuple[int, int, int, int, float], ...]
        ) -> tuple[ValveFlows, float, float, float, float]:
    """Compiled flows and analytic rail-pressure derivatives.

    Returns the valve flows followed by derivatives of ``q_supply`` and
    ``q_return`` with respect to the low and high algebraic rail pressures.
    """
    spool = max(-1.0, min(1.0, command))
    flows = [0.0, 0.0, 0.0, 0.0]
    dlow = [0.0, 0.0, 0.0, 0.0]
    dhigh = [0.0, 0.0, 0.0, 0.0]
    maximum_fraction = 0.0
    for branch_code, left, right, curve_code, coefficient in compiled:
        fraction = _fraction_from_code(spool, curve_code)
        if fraction > maximum_fraction:
            maximum_fraction = fraction
        if fraction <= 0.0:
            continue
        dp = pressures[left] - pressures[right]
        base = dp * dp + 1.0
        flow = coefficient * fraction * dp / (base ** 0.25)
        dq_ddp = coefficient * fraction * (0.5 * dp * dp + 1.0) / (base ** 1.25)
        flows[branch_code] = flow
        dlow[branch_code] = dq_ddp * (
            dpressure_low[left] - dpressure_low[right])
        dhigh[branch_code] = dq_ddp * (
            dpressure_high[left] - dpressure_high[right])
    q0, q1, q2, q3 = flows
    valve_flows = ValveFlows(
        q_a=q0 + q2, q_b=q1 + q3, q_supply=q0 + q1,
        opening=maximum_fraction * 20.0e-6,
        q_pa=q0, q_pb=q1, q_at=-q2, q_bt=-q3,
        q_return=-(q2 + q3), spool_position=spool)
    return (valve_flows, dlow[0] + dlow[1], dhigh[0] + dhigh[1],
            -(dlow[2] + dlow[3]), -(dhigh[2] + dhigh[3]))
