from __future__ import annotations

from .parameters import PumpParameters


def pump_flow(speed_rad_s: float, p_out: float, p_in: float, p: PumpParameters) -> float:
    return p.displacement * speed_rad_s * p.volumetric_efficiency - p.leakage * (p_out - p_in)


def pump_torque(p_out: float, p_in: float, p: PumpParameters) -> float:
    return (p_out - p_in) * p.displacement
