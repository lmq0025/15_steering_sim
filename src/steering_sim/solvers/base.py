"""Solver-neutral ODE contract; DAE extension points are documented for later rounds."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]
StateRHS = Callable[[float, FloatArray], FloatArray]


@dataclass(frozen=True, slots=True)
class SolverResult:
    time: FloatArray
    state: FloatArray
    success: bool
    message: str = ""


class Solver(ABC):
    @abstractmethod
    def solve(
        self,
        rhs: StateRHS,
        t_span: tuple[float, float],
        initial_state: FloatArray,
        *,
        evaluation_times: FloatArray | None = None,
    ) -> SolverResult:
        """Integrate a coupled system assembled as one RHS."""

