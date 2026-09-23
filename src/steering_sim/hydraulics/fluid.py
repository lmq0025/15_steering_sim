"""R03-B1 fluid data only; proprietary AMESim property utilities are not reimplemented."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConstantFluidProperties:
    fluid_index: int
    density_kg_m3: float
    bulk_modulus_pa: float
    dynamic_viscosity_pa_s: float
    air_content_percent: float
    saturation_pressure_pa: float
    source_submodel: str = "FP04"

    @property
    def kinematic_viscosity_m2_s(self) -> float:
        return self.dynamic_viscosity_pa_s / self.density_kg_m3

