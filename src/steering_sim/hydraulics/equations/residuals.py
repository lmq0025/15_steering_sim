from __future__ import annotations

import numpy as np
from numpy.typing import NDArray


def hydraulic_zero_residual(pressures_pa, flows_into_m3_s) -> NDArray[np.float64]:
    p, q = np.asarray(pressures_pa, dtype=float), np.asarray(flows_into_m3_s, dtype=float)
    return np.concatenate((p[1:] - p[0], np.array([q.sum()])))


def mechanical_one_residual(flows, efforts_into) -> NDArray[np.float64]:
    f, e = np.asarray(flows, dtype=float), np.asarray(efforts_into, dtype=float)
    return np.concatenate((f[1:] - f[0], np.array([e.sum()])))
