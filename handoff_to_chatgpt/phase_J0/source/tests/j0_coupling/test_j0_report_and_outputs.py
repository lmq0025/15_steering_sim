"""J0 artefact tests: summaries, figures and the documented case outcomes."""
from __future__ import annotations

import json
import math

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
    """Characterisation of the delivered plant, with the J0 configuration as shipped.

    J0-01 (0 deg / 0 km/h) is the trivial fixed point and passes: every stroke,
    every wheel angle and every residual stays exactly zero.

    J0-02/03/04 stop early.  The stop condition, not a plausible-looking result,
    is what the runner reports; the recorded reason is the plant defect that must
    be resolved before a real four-channel closed loop is possible.  See
    ``docs/handoff/J0_claude/05_J0_PLANT_DEFECT_AND_KNOWN_RISKS.md``.
    """
    outcomes = {}
    for case in j0_config.cases:
        result = runner.run_case(_short(case, 0.25))
        outcomes[case.id] = result
    assert outcomes["J0-01"].completed
    assert outcomes["J0-01"].summary["status"] == "PASS"
    assert outcomes["J0-01"].summary["max_abs_stroke_m"] == 0.0
    for case_id in ("J0-02", "J0-03", "J0-04"):
        result = outcomes[case_id]
        assert not result.completed, case_id
        assert result.summary["status"] == "FAIL"
        assert result.failure_time_s is not None
        assert "MAPPING_OUT_OF_ENVELOPE" in (result.failure_reason or "") or \
            "chamber volume" in (result.failure_reason or "")


@pytest.mark.slow
def test_front_group_cannot_reach_its_reference(runner, j0_config):
    """The front group's commanded stroke is not reachable with channel_front.

    Measured static force authority of ``channel_front`` is tens of newtons while
    the front group needs kilonewtons to hold the J0 road load, so the front
    axle-1/axle-2 wheels stay at 0 deg for every non-zero target.
    """
    target = runner.target(j0_config.cases[1])
    assert abs(target["x_ref"]["channel_front"]) > 1.0e-3
    window = runner.authorities[0].force_window_n
    assert window[1] - window[0] < 200.0
    front_load = math.nan
    # The road load on the front group at the J0-02 target.
    from steering_sim.j0_coupling.road_load import road_load
    road = road_load(runner.geometry, target["q_ref"], speed_kmh=5.0,
                     friction_coefficient=runner.mu, axle_mass_t=runner.axle_mass_t,
                     curvature_1pm=target["curvature_1pm"],
                     singular_threshold_m_per_rad=runner.singular_threshold)
    front_load = road.hydraulic_load_force_n["q_front"]
    assert abs(front_load) > 20.0 * (window[1] - window[0])
    del front_load


def test_authority_recorded_for_every_channel(runner):
    assert len(runner.authorities) == 4
    assert runner.authorities[0].channel == "channel_front"
    assert runner.authorities[1].channel == "channel_rear_1"
    assert any("NEGLIGIBLE_STATIC_FORCE_AUTHORITY" in note
               for note in runner.authorities[0].notes)
    for authority in runner.authorities[1:]:
        assert authority.bidirectional
        assert authority.force_window_n[1] - authority.force_window_n[0] > 5.0e3
