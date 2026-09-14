"""Continuous-time contract for the electro-hydraulic subsystem."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Any, Mapping

import numpy as np
from numpy.typing import NDArray

from steering_sim.core.lifecycle import ObservableComponent
from steering_sim.core.parameters import ParameterMeta
from steering_sim.core.ports import HydraulicPowerPort, RotationalPowerPort, TranslationalPowerPort

FloatArray = NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class HydraulicState:
    pressure: FloatArray
    flow: FloatArray
    internal: FloatArray = field(default_factory=lambda: np.empty(0, dtype=float))


@dataclass(frozen=True, slots=True)
class HydraulicInputs:
    command: FloatArray
    actuator_displacement: FloatArray
    actuator_velocity: FloatArray


@dataclass(frozen=True, slots=True)
class HydraulicOutputs:
    actuator_effort: FloatArray
    supply_ports: tuple[HydraulicPowerPort, ...]
    actuator_ports: tuple[TranslationalPowerPort | RotationalPowerPort, ...]


class HydraulicModel(ObservableComponent):
    """Hydraulic network boundary; pressure/flow states remain solver-owned."""

    @abstractmethod
    def rhs(self, t: float, state: HydraulicState, inputs: HydraulicInputs) -> HydraulicState:
        """Return pressure, flow, and internal-state derivatives."""

    @abstractmethod
    def outputs(self, state: HydraulicState, inputs: HydraulicInputs) -> HydraulicOutputs:
        """Return forces/torques and power ports presented to other subsystems."""

    @abstractmethod
    def update_parameters(self, updates: Mapping[str, ParameterMeta]) -> None:
        """Apply traceable runtime parameter changes (reserved for degradation models)."""

