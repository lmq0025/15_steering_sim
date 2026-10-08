"""Central LEVEL C engineering surrogates for Amesim runtime functions.

These functions are intentionally isolated so Phase 2 numeric probes can
replace them without changing individual component equations.
"""

from __future__ import annotations

import math

LEVEL = "LEVEL C SURROGATE"


def q0top(_pressure_pa: float) -> float:
    """Phase-1 substitute for Amesim q0top_: reference-volume ratio = 1."""
    return 1.0


def chamber_pressure_rhs(bulk_modulus_pa: float, volume_m3: float, net_flow_m3_s: float) -> float:
    if bulk_modulus_pa <= 0.0 or volume_m3 <= 0.0:
        raise ValueError("bulk modulus and chamber volume must be positive")
    return bulk_modulus_pa / volume_m3 * net_flow_m3_s


def regularized_orifice_flow(
    pressure_drop_pa: float,
    area_m2: float,
    density_kg_m3: float,
    discharge_coefficient: float = 0.7,
    smoothing_pressure_pa: float = 10.0,
) -> float:
    """Smooth odd approximation to Cd*A*sign(dp)*sqrt(2*abs(dp)/rho)."""
    if area_m2 < 0.0 or density_kg_m3 <= 0.0 or discharge_coefficient < 0.0:
        raise ValueError("area/Cd must be nonnegative and density positive")
    if smoothing_pressure_pa <= 0.0:
        raise ValueError("smoothing pressure must be positive")
    dp = float(pressure_drop_pa)
    # dp/(dp^2+eps^2)^1/4 is linear at zero and asymptotic to sign(dp)*sqrt(abs(dp)).
    smooth_root = dp / (dp * dp + smoothing_pressure_pa**2) ** 0.25
    return discharge_coefficient * area_m2 * math.sqrt(2.0 / density_kg_m3) * smooth_root


def pipe_pressure_drop(flow_m3_s: float, laminar_resistance_pa_s_m3: float, quadratic_resistance_pa_s2_m6: float) -> float:
    q = float(flow_m3_s)
    if laminar_resistance_pa_s_m3 < 0.0 or quadratic_resistance_pa_s2_m6 < 0.0:
        raise ValueError("pipe resistance coefficients must be nonnegative")
    return laminar_resistance_pa_s_m3 * q + quadratic_resistance_pa_s2_m6 * q * abs(q)


def pipe_flow_from_pressure_drop(pressure_drop_pa: float, laminar_resistance_pa_s_m3: float, quadratic_resistance_pa_s2_m6: float) -> float:
    dp = float(pressure_drop_pa)
    r, k = float(laminar_resistance_pa_s_m3), float(quadratic_resistance_pa_s2_m6)
    if r < 0.0 or k < 0.0 or (r == 0.0 and k == 0.0):
        raise ValueError("at least one nonnegative resistance coefficient must be nonzero")
    if k == 0.0:
        return dp / r
    magnitude = (math.sqrt(r * r + 4.0 * k * abs(dp)) - r) / (2.0 * k)
    return math.copysign(magnitude, dp)
