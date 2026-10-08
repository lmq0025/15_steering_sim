from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MAS001:
    mass_kg: float
    gravity_component_m_s2: float = 0.0

    def acceleration_m_s2(self, applied_force_n: float) -> float:
        if self.mass_kg <= 0.0:
            raise ValueError("mass must be positive")
        return self.gravity_component_m_s2 - applied_force_n / self.mass_kg

    @staticmethod
    def displacement_rhs_m_s(velocity_m_s: float) -> float:
        return float(velocity_m_s)
