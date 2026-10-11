from __future__ import annotations

import math
from dataclasses import dataclass

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
