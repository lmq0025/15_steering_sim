from __future__ import annotations

from dataclasses import dataclass
import numpy as np
from numpy.typing import NDArray

from ..surrogates import chamber_pressure_rhs, pipe_flow_from_pressure_drop


@dataclass(frozen=True, slots=True)
class ComplianceLine:
    volume_m3: float
    bulk_modulus_pa: float

    def pressure_rhs_pa_s(self, net_inflow_m3_s: float) -> float:
        return chamber_pressure_rhs(self.bulk_modulus_pa, self.volume_m3, net_inflow_m3_s)


@dataclass(frozen=True, slots=True)
class ResistiveComplianceLine:
    volume_m3: float
    bulk_modulus_pa: float
    laminar_resistance_pa_s_m3: float
    quadratic_resistance_pa_s2_m6: float

    def end_flow_m3_s(self, end_pressure_pa: float, middle_pressure_pa: float) -> float:
        return pipe_flow_from_pressure_drop(end_pressure_pa - middle_pressure_pa, self.laminar_resistance_pa_s_m3, self.quadratic_resistance_pa_s2_m6)

    def pressure_rhs_pa_s(self, middle_pressure_pa: float, pressure_1_pa: float, pressure_2_pa: float) -> float:
        q1 = self.end_flow_m3_s(pressure_1_pa, middle_pressure_pa)
        q2 = self.end_flow_m3_s(pressure_2_pa, middle_pressure_pa)
        return chamber_pressure_rhs(self.bulk_modulus_pa, self.volume_m3, q1 + q2)


@dataclass(frozen=True, slots=True)
class SegmentedLine:
    cell_volumes_m3: NDArray[np.float64]
    bulk_modulus_pa: float
    laminar_resistance_pa_s_m3: float
    quadratic_resistance_pa_s2_m6: float

    def rhs(self, pressures_pa: NDArray[np.float64], inlet_pressure_pa: float, outlet_pressure_pa: float) -> NDArray[np.float64]:
        p = np.asarray(pressures_pa, dtype=float)
        volumes = np.asarray(self.cell_volumes_m3, dtype=float)
        if p.shape != volumes.shape or np.any(volumes <= 0.0):
            raise ValueError("one positive volume is required for every pressure cell")
        boundaries = np.concatenate(([inlet_pressure_pa], p, [outlet_pressure_pa]))
        flows = np.array([pipe_flow_from_pressure_drop(boundaries[i] - boundaries[i + 1], self.laminar_resistance_pa_s_m3, self.quadratic_resistance_pa_s2_m6) for i in range(len(p) + 1)])
        return self.bulk_modulus_pa / volumes * (flows[:-1] - flows[1:])
