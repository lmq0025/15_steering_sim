"""Explicit fixed-step reference solver for smoke tests and non-stiff prototypes."""

from __future__ import annotations

import numpy as np

from .base import Solver, SolverResult, StateRHS


class ExplicitFixedStepSolver(Solver):
    def __init__(self, step_size: float, method: str = "rk4") -> None:
        if step_size <= 0.0:
            raise ValueError("step_size must be positive")
        if method not in {"euler", "rk4"}:
            raise ValueError("method must be 'euler' or 'rk4'")
        self.step_size = float(step_size)
        self.method = method

    def _advance(self, rhs: StateRHS, t: float, y: np.ndarray, h: float) -> np.ndarray:
        if self.method == "euler":
            return y + h * np.asarray(rhs(t, y), dtype=float)
        k1 = np.asarray(rhs(t, y), dtype=float)
        k2 = np.asarray(rhs(t + h / 2, y + h * k1 / 2), dtype=float)
        k3 = np.asarray(rhs(t + h / 2, y + h * k2 / 2), dtype=float)
        k4 = np.asarray(rhs(t + h, y + h * k3), dtype=float)
        return y + h * (k1 + 2 * k2 + 2 * k3 + k4) / 6

    def solve(self, rhs, t_span, initial_state, *, evaluation_times=None) -> SolverResult:
        t0, tf = map(float, t_span)
        if tf <= t0:
            raise ValueError("t_span must be increasing")
        if evaluation_times is not None:
            requested = np.asarray(evaluation_times, dtype=float)
            if requested.ndim != 1 or len(requested) < 2:
                raise ValueError("evaluation_times must be a one-dimensional grid")
            if requested[0] != t0 or requested[-1] != tf:
                raise ValueError("evaluation_times must include both t_span endpoints")
            times = requested
        else:
            steps = max(1, int(np.ceil((tf - t0) / self.step_size)))
            times = np.linspace(t0, tf, steps + 1)
        states = [np.asarray(initial_state, dtype=float).copy()]
        for left, right in zip(times[:-1], times[1:]):
            y = states[-1]
            interval = float(right - left)
            substeps = max(1, int(np.ceil(interval / self.step_size)))
            h = interval / substeps
            t = float(left)
            for _ in range(substeps):
                y = self._advance(rhs, t, y, h)
                t += h
            states.append(y)
        return SolverResult(times.copy(), np.stack(states, axis=1), True, "completed")

