"""HYDVORF0 active-branch configuration and explicit traceability barrier."""

from __future__ import annotations

from dataclasses import dataclass

from .r03b1_errors import UnresolvedAmesimUtilityError


@dataclass(frozen=True, slots=True)
class HYDVORF0Config:
    characteristic_flow_m3_s: float
    characteristic_pressure_drop_pa: float
    critical_flow_number: float
    measurement_density_kg_m3: float
    measurement_kinematic_viscosity_m2_s: float
    minimum_signal: float = 0.0
    maximum_signal: float = 100.0
    method: int = 1
    parallel_orifices: int = 1


@dataclass(frozen=True, slots=True)
class HYDVORF0Observation:
    opening_signal: float
    normalized_opening: float
    pressure_drop_pa: float
    flow_m3_s: float
    clipped: bool


class HYDVORF0:
    """Facade for method 1; refuses an untraceable replacement for private utilities."""

    def __init__(self, config: HYDVORF0Config) -> None:
        if config.method != 1:
            raise NotImplementedError("Only the audited HYDVORF0 method=1 branch is in scope")
        self.config = config

    def flow(self, pressure_1_pa: float, pressure_2_pa: float, opening_signal: float) -> HYDVORF0Observation:
        raise UnresolvedAmesimUtilityError(
            "HYDVORF0 method=1 requires AMESim 2021.1 private utilities eqarea/orif3f_; "
            "no traceable equation body was found, so R03-B1 will not substitute a textbook orifice law"
        )

    def normalize_opening(self, opening_signal: float) -> tuple[float, bool]:
        limited = min(max(float(opening_signal), self.config.minimum_signal), self.config.maximum_signal)
        span = self.config.maximum_signal - self.config.minimum_signal
        if span <= 0.0:
            raise ValueError("HYDVORF0 signal interval must be positive")
        return (limited - self.config.minimum_signal) / span, limited != float(opening_signal)

