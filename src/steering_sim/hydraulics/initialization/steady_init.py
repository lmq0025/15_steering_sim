from __future__ import annotations

import numpy as np
from numpy.typing import NDArray


def relax_pressure_states(model, state: NDArray[np.float64], inputs: dict[str, float], passes: int = 4) -> NDArray[np.float64]:
    """Project storage pressures toward their connected algebraic boundaries."""
    value = np.asarray(state, dtype=float).copy()
    for _ in range(passes):
        algebraic = model.solve_algebraic(0.0, value, inputs)
        for dynamic in model.dynamic_hydraulic:
            pressures = [algebraic.junction_pressure_pa[j] for j in dynamic.junction_indices]
            if not pressures:
                continue
            if len(dynamic.state_indices) == 1:
                value[dynamic.state_indices[0]] = float(np.mean(pressures))
            else:
                value[dynamic.state_indices[0]] = pressures[0]
                value[dynamic.state_indices[-1]] = pressures[-1]
                if len(dynamic.state_indices) > 2:
                    value[list(dynamic.state_indices)] = np.linspace(pressures[0], pressures[-1], len(dynamic.state_indices))
    return value
