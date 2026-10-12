"""Controller contract independent of any physical model implementation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Mapping

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class Measurement:
    values: FloatArray
    names: tuple[str, ...] = ()
    metadata: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Reference:
    values: FloatArray
    names: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Command:
    values: FloatArray


class Controller(ABC):
    """Uniform sampled-data law: measurement + reference + dt -> command."""

    @abstractmethod
    def reset(self) -> None:
        """Clear controller memory."""

    @abstractmethod
    def step(self, measurement: Measurement, reference: Reference, dt: float) -> Command:
        """Compute one discrete command without holding a plant reference."""

