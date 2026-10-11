from __future__ import annotations

from dataclasses import dataclass

from .parameters import ActuatorParameters, FluidParameters


@dataclass(frozen=True)
class ActuatorRates:
    dp_a: float
    dp_b: float
    dx: float
    dv: float
    hydraulic_force: float
    volume_a: float
    volume_b: float


def chamber_volumes(x: float, p: ActuatorParameters) -> tuple[float, float]:
    return p.volume_a0 + p.area_a * x, p.volume_b0 - p.area_b * x


def actuator_rates(p_a: float, p_b: float, x: float, v: float, q_a: float, q_b: float,
                   load_force: float, actuator: ActuatorParameters, fluid: FluidParameters) -> ActuatorRates:
    va, vb = chamber_volumes(x, actuator)
    if va <= 0.0 or vb <= 0.0:
        raise ValueError("non-positive chamber volume")
    leakage = actuator.leakage * (p_a - p_b)
    dp_a = fluid.bulk_modulus / va * (q_a - actuator.area_a * v - leakage)
    dp_b = fluid.bulk_modulus / vb * (q_b + actuator.area_b * v + leakage)
    force = actuator.area_a * p_a - actuator.area_b * p_b
    friction = actuator.friction_force * (1.0 if v > 0.0 else -1.0 if v < 0.0 else 0.0)
    limit = actuator.stroke / 2.0
    endstop = 0.0
    if x > limit:
        endstop = actuator.endstop_stiffness * (x - limit) + actuator.endstop_damping * max(v, 0.0)
    elif x < -limit:
        endstop = actuator.endstop_stiffness * (x + limit) + actuator.endstop_damping * min(v, 0.0)
    dv = (force - actuator.viscous_damping * v - friction - load_force - endstop) / actuator.moving_mass
    return ActuatorRates(dp_a, dp_b, v, dv, force, va, vb)
