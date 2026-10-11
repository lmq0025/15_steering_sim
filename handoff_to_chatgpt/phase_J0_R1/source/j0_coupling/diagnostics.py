"""Read-only characterisation of the delivered L1-Fast V1 plant behaviour.

These are the J0 "hydraulic sanity" checks required by
``03_J0_IMPLEMENTATION_BRIEF.md`` section 10.7 and section 10.13.  Nothing here
writes to the hydraulic model.

Three independent observables are produced for every channel:

``dF/dv``  slope of hydraulic force against piston velocity under a prescribed
           1 Hz motion.  A passive actuator must return a *negative* slope
           (positive damping); a positive slope means the channel injects
           energy.
``dF/dx``  slope of hydraulic force against piston displacement under a slow
           prescribed motion.  A chamber that is compressed by positive ``x``
           must return a *negative* slope (a restoring spring).
``force_window``  the steady hydraulic force reachable over the full command
           range with the piston motion prescribed to zero: the static force
           authority of the channel.

The prescribed-motion form is used on purpose: it separates the constitutive
behaviour from the integration stability question, so the result does not
depend on the hydraulic step size.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from steering_sim.hydraulics_lumped import (HydraulicInput, LumpedHydraulicSystem,
                                            evaluate_hydraulic)
from steering_sim.hydraulics_lumped.simulation import simulate_rk4

from .authority import steady_force, working_point

DT_H = 5.0e-4


@dataclass(frozen=True, slots=True)
class PlantCharacterisation:
    channel: str
    valve_alias: str
    command: float
    d_force_d_velocity_n_s_per_m: float
    d_force_d_displacement_n_per_m: float
    force_offset_n: float
    force_window_n: tuple[float, float]
    damping_flag: str
    stiffness_flag: str

    @property
    def flags(self) -> tuple[str, ...]:
        found = []
        if self.d_force_d_velocity_n_s_per_m > 0.0:
            found.append("NEGATIVE_HYDRAULIC_DAMPING")
        if self.d_force_d_displacement_n_per_m > 0.0:
            found.append("NEGATIVE_HYDRAULIC_STIFFNESS")
        return tuple(found)


def _inputs(model: LumpedHydraulicSystem, commands: list[float],
            loads: tuple[float, ...], aliases: list[str],
            amplitude: float, freq: float):
    speeds = tuple(channel.pump.nominal_speed for channel in model.channels)

    def motion(t: float):
        x = amplitude * math.sin(2 * math.pi * freq * t)
        v = amplitude * 2 * math.pi * freq * math.cos(2 * math.pi * freq * t)
        a = -(2 * math.pi * freq) ** 2 * x
        return {alias: (x, v, a) for alias in aliases}

    def builder(t: float) -> HydraulicInput:
        return HydraulicInput(tuple(commands), speeds, loads,
                              prescribed_motion_by_alias=motion(t))
    return builder


def characterise_channel(model: LumpedHydraulicSystem, index: int, command: float,
                         *, amplitude_m: float = 1.0e-4, frequency_hz: float = 1.0,
                         cycles: float = 4.0, loads: tuple[float, ...] | None = None
                         ) -> tuple[float, float, float]:
    """Return ``(dF/dv, dF/dx, offset)`` from a prescribed 1 Hz motion."""
    state, default_loads = working_point(model)
    applied_loads = default_loads if loads is None else loads
    commands = [0.0] * 4
    commands[index] = float(command)
    aliases = [channel.actuator_alias for channel in model.channels]
    builder = _inputs(model, commands, applied_loads, aliases, amplitude_m, frequency_hz)
    duration = cycles / frequency_hz
    # simulate_rk4 consumes the SystemInputs form; evaluate_hydraulic consumes
    # the HydraulicInput form.  Both describe the same boundary.
    times, states = simulate_rk4(model, duration, DT_H,
                                 lambda t: builder(t).to_system_inputs(), state)
    force: list[float] = []
    velocity: list[float] = []
    displacement: list[float] = []
    for time, sample in zip(times, states):
        if time < duration * 0.5:
            continue
        _, outputs = evaluate_hydraulic(model, time, sample, builder(time))
        force.append(float(outputs.channels[index].hydraulic_force_n))
        velocity.append(amplitude_m * 2 * math.pi * frequency_hz
                        * math.cos(2 * math.pi * frequency_hz * time))
        displacement.append(amplitude_m * math.sin(2 * math.pi * frequency_hz * time))
    design = np.column_stack([np.asarray(displacement), np.asarray(velocity),
                              np.ones(len(force))])
    coefficients, *_ = np.linalg.lstsq(design, np.asarray(force), rcond=None)
    return float(coefficients[1]), float(coefficients[0]), float(coefficients[2])


def characterise_plant(model: LumpedHydraulicSystem, *,
                       neutral_commands: tuple[float, float, float, float],
                       force_samples: int = 9) -> tuple[PlantCharacterisation, ...]:
    results: list[PlantCharacterisation] = []
    for index, channel in enumerate(model.channels):
        neutral = float(neutral_commands[index])
        d_f_d_v, d_f_d_x, offset = characterise_channel(model, index, neutral)
        low, high = min(-1.0, neutral), max(1.0, neutral)
        window = [steady_force(model, index, float(u), neutral_commands,
                               duration_s=0.2 if index == 0 else 0.5)
                  for u in np.linspace(low, high, force_samples)]
        results.append(PlantCharacterisation(
            channel=channel.name,
            valve_alias="+".join(channel.valve_aliases),
            command=neutral,
            d_force_d_velocity_n_s_per_m=d_f_d_v,
            d_force_d_displacement_n_per_m=d_f_d_x,
            force_offset_n=offset,
            force_window_n=(float(min(window)), float(max(window))),
            damping_flag="NEGATIVE_HYDRAULIC_DAMPING" if d_f_d_v > 0.0 else "POSITIVE_DAMPING",
            stiffness_flag="NEGATIVE_HYDRAULIC_STIFFNESS" if d_f_d_x > 0.0 else "RESTORING_STIFFNESS",
        ))
    return tuple(results)


def passive_closed_loop_estimate(d_f_d_v: float, d_f_d_x: float,
                                 road_stiffness_n_per_m: float,
                                 equivalent_mass_kg: float = 1000.0) -> dict[str, float]:
    """``m x'' = F_hyd - F_road`` 的线性化稳定性指标。

    记 ``c = dF_hyd/dv``、``k = dF_hyd/dx + dF_road/dx``，则
    ``m δx'' = c δx' + k δx``，特征方程 ``λ^2 - (c/m)λ - (k/m) = 0``，
    根为 ``λ = [c/m ± sqrt((c/m)^2 + 4k/m)] / 2``。

    注意根号内是 **加号**。因此：``c < 0`` 且 ``k < 0``（正的液压阻尼与回复刚度、
    道路负载亦为回复）时两根实部均为负，系统被动稳定；而 ``c > 0``（负阻尼）时
    大根实部必为正，任何正的机械刚度都无法挽回——这正是 J0 阶段的 F1 缺陷。
    """
    c = float(d_f_d_v)
    k = float(d_f_d_x) + float(road_stiffness_n_per_m)
    m = float(equivalent_mass_kg)
    discriminant = (c / m) ** 2 + 4.0 * k / m
    if discriminant >= 0.0:
        root = math.sqrt(discriminant)
        real = 0.5 * (c / m + root)
        growth = real
        return {"kind": "real_roots", "k_eff_n_per_m": k, "c_eff_n_s_per_m": c,
                "max_real_part_1_per_s": growth, "growth_rate_1_per_s": growth}
    real = 0.5 * c / m
    omega = 0.5 * math.sqrt(-discriminant)
    return {"kind": "complex_roots", "k_eff_n_per_m": k, "c_eff_n_s_per_m": c,
            "max_real_part_1_per_s": real, "growth_rate_1_per_s": real,
            "imaginary_part_rad_per_s": omega}
