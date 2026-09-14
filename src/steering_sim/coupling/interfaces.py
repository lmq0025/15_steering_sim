"""Coupling records without implementing a general Bond Graph solver."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from steering_sim.core.ports import HydraulicPowerPort, RotationalPowerPort, TranslationalPowerPort

MechanicalPort = TranslationalPowerPort | RotationalPowerPort


@dataclass(frozen=True, slots=True)
class CouplingExchange:
    """Values exchanged at one coupled RHS evaluation."""

    actuator_displacement: NDArray[np.float64]
    actuator_velocity: NDArray[np.float64]
    actuator_effort: NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class PowerBalance:
    hydraulic: tuple[HydraulicPowerPort, ...]
    mechanical: tuple[MechanicalPort, ...]
    losses: float = 0.0

    @property
    def residual(self) -> float:
        """Signed instantaneous imbalance; zero is the ideal conservation target."""
        return float(
            sum(port.power for port in self.hydraulic)
            + sum(port.power for port in self.mechanical)
            + self.losses
        )

