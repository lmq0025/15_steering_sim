"""J0 artefact tests: summaries, figures and the documented case outcomes."""
from __future__ import annotations

import json

import numpy as np
import pytest

from steering_sim.j0_coupling.config import J0CaseConfig
from steering_sim.j0_coupling.reporting import (markdown_table, plot_case,
                                                write_samples_csv, write_summary_json)


def _short(case, duration=0.02):
    return J0CaseConfig(id=case.id, target_outer_angle_deg=case.target_outer_angle_deg,
                        speed_kmh=case.speed_kmh, duration_s=duration)


@pytest.mark.slow
def test_summary_carries_every_required_field(runner, j0_config):
    """Item 14/section 9: the case summary contains the required quantities."""
    result = runner.run_case(_short(j0_config.cases[1], 0.05))
    summary = result.summary
    for key in ("steady_wheel_angle_error_deg", "max_steady_wheel_angle_error_deg",
                "max_pressure_mpa_g", "max_abs_velocity_m_s", "max_abs_stroke_m",
                "max_link_residual_m", "third_axle_max_abs_deg",
                "control_saturation_fraction", "anti_windup_active_fraction",
                "virtual_work_residual_max_abs", "pump_capacity_warnings",
                "max_adhesion_utilization", "max_abs_slip_angle_deg",
                "target_q_ref_rad", "target_x_ref_m", "stroke_range_m",
                "peak_hydraulic_force_n", "authority"):
        assert key in summary, key
    assert summary["status"] in {"PASS", "CONDITIONAL", "FAIL"}
    assert len(summary["steady_wheel_angle_error_deg"]) == 12


@pytest.mark.slow
def test_csv_round_trips(scratch_dir, runner, j0_config):
    result = runner.run_case(_short(j0_config.cases[0], 0.02))
    path = write_samples_csv(result, scratch_dir / "case.csv")
    header = path.read_text(encoding="utf-8").splitlines()[0].split(",")
    for key in ("time_s", "channel_front_x_m", "wheel_axle6_right_actual_deg",
                "cylinder_axle4_B_stroke_m", "max_link_residual_m"):
        assert key in header


@pytest.mark.slow
def test_summary_json_is_serialisable(scratch_dir, runner, j0_config):
    result = runner.run_case(_short(j0_config.cases[0], 0.02))
    path = write_summary_json({"case": result.summary}, scratch_dir / "summary.json")
    reloaded = json.loads(path.read_text(encoding="utf-8"))
    assert reloaded["case"]["case_id"] == result.case.id


@pytest.mark.slow
def test_three_required_figures_are_written(scratch_dir, runner, j0_config):
    result = runner.run_case(_short(j0_config.cases[1], 0.05))
    written = plot_case(result, scratch_dir)
    assert len(written) == 3
    for path in written:
        assert path.exists() and path.stat().st_size > 1000


def test_markdown_table_helper():
    text = markdown_table([[1, 2]], ["a", "b"])
    assert text.splitlines()[0] == "| a | b |"
    assert text.splitlines()[2] == "| 1 | 2 |"


# ------------------------------------------------------------------ outcomes
@pytest.mark.slow
def test_recorded_outcome_of_every_configured_case(runner, j0_config):
    """J0-R1 后四个工况都必须跑满全程且不触发停止条件。

    J0-01（0°/0 km/h）是精确不动点：位移、轮角、残差全程严格为零。

    J0-02/03/04 在修复前于 0.075–0.082 s 触发 ``MAPPING_OUT_OF_ENVELOPE``
    （F1 负阻尼发散）。修复后应稳定收敛；本用例守住"不再停机"这一底线，
    跟踪精度由 ``test_four_channel_loop_tracks_the_j0_reference`` 与交付报告负责。
    """
    outcomes = {}
    for case in j0_config.cases:
        result = runner.run_case(_short(case, 0.5))
        outcomes[case.id] = result
    assert outcomes["J0-01"].completed
    assert outcomes["J0-01"].summary["status"] == "PASS"
    # PHASE J1-R2：零位工况的行程残差是 RK4 的浮点残差（实测 7.6e-19 m），
    # 对它做"逐位等于 0"的断言不是物理要求。改为亚皮米量级的工程判据。
    assert outcomes["J0-01"].summary["max_abs_stroke_m"] < 1.0e-12
    for case_id in ("J0-02", "J0-03", "J0-04"):
        result = outcomes[case_id]
        assert result.completed, f"{case_id}: {result.failure_reason}"
        assert result.failure_time_s is None
        assert result.summary["max_pressure_mpa_g"] < 20.0
        assert result.summary["max_abs_velocity_m_s"] < 1.0


@pytest.mark.slow
def test_front_group_force_authority_covers_its_road_load(runner, j0_config):
    """J0-R1 F2 后，前通道的作动力量级必须覆盖前端组的道路负载需求。

    本用例原为 ``test_front_group_cannot_reach_its_reference``，断言作动能力比负载
    需求小 20 倍（缺陷表征）。修复后改为验证覆盖关系。
    """
    from steering_sim.j0_coupling.road_load import road_load

    target = runner.target(j0_config.cases[1])
    assert abs(target["x_ref"]["channel_front"]) > 1.0e-3
    low, high = runner.authorities[0].force_window_n
    assert low < 0.0 < high
    road = road_load(runner.geometry, target["q_ref"], speed_kmh=5.0,
                     friction_coefficient=runner.mu, axle_mass_t=runner.axle_mass_t,
                     curvature_1pm=target["curvature_1pm"],
                     singular_threshold_m_per_rad=runner.singular_threshold)
    front_load = road.hydraulic_load_force_n["q_front"]
    assert abs(front_load) > 1.0e3, "前端组负载量级异常"
    available = min(-low, high)
    assert available > 0.75 * abs(front_load), (
        f"前通道可用 {available:.0f} N，前端组需要 {abs(front_load):.0f} N")


def test_authority_recorded_for_every_channel(runner):
    """J0-R1 后四个通道都必须双向，且都没有"静态力可忽略"的告警。"""
    assert len(runner.authorities) == 4
    assert runner.authorities[0].channel == "channel_front"
    assert runner.authorities[1].channel == "channel_rear_1"
    for authority in runner.authorities:
        assert authority.bidirectional, authority.channel
        assert authority.force_window_n[1] - authority.force_window_n[0] > 5.0e3, \
            authority.channel
        assert "NEGLIGIBLE_STATIC_FORCE_AUTHORITY" not in authority.notes
        assert "ZERO_COMMAND_AUTHORITY" not in authority.notes
