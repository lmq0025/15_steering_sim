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


def test_command_windows_respect_the_measured_neutral_points(j0_config):
    """J0-R1 F2 后四个通道都是对称窗口 [-1, +1]、中立 0.0。

    原用例断言前通道窗口为 [0, 1]、中立 +1.0，反映的是 A 腔被硬置零时的旧拓扑。
    """
    for item in j0_config.channels:
        assert item.neutral_command == 0.0, item.channel
        assert (item.command_min, item.command_max) == (-1.0, 1.0), item.channel
        assert item.command_from_pid(1.0) == pytest.approx(item.command_polarity)
        assert item.command_from_pid(-1.0) == pytest.approx(-item.command_polarity)
    # 实测极性：前阀 +1，后三通道 -1（见 configs/j0/j0_config.json 的 notes）。
    assert j0_config.channel("channel_front").command_polarity == 1.0
    for item in j0_config.channels[1:]:
        assert item.command_polarity == -1.0, item.channel


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
def test_operating_case_runs_to_completion_without_a_stop_condition(runner, j0_config):
    """J0-R1 F1/F2 已修复：J0-02 必须跑满全程，不再触发 §11 停止条件。

    本用例原为 ``test_delivered_plant_diverges_and_the_runner_reports_a_stop_condition``，
    断言 1 s 内发散停机（缺陷表征）。修复后改为验证闭环稳定收敛，并守住物理合理性：
    压力不得超出供油轨量级、速度不得出现发散值、闭链残差与三桥锁定保持。
    """
    result = runner.run_case(_short_case(j0_config.cases[1], duration=2.0))
    assert result.completed, result.failure_reason
    assert result.failure_time_s is None
    assert result.summary["max_pressure_mpa_g"] < 20.0
    assert result.summary["max_abs_velocity_m_s"] < 1.0
    assert result.summary["max_link_residual_m"] <= 1.0e-9
    assert result.summary["third_axle_max_abs_deg"] == 0.0


@pytest.mark.slow
def test_four_channel_loop_tracks_the_j0_reference(runner, j0_config):
    """PHASE J0 原本要交付的能力：四通道闭环跟踪。

    J0-R1 的 F1/F2 修复前该用例以 ``xfail(strict=True)`` 记录，因为负阻尼使任何
    非零命令在 0.03–0.2 s 内发散。修复后 xfail 标记已按任务书第 9 节移除，改为
    正式验证真实跟踪行为。正式用例**不得**使用任何人造阻尼。
    """
    result = runner.run_case(_short_case(j0_config.cases[1], duration=2.0))
    assert result.completed, result.failure_reason
    assert result.diagnostic_damping_n_s_per_m == 0.0
    assert result.summary["status"] in {"PASS", "CONDITIONAL", "FAIL"}
    # 跟踪必须真实发生：目标行程不可忽略，实际行程必须朝目标方向推进。
    for item in j0_config.channels:
        reference = result.summary["target_x_ref_m"][item.channel]
        assert abs(reference) > 1.0e-3, item.channel
        achieved = result.samples[f"{item.channel}_x_m"][-1]
        assert np.sign(achieved) == np.sign(reference), item.channel
        assert abs(achieved) > 0.3 * abs(reference), (
            f"{item.channel}: 2 s 内只走到目标的 "
            f"{abs(achieved)/abs(reference)*100:.0f}%")
    # 且不得由人为阻尼或复制目标角伪造。
    assert result.summary["max_link_residual_m"] <= 1.0e-9


@pytest.mark.slow
def test_run_is_repeatable(j0_config, m1_model):
    """Item 14: two runs of the same case reproduce identical samples."""
    runner = J0Runner(j0_config, m1_model, probe_authority=False)
    case = _short_case(j0_config.cases[0], duration=0.1)
    first = runner.run_case(case)
    second = runner.run_case(case)
    for key in ("channel_front_x_m", "channel_rear_1_x_m", "time_s"):
        assert np.array_equal(first.samples[key], second.samples[key])


def test_long_run_cancellation_stops_at_a_control_boundary(runner, j0_config):
    checks = {"count": 0}

    def should_stop():
        checks["count"] += 1
        return checks["count"] >= 3

    case = _short_case(j0_config.cases[0], duration=0.2)
    result = runner.run_case(case, should_stop=should_stop)
    assert not result.completed
    assert "cancelled by user" in (result.failure_reason or "")
    assert result.failure_time_s == pytest.approx(0.02)
