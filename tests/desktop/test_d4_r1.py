from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from steering_sim.desktop.response_analysis import (
    NOT_SETTLED, ResponseCriteria, analyze_response, linear_ramp_profile)
from steering_sim.j0_coupling.runner import CHANNEL_ORDER, WHEELS


ROOT = Path(__file__).resolve().parents[2]


def _synthetic(oscillating: bool = False) -> dict[str, np.ndarray]:
    time = np.arange(0.0, 10.01, 0.01)
    samples: dict[str, np.ndarray] = {"time_s": time}
    command = np.minimum(time / 4.0, 1.0)
    actual = np.where(time < 4.0, command - 0.02, 1.0)
    if oscillating:
        actual = np.where(time >= 4.0, 1.0 + 0.08 * np.sin(8 * time), actual)
    for wheel in WHEELS:
        samples[f"wheel_{wheel}_command_deg"] = command.copy()
        samples[f"wheel_{wheel}_actual_deg"] = actual.copy()
    for channel in CHANNEL_ORDER:
        samples[f"{channel}_x_ref_eff_m"] = command * 0.01
        samples[f"{channel}_x_m"] = actual * 0.01
        samples[f"{channel}_v_m_s"] = np.gradient(actual * 0.01, time)
    return samples


def test_bat_is_ascii_crlf_and_uses_diagnostic_launcher():
    payload = (ROOT / "start_steering_desktop.bat").read_bytes()
    assert all(value < 128 for value in payload)
    assert b"\r\n" in payload and b"\n" not in payload.replace(b"\r\n", b"")
    assert b"launch_desktop.py" in payload
    assert b"Library\\bin" in payload


def test_six_seconds_per_degree_ramp_math_and_signs():
    forward = linear_ramp_profile(60.0)
    reverse = linear_ramp_profile(120.0)
    assert forward(0) == (0.0, 1 / 60)
    assert forward(30) == (0.5, 1 / 60)
    assert forward(60) == (1.0, 0.0)
    assert reverse(60) == (0.5, 1 / 120)
    # Direction is carried by the final-minus-initial stroke delta, so the
    # normalized profile remains monotone for positive, negative and cross-zero moves.
    assert (-10 - 10) * reverse(60)[0] == -10


def test_arrival_and_settled_are_distinct_and_use_sustained_window():
    criteria = ResponseCriteria(wheel_angle_tolerance_deg=0.05,
                                wheel_speed_threshold_deg_s=0.05,
                                settled_observation_s=2.0)
    result = analyze_response(_synthetic(), 4.0, criteria)
    assert result["wheel_table"].iloc[0]["first_arrival_s"] == 4.0
    assert result["wheel_table"].iloc[0]["settled_time_s"] >= 4.0
    assert result["system_status"] == "SETTLED"


def test_oscillation_does_not_settle_early():
    criteria = ResponseCriteria(wheel_angle_tolerance_deg=0.1,
                                wheel_speed_threshold_deg_s=0.05,
                                settled_observation_s=2.0)
    result = analyze_response(_synthetic(oscillating=True), 4.0, criteria)
    assert result["system_status"] == NOT_SETTLED
    assert result["system_settled_s"] is None


def test_response_tables_cover_real_model_dimensions():
    result = analyze_response(_synthetic(), 4.0, ResponseCriteria())
    assert list(result["wheel_table"]["wheel"]) == list(WHEELS)
    assert list(result["cylinder_table"]["channel"]) == list(CHANNEL_ORDER)
    assert len(result["wheel_table"]) == 12
    assert len(result["cylinder_table"]) == 4


def test_zero_target_wheels_are_handled_by_absolute_tolerance():
    samples = _synthetic()
    for wheel in ("axle3_left", "axle3_right"):
        samples[f"wheel_{wheel}_command_deg"][:] = 0.0
        samples[f"wheel_{wheel}_actual_deg"][:] = 0.0
    result = analyze_response(samples, 4.0, ResponseCriteria())
    third = result["wheel_table"].query("wheel in ['axle3_left', 'axle3_right']")
    assert (third["settled_status"] == "SETTLED").all()
    assert (third["final_target_deg"] == 0.0).all()


def test_response_criteria_reject_nonphysical_values():
    with pytest.raises(ValueError, match="wheel_angle_tolerance_deg"):
        ResponseCriteria(wheel_angle_tolerance_deg=-0.1)
    with pytest.raises(ValueError, match="settled_observation_s"):
        ResponseCriteria(settled_observation_s=0.0)
