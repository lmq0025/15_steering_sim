"""J0 minimum test set, items 9, 11, 14: control cadence, x-driven wheel angles,
and repeatable full-case runs.

Scope note (PHASE J0 close-out): the J0 layer itself -- mapping, closed chain,
road load, virtual work, PID cadence -- is exercised here and passes.  The
*closed-loop tracking* capability is deliberately recorded as an ``xfail``
(``test_four_channel_loop_tracks_the_j0_reference``) because it is blocked by a
defect in the delivered L1-Fast V1 hydraulic plant, not by anything in this
layer.  See ``docs/handoff/J0_claude/05_J0_PLANT_DEFECT_AND_KNOWN_RISKS.md``.
Do not weaken these assertions to make the loop "pass".
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from steering_sim.control.base import Measurement, Reference
from steering_sim.control.pid import PIDController
from steering_sim.j0_coupling.config import J0CaseConfig, load_j0_config
from steering_sim.j0_coupling.runner import J0Runner


# --------------------------------------------------------------- item 9: PID
def test_pid_clamps_to_the_configured_limit():
    controller = PIDController(kp=1000.0, ki=0.0, kd=0.0, limit=0.35)
    command = controller.step(Measurement(np.array([0.0])), Reference(np.array([1.0])), 0.01)
    assert command.values[0] == pytest.approx(0.35)


def test_pid_conditional_integration_prevents_windup():
    """Item 9: while the output is saturated the integrator must not keep filling."""
    controller = PIDController(kp=0.0, ki=1.0, kd=0.0, limit=0.1)
    for _ in range(200):
        controller.step(Measurement(np.array([0.0])), Reference(np.array([1.0])), 0.01)
    # Without conditional integration the integral would have reached 2.0 after
    # 200 steps of a unit error; the anti-windup condition holds it at the limit.
    assert controller._integral[0] <= 0.1 + 1.0e-9
    # Once the error reverses, the stored integral is spent immediately and the
    # output backs out of saturation on the first sample.
    command = controller.step(Measurement(np.array([2.0])), Reference(np.array([1.0])), 0.01)
    assert command.values[0] < 0.1
    assert controller._integral[0] < 0.1


def test_control_period_is_an_integer_multiple_of_the_hydraulic_step(j0_config):
    """Item 9: 10 ms control on a 0.5 ms hydraulic step, so 20 substeps."""
    assert j0_config.dt_hydraulic_s == 5.0e-4
    assert j0_config.dt_control_s == 1.0e-2
    assert j0_config.substeps_per_control == 20


def test_command_window_is_respected_for_the_front_channel(j0_config):
    """The front channel command window is [0, 1]; the rear family is [-1, 1]."""
    front = j0_config.channel("channel_front")
    assert front.neutral_command == 1.0
    assert (front.command_min, front.command_max) == (0.0, 1.0)
    assert front.command_from_pid(+1.0) == 1.0
    assert front.command_from_pid(-1.0) == 0.0
    for item in j0_config.channels[1:]:
        assert item.neutral_command == 0.0
        assert item.command_from_pid(1.0) == 1.0
        assert item.command_from_pid(-1.0) == -1.0


# ------------------------------------------------- item 11: x drives the angles
@pytest.mark.slow
def test_actual_wheel_angles_follow_the_actual_stroke(runner, j0_config):
    """Item 11: forcing x away from the reference changes the wheel angles."""
    q_ref = runner.target(j0_config.cases[1])["q_ref"]
    forced = 0.5 * q_ref["q4"]
    x_forced = runner.geometry.representative_stroke("q4", forced)
    q_now, status = runner.geometry.q_from_strokes(
        {"channel_front": 0.0, "channel_rear_1": x_forced,
         "channel_rear_2": 0.0, "channel_rear_3": 0.0})
    assert all(item.ok for item in status.values())
    angles = runner.geometry.wheel_angles_deg(q_now)
    assert abs(angles["axle4_left"]) > 1.0e-3
    assert not math.isclose(angles["axle4_left"],
                            runner.geometry.wheel_angles_deg(q_ref)["axle4_left"],
                            abs_tol=1e-6)


def test_reference_is_a_stroke_not_a_wheel_angle(runner, j0_config):
    """The PID reference is the representative stroke of each group."""
    target = runner.target(j0_config.cases[1])
    assert set(target["x_ref"]) == {"channel_front", "channel_rear_1",
                                    "channel_rear_2", "channel_rear_3"}
    strokes = runner.geometry.seven_cylinder_strokes(target["q_ref"])
    assert target["x_ref"]["channel_front"] == pytest.approx(strokes["front_group_1"])
    assert target["x_ref"]["channel_rear_1"] == pytest.approx(strokes["axle4_A"])
    assert target["x_ref"]["channel_rear_2"] == pytest.approx(strokes["axle5_A"])
    assert target["x_ref"]["channel_rear_3"] == pytest.approx(strokes["axle6_A"])


# ------------------------------------------------------------ item 14: the runs
def _short_case(case, duration=0.05):
    return J0CaseConfig(id=case.id, target_outer_angle_deg=case.target_outer_angle_deg,
                        speed_kmh=case.speed_kmh, duration_s=duration)


@pytest.mark.slow
def test_straight_case_records_the_full_output_set(runner, j0_config):
    """Item 14: a 0 deg run produces the full 12-wheel / 7-cylinder record."""
    result = runner.run_case(_short_case(j0_config.cases[0]))
    samples = result.samples
    for wheel in ("axle1_left", "axle3_right", "axle6_right"):
        assert f"wheel_{wheel}_actual_deg" in samples
        assert f"wheel_{wheel}_target_deg" in samples
    for name in ("front_group_1", "axle4_A", "axle4_B", "axle5_A", "axle5_B",
                 "axle6_A", "axle6_B"):
        assert f"cylinder_{name}_stroke_m" in samples
    for item in j0_config.channels:
        for suffix in ("_pA_mpa_g", "_pB_mpa_g", "_hydraulic_force_n", "_load_force_n",
                       "_valve_command", "_dx_dq_m_per_rad", "_Q_road_nm", "_x_m",
                       "_v_m_s", "_flow_a_m3_s"):
            assert f"{item.channel}{suffix}" in samples
    assert "max_link_residual_m" in samples
    assert np.all(np.isfinite(samples["time_s"]))


@pytest.mark.slow
def test_straight_case_holds_zero_without_spurious_wheel_angle(runner, j0_config):
    result = runner.run_case(_short_case(j0_config.cases[0], duration=0.2))
    assert result.completed, result.failure_reason
    for wheel in ("axle1_left", "axle1_right", "axle2_left", "axle2_right",
                  "axle3_left", "axle3_right", "axle4_left", "axle4_right",
                  "axle5_left", "axle5_right", "axle6_left", "axle6_right"):
        assert float(np.max(np.abs(result.samples[f"wheel_{wheel}_actual_deg"]))) < 1.0e-6
    assert result.summary["third_axle_max_abs_deg"] == 0.0
    assert result.summary["max_link_residual_m"] <= 1.0e-9


@pytest.mark.slow
def test_delivered_plant_diverges_and_the_runner_reports_a_stop_condition(runner, j0_config):
    """Pinned finding: the delivered L1-Fast V1 plant cannot hold the J0 loop.

    The runner must stop the case and say why rather than reporting a plausible
    result.  Both the finite piston travel of the L1-Fast actuator and the
    negative hydraulic damping contribute; the exact stop reason is recorded.

    This is the defect-regression guard, not a capability test: it asserts the
    documented behaviour of the delivered plant.  See
    ``docs/handoff/J0_claude/05_J0_PLANT_DEFECT_AND_KNOWN_RISKS.md`` (F1).
    """
    result = runner.run_case(_short_case(j0_config.cases[1], duration=1.0))
    assert not result.completed
    assert result.summary["status"] == "FAIL"
    assert result.failure_time_s is not None and result.failure_time_s <= 1.0
    assert result.failure_reason
    assert result.summary["status_notes"]


@pytest.mark.skip(reason=(
    "Diagnostic only, and no longer exercised as a test.  The chain runs to "
    "completion only with an artificial mechanical damper added on top of the "
    "plant (scripts/j0/run_j0.py --diagnostic-damping).  That is a probe of the "
    "J0 pipeline, not a capability of L1-Fast V1; the evidence is kept in "
    "outputs/j0_diag/.  See "
    "docs/handoff/J0_claude/05_J0_PLANT_DEFECT_AND_KNOWN_RISKS.md (F1)."))
def test_diagnostic_damping_stabilises_the_loop_structure(runner, j0_config):
    result = runner.run_case(_short_case(j0_config.cases[1], duration=0.5),
                             diagnostic_damping_n_s_per_m=3.0e6)
    assert result.completed, result.failure_reason


@pytest.mark.slow
@pytest.mark.xfail(strict=True, reason=(
    "BLOCKED BY F1: L1-Fast V1 has dF_hyd/dv > 0 and dF_hyd/dx > 0 on all four "
    "channels, so any non-zero valve command diverges within 0.03-0.2 s and no "
    "gain set closes the loop (19 of 20 tested gain sets fail; the only one that "
    "runs is kp=ki=kd=0, which does nothing).  This marker must be removed once "
    "the actuator sign convention is resolved.  See "
    "docs/handoff/J0_claude/05_J0_PLANT_DEFECT_AND_KNOWN_RISKS.md."))
def test_four_channel_loop_tracks_the_j0_reference(runner, j0_config):
    """The capability PHASE J0 was meant to deliver.

    Recorded as an expected failure so the gap stays visible in the suite rather
    than being papered over by a weakened assertion.
    """
    result = runner.run_case(_short_case(j0_config.cases[1], duration=2.0))
    assert result.completed, result.failure_reason
    assert result.summary["status"] in {"PASS", "CONDITIONAL"}
    assert result.summary["max_stroke_error_m"] <= 1.0e-3


@pytest.mark.slow
def test_run_is_repeatable(j0_config, m1_model):
    """Item 14: two runs of the same case reproduce identical samples."""
    runner = J0Runner(j0_config, m1_model, probe_authority=False)
    case = _short_case(j0_config.cases[0], duration=0.1)
    first = runner.run_case(case)
    second = runner.run_case(case)
    for key in ("channel_front_x_m", "channel_rear_1_x_m", "time_s"):
        assert np.array_equal(first.samples[key], second.samples[key])
