from __future__ import annotations

import math
from dataclasses import dataclass

from ..surrogates import chamber_pressure_rhs


@dataclass(frozen=True, slots=True)
class DoubleActingCylinder:
    piston_diameter_m: float
    rod_diameter_1_m: float
    rod_diameter_2_m: float
    stroke_m: float
    dead_volume_1_m3: float
    dead_volume_2_m3: float
    bulk_modulus_pa: float
    leakage_m3_s_pa: float = 0.0
    viscous_friction_n_s_m: float = 0.0
    spring_rate_n_m: float = 0.0
    spring_preload_n: float = 0.0

    def __post_init__(self) -> None:
        if self.piston_diameter_m <= 0 or self.stroke_m <= 0 or self.dead_volume_1_m3 <= 0 or self.dead_volume_2_m3 <= 0:
            raise ValueError("cylinder geometry, stroke and dead volumes must be positive")
        if not (0 <= self.rod_diameter_1_m < self.piston_diameter_m and 0 <= self.rod_diameter_2_m < self.piston_diameter_m):
            raise ValueError("rod diameters must be smaller than piston diameter")

    @property
    def piston_area_m2(self) -> float:
        return math.pi * self.piston_diameter_m**2 / 4.0

    @property
    def area_1_m2(self) -> float:
        return self.piston_area_m2 - math.pi * self.rod_diameter_1_m**2 / 4.0

    @property
    def area_2_m2(self) -> float:
        return self.piston_area_m2 - math.pi * self.rod_diameter_2_m**2 / 4.0

    def chamber_volumes_m3(self, displacement_m: float) -> tuple[float, float]:
        x = float(displacement_m)
        if not 0.0 <= x <= self.stroke_m:
            raise ValueError("displacement must lie inside the cylinder stroke")
        return self.dead_volume_1_m3 + self.area_1_m2 * x, self.dead_volume_2_m3 + self.area_2_m2 * (self.stroke_m - x)

    def leakage_flow_m3_s(self, p1_pa: float, p2_pa: float) -> float:
        return self.leakage_m3_s_pa * (float(p1_pa) - float(p2_pa))

    def force_n(self, p1_pa: float, p2_pa: float, velocity_m_s: float, displacement_m: float) -> float:
        return (self.area_1_m2 * p1_pa - self.area_2_m2 * p2_pa - self.viscous_friction_n_s_m * velocity_m_s
                - self.spring_preload_n - self.spring_rate_n_m * displacement_m)

    def pressure_rhs_pa_s(self, p1_pa: float, p2_pa: float, q1_into_m3_s: float, q2_into_m3_s: float, displacement_m: float, velocity_m_s: float) -> tuple[float, float]:
        v1, v2 = self.chamber_volumes_m3(displacement_m)
        leak = self.leakage_flow_m3_s(p1_pa, p2_pa)
        # Independent-model convention: positive velocity extends the rod,
        # increasing chamber 1 and decreasing chamber 2.
        net1 = q1_into_m3_s - self.area_1_m2 * velocity_m_s - leak
        net2 = q2_into_m3_s + self.area_2_m2 * velocity_m_s + leak
        return chamber_pressure_rhs(self.bulk_modulus_pa, v1, net1), chamber_pressure_rhs(self.bulk_modulus_pa, v2, net2)


def HJ020(**kwargs) -> DoubleActingCylinder:
    """Single-rod cylinder: full piston area at port 1, annular at port 2."""
    kwargs.setdefault("rod_diameter_1_m", 0.0)
    return DoubleActingCylinder(**kwargs)


def HJ021(**kwargs) -> DoubleActingCylinder:
    """Double-rod cylinder; caller supplies both rod diameters."""
    return DoubleActingCylinder(**kwargs)


def HJ0022(**kwargs) -> DoubleActingCylinder:
    """Spring-return single-rod cylinder."""
    kwargs.setdefault("rod_diameter_1_m", 0.0)
    return DoubleActingCylinder(**kwargs)
