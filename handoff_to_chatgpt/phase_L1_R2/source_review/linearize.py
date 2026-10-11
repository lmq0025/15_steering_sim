from __future__ import annotations

import numpy as np

from .model import LumpedHydraulicSystem, SystemInputs


def linearize(model: LumpedHydraulicSystem, x0: np.ndarray, u0: SystemInputs) -> tuple[np.ndarray, np.ndarray]:
    x0 = np.asarray(x0, dtype=float)
    uvec = np.asarray(list(u0.valve_commands) + list(u0.pump_speeds) + list(u0.load_forces), dtype=float)
    n, m = x0.size, uvec.size
    a = np.empty((n, n)); b = np.empty((n, m))

    def unpack(v: np.ndarray) -> SystemInputs:
        q = len(model.channels)
        return SystemInputs(v[:q], v[q:2*q], v[2*q:3*q])

    for j in range(n):
        h = max(abs(x0[j]) * 1e-5, 1e-3 if j % 4 < 2 else 1e-7)
        xp, xm = x0.copy(), x0.copy(); xp[j] += h; xm[j] -= h
        a[:, j] = (model.rhs(0.0, xp, u0) - model.rhs(0.0, xm, u0)) / (2*h)
    for j in range(m):
        h = max(abs(uvec[j]) * 1e-5, 1e-6)
        up, um = uvec.copy(), uvec.copy(); up[j] += h; um[j] -= h
        b[:, j] = (model.rhs(0.0, x0, unpack(up)) - model.rhs(0.0, x0, unpack(um))) / (2*h)
    return a, b
