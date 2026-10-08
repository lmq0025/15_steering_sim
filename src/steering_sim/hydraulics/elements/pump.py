from __future__ import annotations

from dataclasses import dataclass

from ..surrogates import q0top


@dataclass(frozen=True, slots=True)
class PU001:
    """Fixed-displacement pump in SI units; q0top is the Phase-1 surrogate."""
    displacement_m3_rad: float

    def __post_init__(self) -> None:
        if self.displacement_m3_rad <= 0.0:
            raise ValueError("pump displacement must be positive")

    def flow_m3_s(self, angular_speed_rad_s: float, upstream_pressure_pa: float = 0.0) -> float:
        return self.displacement_m3_rad * float(angular_speed_rad_s) / q0top(upstream_pressure_pa)

    def torque_nm(self, inlet_pressure_pa: float, outlet_pressure_pa: float) -> float:
        return (float(outlet_pressure_pa) - float(inlet_pressure_pa)) * self.displacement_m3_rad
