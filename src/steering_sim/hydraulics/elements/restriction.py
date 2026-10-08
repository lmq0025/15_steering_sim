from __future__ import annotations

from dataclasses import dataclass

from ..surrogates import regularized_orifice_flow


@dataclass(frozen=True, slots=True)
class FixedOrifice:
    area_m2: float
    density_kg_m3: float
    discharge_coefficient: float = 0.7
    smoothing_pressure_pa: float = 10.0

    def flow_m3_s(self, upstream_pressure_pa: float, downstream_pressure_pa: float) -> float:
        return regularized_orifice_flow(upstream_pressure_pa - downstream_pressure_pa, self.area_m2, self.density_kg_m3, self.discharge_coefficient, self.smoothing_pressure_pa)


@dataclass(frozen=True, slots=True)
class VariableOrifice(FixedOrifice):
    def flow_m3_s(self, upstream_pressure_pa: float, downstream_pressure_pa: float, opening: float = 1.0) -> float:
        fraction = min(max(float(opening), 0.0), 1.0)
        return regularized_orifice_flow(upstream_pressure_pa - downstream_pressure_pa, self.area_m2 * fraction, self.density_kg_m3, self.discharge_coefficient, self.smoothing_pressure_pa)
