"""Interface placeholder for a future plant-informed sliding-mode design."""

from __future__ import annotations

import numpy as np

from .base import Command, Controller, Measurement, Reference


class SlidingModeController(Controller):
    """Bounded reaching-law baseline, intentionally free of plant equations in R01."""

    def __init__(self, gain: float, boundary_layer: float = 0.01, limit: float = 1.0):
        if gain < 0.0 or boundary_layer <= 0.0 or limit <= 0.0:
            raise ValueError("gain must be non-negative; boundary_layer and limit must be positive")
        self.gain = float(gain)
        self.boundary_layer = float(boundary_layer)
        self.limit = float(limit)

    def reset(self) -> None:
        return None

    def step(self, measurement: Measurement, reference: Reference, dt: float) -> Command:
        if dt <= 0.0:
            raise ValueError("dt must be positive")
        surface = np.asarray(reference.values, dtype=float) - np.asarray(measurement.values, dtype=float)
        command = self.gain * np.tanh(surface / self.boundary_layer)
        return Command(np.clip(command, -self.limit, self.limit))

