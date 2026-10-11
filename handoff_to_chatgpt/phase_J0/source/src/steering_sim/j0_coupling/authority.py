"""Per-channel valve command polarity and static force authority probe.

``04_INTERFACES_AND_RISKS.md`` forbids assuming that a positive valve command
produces positive motion, and requires the front SC_1 table family and the rear
family to be identified separately.  For every channel this module measures:

* the sign of the initial piston acceleration produced by a small command
  perturbation from the pre-charged working point.  This is the same observable
  the L1-Fast acceptance test uses
  (``test_small_autonomous_step_has_expected_initial_motion_direction``).
* the steady hydraulic-force window at the working point, obtained with the
  piston motion prescribed to zero so that only the chamber pressures relax.
  The window is what decides whether a channel can hold a steering load at all.
* the reachable half-line: which signs of ``x`` the valve can actually drive.

The probe is read-only with respect to the hydraulic model.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from steering_sim.hydraulics_lumped import (HydraulicInput, LumpedHydraulicSystem,
                                            evaluate_hydraulic)
from steering_sim.hydraulics_lumped.simulation import simulate_rk4

WORKING_POINT_DELTA = 0.01
SETTLE_DURATION_S = 0.50
PROBE_DURATION_S = 0.02


@dataclass(frozen=True, slots=True)
class ChannelAuthority:
    index: int
    channel: str
    valve_alias: str
    actuator_alias: str
    neutral_command: float
    acceleration_at_plus: float
    acceleration_at_minus: float
    d_acceleration_over_d_command: float
    force_window_n: tuple[float, float]
    reachable_x_signs: tuple[int, ...]
    notes: tuple[str, ...]

    @property
    def bidirectional(self) -> bool:
        return set(self.reachable_x_signs) == {-1, 1}


def working_point(model: LumpedHydraulicSystem) -> tuple[np.ndarray, tuple[float, ...]]:
    """L1-Fast pre-charged healthy working point (same arithmetic as the acceptance test)."""
    state = np.zeros(model.state_count)
    loads: list[float] = []
    for index, channel in enumerate(model.channels):
        pressure = channel.supply.regulated_return_rail_pressure
        state[4 * index:4 * index + 4] = (pressure, pressure, 0.0, 0.0)
        loads.append(channel.actuator.area_a * pressure - channel.actuator.area_b * pressure)
    return state, tuple(loads)


def _motion(model: LumpedHydraulicSystem) -> dict[str, tuple[float, float, float]]:
    return {channel.actuator_alias: (0.0, 0.0, 0.0) for channel in model.channels}


def _inputs(model: LumpedHydraulicSystem, commands: list[float],
            loads: tuple[float, ...], prescribed: bool = False) -> HydraulicInput:
    speeds = tuple(channel.pump.nominal_speed for channel in model.channels)
    return HydraulicInput(tuple(commands), speeds, loads,
                          prescribed_motion_by_alias=_motion(model) if prescribed else None)


def steady_force(model: LumpedHydraulicSystem, index: int, command: float,
                 neutral_commands: tuple[float, float, float, float],
                 duration_s: float = SETTLE_DURATION_S) -> float:
    """Steady hydraulic force with the piston motion prescribed to zero."""
    state, _ = working_point(model)
    commands = [float(value) for value in neutral_commands]
    commands[index] = float(command)
    loads = (0.0,) * 4
    inputs = _inputs(model, commands, loads, prescribed=True)
    system_inputs = inputs.to_system_inputs()
    times, states = simulate_rk4(model, duration_s, 5.0e-4, lambda _t: system_inputs, state)
    _, outputs = evaluate_hydraulic(model, times[-1], states[-1], inputs)
    return float(outputs.channels[index].hydraulic_force_n)


def short_run_response(model: LumpedHydraulicSystem, index: int, command: float,
                       neutral_commands: tuple[float, float, float, float],
                       duration_s: float = PROBE_DURATION_S) -> tuple[float, float]:
    """Free 20 ms run; return ``(v, x)`` of the perturbed channel.

    The instantaneous piston acceleration is identically zero at the pre-charged
    working point (the hydraulic force exactly cancels the working-point load),
    so the direction must be read from a short integration.  This is the same
    observable as the L1-Fast acceptance test, which uses a 50 ms window.
    """
    state, loads = working_point(model)
    commands = [float(value) for value in neutral_commands]
    commands[index] = float(command)
    speeds = tuple(channel.pump.nominal_speed for channel in model.channels)
    inputs = HydraulicInput(tuple(commands), speeds, loads).to_system_inputs()
    _, states = simulate_rk4(model, duration_s, 5.0e-4, lambda _t: inputs, state)
    return float(states[-1, 4 * index + 3]), float(states[-1, 4 * index + 2])


def probe_channel_authority(model: LumpedHydraulicSystem, *,
                            neutral_commands: tuple[float, float, float, float],
                            delta: float = WORKING_POINT_DELTA,
                            force_samples: int = 5,
                            settle_duration_s: float = SETTLE_DURATION_S
                            ) -> tuple[ChannelAuthority, ...]:
    results: list[ChannelAuthority] = []
    for index, channel in enumerate(model.channels):
        neutral = float(neutral_commands[index])
        responses: list[float] = []
        for sign in (1, -1):
            velocity, _ = short_run_response(model, index, neutral + sign * delta,
                                             neutral_commands)
            responses.append(velocity)
        plus, minus = responses
        slope = (plus - minus) / (2.0 * delta)

        low, high = min(-1.0, neutral), max(1.0, neutral)
        window = [steady_force(model, index, float(u), neutral_commands,
                              duration_s=settle_duration_s)
                  for u in np.linspace(low, high, force_samples)]
        force_lo, force_hi = float(min(window)), float(max(window))

        signs: list[int] = []
        if plus > 0.0:
            signs.append(1)
        if minus < 0.0:
            signs.append(-1)
        notes: list[str] = []
        if not signs:
            notes.append("ZERO_INITIAL_COMMAND_AUTHORITY")
        elif len(signs) == 1:
            notes.append("ONE_QUADRANT_INITIAL_AUTHORITY")
        if force_hi - force_lo < 100.0:
            notes.append("NEGLIGIBLE_STATIC_FORCE_AUTHORITY")
        results.append(ChannelAuthority(
            index=index,
            channel=channel.name,
            valve_alias="+".join(channel.valve_aliases),
            actuator_alias=channel.actuator_alias,
            neutral_command=neutral,
            acceleration_at_plus=plus,
            acceleration_at_minus=minus,
            d_acceleration_over_d_command=slope,
            force_window_n=(force_lo, force_hi),
            reachable_x_signs=tuple(signs),
            notes=tuple(notes),
        ))
    return tuple(results)


def authority_as_dict(authority: ChannelAuthority) -> dict[str, object]:
    return {
        "channel": authority.channel,
        "valve_alias": authority.valve_alias,
        "actuator_alias": authority.actuator_alias,
        "neutral_command": authority.neutral_command,
        "d_acceleration_over_d_command": authority.d_acceleration_over_d_command,
        "acceleration_at_plus": authority.acceleration_at_plus,
        "acceleration_at_minus": authority.acceleration_at_minus,
        "force_window_n": list(authority.force_window_n),
        "reachable_x_signs": list(authority.reachable_x_signs),
        "bidirectional": authority.bidirectional,
        "notes": list(authority.notes),
    }


def assert_authority_matches_config(authorities: tuple[ChannelAuthority, ...],
                                    expected_signs: tuple[float, float, float, float],
                                    tolerance: float = 1.0e-12) -> None:
    """Fail loudly if the measured command polarity contradicts the configuration."""
    for authority, expected in zip(authorities, expected_signs):
        measured = math.copysign(1.0, authority.d_acceleration_over_d_command)
        if abs(authority.d_acceleration_over_d_command) <= tolerance:
            raise ValueError(f"{authority.channel}: measured zero command authority")
        if measured != math.copysign(1.0, expected):
            raise ValueError(
                f"{authority.channel}: configured command polarity {expected:+.0f} "
                f"contradicts the measured {measured:+.0f}")
