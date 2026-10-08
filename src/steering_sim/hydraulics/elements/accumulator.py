from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GasAccumulator:
    precharge_pressure_abs_pa: float
    nominal_gas_volume_m3: float
    polytropic_index: float = 1.4

    def gas_volume_m3(self, pressure_abs_pa: float) -> float:
        if pressure_abs_pa <= 0.0:
            raise ValueError("absolute pressure must be positive")
        return self.nominal_gas_volume_m3 * (self.precharge_pressure_abs_pa / pressure_abs_pa) ** (1.0 / self.polytropic_index)

    def pressure_rhs_pa_s(self, pressure_abs_pa: float, inflow_m3_s: float) -> float:
        volume = self.gas_volume_m3(pressure_abs_pa)
        return self.polytropic_index * pressure_abs_pa * inflow_m3_s / volume
