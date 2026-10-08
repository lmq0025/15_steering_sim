from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TK000:
    pressure_pa: float

    def effort(self) -> float:
        return self.pressure_pa


@dataclass(frozen=True, slots=True)
class PM000:
    angular_speed_rad_s: float

    def flow(self) -> float:
        return self.angular_speed_rad_s


@dataclass(frozen=True, slots=True)
class FORC:
    """Exact modulated translational effort source; command is force in N."""
    default_force_n: float = 0.0

    def effort(self, command_n: float | None = None) -> float:
        return self.default_force_n if command_n is None else float(command_n)
