"""Small vector PID baseline; tuning and actuator-specific logic are out of scope for R01."""

from __future__ import annotations

import numpy as np

from .base import Command, Controller, Measurement, Reference


class PIDController(Controller):
    def __init__(self, kp: float, ki: float = 0.0, kd: float = 0.0, limit: float = 1.0):
        self.kp = float(kp)
        self.ki = float(ki)
        self.kd = float(kd)
        self.limit = float(limit)
        if self.limit <= 0.0:
            raise ValueError("limit must be positive")
        self.reset()

    def reset(self) -> None:
        self._integral: np.ndarray | None = None
        self._previous_error: np.ndarray | None = None

    def step(self, measurement: Measurement, reference: Reference, dt: float) -> Command:
        if dt <= 0.0:
            raise ValueError("dt must be positive")
        error = np.asarray(reference.values, dtype=float) - np.asarray(measurement.values, dtype=float)
        if self._integral is None:
            self._integral = np.zeros_like(error)
        derivative = (
            np.zeros_like(error)
            if self._previous_error is None
            else (error - self._previous_error) / dt
        )
        candidate_integral = self._integral + error * dt
        raw = self.kp * error + self.ki * candidate_integral + self.kd * derivative
        command = np.clip(raw, -self.limit, self.limit)
        # Conditional integration: do not wind up further into saturation.
        integrate = (raw == command) | (np.sign(error) != np.sign(raw))
        self._integral = np.where(integrate, candidate_integral, self._integral)
        self._previous_error = error.copy()
        return Command(np.asarray(command, dtype=float))

