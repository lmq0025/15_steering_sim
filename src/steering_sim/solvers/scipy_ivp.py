"""Adapter for SciPy RK45/BDF/Radau integration methods."""

from __future__ import annotations

import numpy as np
from scipy.integrate import solve_ivp

from .base import Solver, SolverResult


class ScipyIVPSolver(Solver):
    SUPPORTED_METHODS = ("RK45", "BDF", "Radau")

    def __init__(self, method: str = "RK45", *, rtol: float = 1e-6, atol: float = 1e-9):
        if method not in self.SUPPORTED_METHODS:
            raise ValueError(f"unsupported method: {method}")
        self.method = method
        self.rtol = float(rtol)
        self.atol = float(atol)

    def solve(self, rhs, t_span, initial_state, *, evaluation_times=None) -> SolverResult:
        result = solve_ivp(
            rhs,
            t_span,
            np.asarray(initial_state, dtype=float),
            method=self.method,
            t_eval=evaluation_times,
            rtol=self.rtol,
            atol=self.atol,
        )
        return SolverResult(result.t, result.y, bool(result.success), str(result.message))

