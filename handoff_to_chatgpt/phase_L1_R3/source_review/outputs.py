from __future__ import annotations

import numpy as np

from .model import LumpedHydraulicSystem, SystemInputs


def output_history(model: LumpedHydraulicSystem, times: np.ndarray, states: np.ndarray, inputs) -> dict[str, np.ndarray]:
    result: dict[str, list[float]] = {}
    for t, x in zip(times, states):
        _, channels = model.evaluate(float(t), x, inputs(float(t)))
        for i, values in enumerate(channels):
            for key, value in values.items():
                result.setdefault(f"channel_{i+1}.{key}", []).append(value)
    return {key: np.asarray(value) for key, value in result.items()}
