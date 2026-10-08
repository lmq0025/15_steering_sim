from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import Callable

import numpy as np
from numpy.typing import NDArray


ResidualJacobian = Callable[[NDArray[np.float64]], tuple[NDArray[np.float64], NDArray[np.float64]]]


@dataclass(slots=True)
class AlgebraicDiagnostics:
    calls: int = 0
    failures: int = 0
    total_iterations: int = 0
    max_iterations: int = 0
    warm_start_hits: int = 0
    total_wall_time_s: float = 0.0
    last_residual: float = 0.0

    @property
    def mean_iterations(self) -> float:
        return self.total_iterations / self.calls if self.calls else 0.0

    @property
    def mean_wall_time_s(self) -> float:
        return self.total_wall_time_s / self.calls if self.calls else 0.0


@dataclass(slots=True)
class LocalAlgebraicSolver:
    group_id: str
    size: int
    max_iterations: int = 8
    relative_tolerance: float = 1.0e-7
    pressure_scale_pa: float = 1.0e7
    previous: NDArray[np.float64] | None = None
    diagnostics: AlgebraicDiagnostics = field(default_factory=AlgebraicDiagnostics)

    def solve(self, residual_jacobian: ResidualJacobian, initial: NDArray[np.float64] | None = None) -> NDArray[np.float64]:
        started = perf_counter()
        self.diagnostics.calls += 1
        if self.previous is not None and self.previous.shape == (self.size,):
            value = self.previous.copy()
            self.diagnostics.warm_start_hits += 1
        elif initial is not None:
            value = np.asarray(initial, dtype=float).copy()
        else:
            value = np.full(self.size, 1.0e5, dtype=float)
        converged = False
        iterations = 0
        for iterations in range(1, self.max_iterations + 1):
            residual, jacobian = residual_jacobian(value)
            norm = float(np.max(np.abs(residual))) if residual.size else 0.0
            self.diagnostics.last_residual = norm
            if norm <= self.relative_tolerance * max(1.0, float(np.max(np.abs(value))) / self.pressure_scale_pa):
                converged = True
                break
            try:
                delta = np.linalg.solve(jacobian, -residual)
            except np.linalg.LinAlgError:
                delta = np.linalg.lstsq(jacobian, -residual, rcond=None)[0]
            # Damping prevents switching/orifice updates from overshooting.
            limit = 0.5 * np.maximum(np.abs(value), self.pressure_scale_pa)
            value += np.clip(delta, -limit, limit)
        if not converged:
            # Fallback: one regularized least-squares correction. A remaining
            # failure is reported; it is never silently accepted.
            residual, jacobian = residual_jacobian(value)
            regularized = jacobian + np.eye(self.size) * 1.0e-14
            value += np.linalg.lstsq(regularized, -residual, rcond=None)[0]
            residual, _ = residual_jacobian(value)
            self.diagnostics.last_residual = float(np.max(np.abs(residual))) if residual.size else 0.0
            converged = self.diagnostics.last_residual <= 1.0e-8
        if not converged:
            self.diagnostics.failures += 1
        self.previous = value.copy()
        self.diagnostics.total_iterations += iterations
        self.diagnostics.max_iterations = max(self.diagnostics.max_iterations, iterations)
        self.diagnostics.total_wall_time_s += perf_counter() - started
        return value

    def reset(self) -> None:
        self.previous = None
        self.diagnostics = AlgebraicDiagnostics()
