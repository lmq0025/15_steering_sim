"""Arrival and sustained-settling metrics from real J1-R2 time series."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd

from steering_sim.j0_coupling.runner import CHANNEL_ORDER, WHEELS


NOT_SETTLED = "NOT_SETTLED_WITHIN_HORIZON"


@dataclass(frozen=True)
class ResponseCriteria:
    wheel_angle_tolerance_deg: float = 0.10
    cylinder_position_tolerance_m: float = 0.00020
    wheel_speed_threshold_deg_s: float = 0.02
    piston_speed_threshold_m_s: float = 0.0010
    settled_observation_s: float = 2.0
    maximum_hold_observation_s: float = 10.0
    slow_ramp_hydraulic_step_s: float = 0.002

    def __post_init__(self) -> None:
        for name in ("wheel_angle_tolerance_deg", "cylinder_position_tolerance_m",
                     "wheel_speed_threshold_deg_s", "piston_speed_threshold_m_s",
                     "settled_observation_s", "maximum_hold_observation_s",
                     "slow_ramp_hydraulic_step_s"):
            if not np.isfinite(getattr(self, name)) or getattr(self, name) <= 0.0:
                raise ValueError(f"{name} must be finite and positive")

    @classmethod
    def load(cls, path: str | Path) -> "ResponseCriteria":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(**{name: raw[name] for name in cls.__dataclass_fields__ if name in raw})


def linear_ramp_profile(duration_s: float):
    """Return normalized position/rate for an exact linear ramp."""
    duration = float(duration_s)
    if duration < 0:
        raise ValueError("ramp duration must be non-negative")

    def profile(time_s: float) -> tuple[float, float]:
        if duration == 0.0:
            return 1.0, 0.0
        if time_s <= 0.0:
            return 0.0, 1.0 / duration
        if time_s < duration:
            return time_s / duration, 1.0 / duration
        return 1.0, 0.0
    return profile


def _first_time(time: np.ndarray, mask: np.ndarray, start_s: float) -> float | None:
    indexes = np.flatnonzero((time >= start_s - 1.0e-12) & mask)
    return None if not len(indexes) else float(time[indexes[0]])


def _settled_time(time: np.ndarray, stable: np.ndarray, start_s: float,
                  observation_s: float) -> float | None:
    eligible = (time >= start_s - 1.0e-12) & stable
    indexes = np.flatnonzero(eligible)
    if not len(indexes):
        return None
    run_start = indexes[0]
    previous = indexes[0]
    for index in indexes[1:]:
        if index != previous + 1:
            if time[previous] - time[run_start] >= observation_s - 1.0e-9:
                return float(time[run_start])
            run_start = index
        previous = index
    if time[previous] - time[run_start] >= observation_s - 1.0e-9:
        return float(time[run_start])
    return None


def analyze_response(samples: Mapping[str, np.ndarray], command_completion_s: float,
                     criteria: ResponseCriteria) -> dict:
    time = np.asarray(samples["time_s"], dtype=float)
    if time.size < 2:
        raise ValueError("response analysis requires at least two time samples")
    wheel_rows, cylinder_rows = [], []
    wheel_stable_masks = []
    cylinder_stable_masks = []
    for wheel in WHEELS:
        target = np.asarray(samples[f"wheel_{wheel}_command_deg"], dtype=float)
        actual = np.asarray(samples[f"wheel_{wheel}_actual_deg"], dtype=float)
        final_target = float(target[-1])
        error = np.abs(actual - final_target)
        speed = np.abs(np.gradient(actual, time))
        position_ok = error <= criteria.wheel_angle_tolerance_deg
        stable = position_ok & (speed <= criteria.wheel_speed_threshold_deg_s)
        arrival = _first_time(time, position_ok, command_completion_s)
        settled = _settled_time(time, stable, command_completion_s,
                                criteria.settled_observation_s)
        wheel_stable_masks.append(stable)
        wheel_rows.append({
            "wheel": wheel, "final_target_deg": final_target,
            "final_actual_deg": float(actual[-1]),
            "maximum_tracking_error_deg": float(np.max(np.abs(actual - target))),
            "first_arrival_s": arrival,
            "settled_time_s": settled,
            "settled_status": "SETTLED" if settled is not None else NOT_SETTLED,
            "final_speed_deg_s": float(np.gradient(actual, time)[-1]),
        })
    for channel in CHANNEL_ORDER:
        target = np.asarray(samples[f"{channel}_x_ref_eff_m"], dtype=float)
        actual = np.asarray(samples[f"{channel}_x_m"], dtype=float)
        velocity = np.asarray(samples[f"{channel}_v_m_s"], dtype=float)
        final_target = float(target[-1])
        error = np.abs(actual - final_target)
        position_ok = error <= criteria.cylinder_position_tolerance_m
        stable = position_ok & (np.abs(velocity) <= criteria.piston_speed_threshold_m_s)
        arrival = _first_time(time, position_ok, command_completion_s)
        settled = _settled_time(time, stable, command_completion_s,
                                criteria.settled_observation_s)
        cylinder_stable_masks.append(stable)
        cylinder_rows.append({
            "channel": channel, "final_target_m": final_target,
            "final_actual_m": float(actual[-1]),
            "final_error_m": float(actual[-1] - final_target),
            "first_arrival_s": arrival,
            "settled_time_s": settled,
            "settled_status": "SETTLED" if settled is not None else NOT_SETTLED,
            "final_velocity_m_s": float(velocity[-1]),
        })
    wheels_common = _settled_time(
        time, np.logical_and.reduce(wheel_stable_masks), command_completion_s,
        criteria.settled_observation_s)
    cylinders_common = _settled_time(
        time, np.logical_and.reduce(cylinder_stable_masks), command_completion_s,
        criteria.settled_observation_s)
    system_common = _settled_time(
        time, np.logical_and.reduce(wheel_stable_masks + cylinder_stable_masks),
        command_completion_s, criteria.settled_observation_s)
    return {
        "command_completion_s": float(command_completion_s),
        "wheel_table": pd.DataFrame(wheel_rows),
        "cylinder_table": pd.DataFrame(cylinder_rows),
        "all_wheels_settled_s": wheels_common,
        "all_cylinders_settled_s": cylinders_common,
        "system_settled_s": system_common,
        "system_status": "SETTLED" if system_common is not None else NOT_SETTLED,
        "criteria": criteria,
    }
