from __future__ import annotations

from collections.abc import Callable
import numpy as np

from .model import LumpedHydraulicSystem, SystemInputs


InputFunction = Callable[[float], SystemInputs]


def simulate_rk4(model: LumpedHydraulicSystem, duration: float, dt: float,
                 inputs: InputFunction, x0: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    steps = int(round(duration / dt))
    times = np.linspace(0.0, duration, steps + 1)
    states = np.empty((steps + 1, model.state_count), dtype=float)
    states[0] = model.initial_state() if x0 is None else np.asarray(x0, dtype=float)
    for k in range(steps):
        t = times[k]
        x = states[k]
        h = times[k + 1] - t
        k1 = model.rhs(t, x, inputs(t))
        k2 = model.rhs(t + h / 2, x + h * k1 / 2, inputs(t + h / 2))
        k3 = model.rhs(t + h / 2, x + h * k2 / 2, inputs(t + h / 2))
        k4 = model.rhs(t + h, x + h * k3, inputs(t + h))
        states[k + 1] = x + h * (k1 + 2 * k2 + 2 * k3 + k4) / 6
    return times, states


def simulate_scipy(model: LumpedHydraulicSystem, duration: float, sample_dt: float,
                   inputs: InputFunction, x0: np.ndarray | None = None,
                   method: str = "DOP853") -> tuple[np.ndarray, np.ndarray]:
    from scipy.integrate import solve_ivp
    t = np.arange(0.0, duration + sample_dt * 0.5, sample_dt)
    initial = model.initial_state() if x0 is None else np.asarray(x0, dtype=float)
    sol = solve_ivp(lambda time, state: model.rhs(time, state, inputs(time)),
                    (0.0, duration), initial, t_eval=t, method=method,
                    rtol=1e-6, atol=np.tile([100.0, 100.0, 1e-8, 1e-7], len(model.channels)))
    if not sol.success:
        raise RuntimeError(sol.message)
    return sol.t, sol.y.T
