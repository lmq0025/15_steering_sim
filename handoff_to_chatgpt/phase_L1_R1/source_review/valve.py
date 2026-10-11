from __future__ import annotations

import math
from dataclasses import dataclass

from .parameters import FluidParameters, ValveParameters


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
