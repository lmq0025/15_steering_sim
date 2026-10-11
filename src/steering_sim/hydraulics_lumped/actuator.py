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
    # HJ020/HJ021 use the connected mechanical displacement with the opposite
    # sign to internal piston travel: xact = c2 - x.  Consequently increasing
    # mechanical x reduces chamber 1 and increases chamber 2.  This convention
    # is source-verified (HJ020.c lines 462, 516 and 525) and is essential when
    # replaying the Amesim mechanical boundary.
    return p.volume_a0 - p.area_a * x, p.volume_b0 + p.area_b * x


def actuator_rates(p_a: float, p_b: float, x: float, v: float, q_a: float, q_b: float,
                   load_force: float, actuator: ActuatorParameters, fluid: FluidParameters) -> ActuatorRates:
    va, vb = chamber_volumes(x, actuator)
    if va <= 0.0 or vb <= 0.0:
        raise ValueError("non-positive chamber volume")
    leakage = actuator.leakage * (p_a - p_b)
    # Exact HJ020 continuity signs (q0top=1 engineering surrogate):
    # inflow1 = q1 + A1*v - qleak; inflow2 = q2 - A2*v + qleak.
    dp_a = fluid.bulk_modulus / va * (q_a + actuator.area_a * v - leakage)
    dp_b = fluid.bulk_modulus / vb * (q_b - actuator.area_b * v + leakage)
    # J0-R1 F1 修正：力的方向必须与上面的容积约定自洽。
    # chamber_volumes 给出 V_a = V_a0 - A_a*x、V_b = V_b0 + A_b*x，也就是
    # x 增大压缩 A 腔、扩张 B 腔；因此 A 腔压力把活塞推向 -x，B 腔压力推向 +x。
    # 修正前写作 area_a*p_a - area_b*p_b，与容积约定相反，导致液压刚度与阻尼
    # 同时取发散符号（dF/dx > 0、dF/dv > 0）。
    # 容积与压力连续性方程本身自洽（dp = (beta/V)(q - Vdot)），未作改动。
    force = actuator.area_b * p_b - actuator.area_a * p_a
    friction = actuator.friction_force * (1.0 if v > 0.0 else -1.0 if v < 0.0 else 0.0)
    limit = actuator.stroke / 2.0
    endstop = 0.0
    if x > limit:
        endstop = actuator.endstop_stiffness * (x - limit) + actuator.endstop_damping * max(v, 0.0)
    elif x < -limit:
        endstop = actuator.endstop_stiffness * (x + limit) + actuator.endstop_damping * min(v, 0.0)
    dv = (force - actuator.viscous_damping * v - friction - load_force - endstop) / actuator.moving_mass
    return ActuatorRates(dp_a, dp_b, v, dv, force, va, vb)
