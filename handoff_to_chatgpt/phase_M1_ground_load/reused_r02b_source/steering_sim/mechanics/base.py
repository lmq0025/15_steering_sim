"""Continuous-time contract for steering mechanical models."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
from numpy.typing import NDArray

from steering_sim.core.lifecycle import ObservableComponent
from steering_sim.core.ports import RotationalPowerPort, TranslationalPowerPort

FloatArray = NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class MechanicalState:
    q: FloatArray
    q_dot: FloatArray
    q_ddot: FloatArray


@dataclass(frozen=True, slots=True)
class MechanicalInputs:
    external_load: FloatArray
    actuator_effort: FloatArray


@dataclass(frozen=True, slots=True)
class MechanicalDerivative:
    q_dot: FloatArray
    q_ddot: FloatArray


class MechanicalModel(ObservableComponent):
    """Model boundary; a solver/orchestrator owns numerical integration."""

    @abstractmethod
    def derivative(
        self, t: float, state: MechanicalState, inputs: MechanicalInputs
    ) -> MechanicalDerivative:
        """Evaluate continuous mechanical dynamics without mutating state."""

    @abstractmethod
    def forward_kinematics(self, q: FloatArray) -> Mapping[str, FloatArray]:
        """Return named positions/poses derived from generalized coordinates."""

    @abstractmethod
    def constraint_residual(self, state: MechanicalState) -> FloatArray:
        """Return holonomic/non-holonomic joint constraint residuals for DAE use."""

    @abstractmethod
    def actuator_kinematics(self, state: MechanicalState) -> tuple[FloatArray, FloatArray]:
        """Return actuator displacement and velocity for the hydraulic model."""

    @abstractmethod
    def actuator_ports(
        self, state: MechanicalState, inputs: MechanicalInputs
    ) -> tuple[TranslationalPowerPort | RotationalPowerPort, ...]:
        """Expose mechanical-side coupling ports using the project sign convention."""

