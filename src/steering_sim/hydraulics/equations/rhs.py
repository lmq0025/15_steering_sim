from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from ..elements.cylinder import DoubleActingCylinder


def actuator_mass_rhs(cylinder: DoubleActingCylinder, mass_kg: float, load_force_n: float, state: NDArray[np.float64], q1_into_m3_s: float, q2_into_m3_s: float) -> NDArray[np.float64]:
    p1, p2, x, v = map(float, state)
    dp1, dp2 = cylinder.pressure_rhs_pa_s(p1, p2, q1_into_m3_s, q2_into_m3_s, x, v)
    acceleration = (cylinder.force_n(p1, p2, v, x) - load_force_n) / mass_kg
    return np.array([dp1, dp2, v, acceleration], dtype=float)
