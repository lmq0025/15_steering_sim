"""Evidence-backed geometry/observation layer for actuator001 / HJ020."""

from __future__ import annotations

import math
from dataclasses import dataclass
import numpy as np
from numpy.typing import NDArray
from .fluid import ConstantFluidProperties
from .r03b1_errors import UnresolvedAmesimUtilityError


@dataclass(frozen=True, slots=True)
class HJ020Config:
    piston_diameter_m: float
    rod_diameter_m: float
    stroke_m: float
    dead_volume_1_m3: float
    dead_volume_2_m3: float
    leakage_m3_s_pa: float
    viscous_friction_n_per_mps: float


@dataclass(frozen=True, slots=True)
class CylinderObservation:
    pressure_1_pa: float
    pressure_2_pa: float
    force_n: float
    leakage_m3_s: float
    volume_1_m3: float
    volume_2_m3: float


class HJ020Cylinder:
    """HJ020 legal-stroke branch; x is reported ``xact`` and v is dxact/dt."""

    def __init__(self, config: HJ020Config, fluid: ConstantFluidProperties) -> None:
        if not 0.0 < config.rod_diameter_m < config.piston_diameter_m:
            raise ValueError("HJ020 requires 0 < rod diameter < piston diameter")
        if config.stroke_m <= 0.0 or config.dead_volume_1_m3 <= 0.0 or config.dead_volume_2_m3 <= 0.0:
            raise ValueError("HJ020 stroke and dead volumes must be positive")
        self.config, self.fluid = config, fluid

    @property
    def piston_area_m2(self) -> float:
        return math.pi * self.config.piston_diameter_m**2 / 4.0

    @property
    def rod_area_m2(self) -> float:
        return math.pi * self.config.rod_diameter_m**2 / 4.0

    @property
    def annular_area_m2(self) -> float:
        return self.piston_area_m2 - self.rod_area_m2

    def chamber_volumes(self, displacement_m: float) -> tuple[float, float]:
        x = float(displacement_m)
        if not 0.0 <= x <= self.config.stroke_m:
            raise ValueError("Prescribed xact is outside [0, stroke]; HJ020 endstops are out of R03-B1 scope")
        return self.piston_area_m2 * x + self.config.dead_volume_1_m3, self.annular_area_m2 * (self.config.stroke_m - x) + self.config.dead_volume_2_m3

    def observe(self, state_pa: NDArray[np.float64], displacement_m: float, velocity_mps: float) -> CylinderObservation:
        values = np.asarray(state_pa, dtype=float)
        if values.shape != (2,):
            raise ValueError("HJ020 state must be [p1, p2]")
        p1, p2 = map(float, values)
        v1, v2 = self.chamber_volumes(displacement_m)
        leakage = (p1 - p2) * self.config.leakage_m3_s_pa
        force = p1 * self.piston_area_m2 - p2 * self.annular_area_m2 - float(velocity_mps) * self.config.viscous_friction_n_per_mps
        return CylinderObservation(p1, p2, force, leakage, v1, v2)

    def rhs(self, state_pa: NDArray[np.float64], q1_into_cylinder_m3_s: float, q2_into_cylinder_m3_s: float, displacement_m: float, velocity_mps: float) -> NDArray[np.float64]:
        self.chamber_volumes(displacement_m)
        raise UnresolvedAmesimUtilityError(
            "HJ020 pressure RHS calls AMESim 2021.1 private pcdyn2_/q0top_ utilities; "
            "no constant-beta substitute is permitted without their equation bodies"
        )

