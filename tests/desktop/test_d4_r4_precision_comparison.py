"""The independent equivalence audit must detect hidden interior excursions."""
import copy
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest


_PATH = Path(__file__).resolve().parents[2] / "scripts/d4/compare_r4_precision.py"
_SPEC = importlib.util.spec_from_file_location("r4_precision_audit", _PATH)
audit = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(audit)


def bundle():
    time = np.arange(2001) * .0005
    state = np.zeros((len(time), 23)); state[:, 0] = time
    for i in range(4):
        state[:, 1+5*i] = 1e6
        state[:, 2+5*i] = 1e6
    state[:, -2:] = 2e7
    recorded_time = time[::20]
    samples = {"time_s": recorded_time}
    for wheel in audit.WHEELS:
        samples[f"wheel_{wheel}_actual_deg"] = np.zeros(len(recorded_time))
        samples[f"wheel_{wheel}_command_deg"] = np.zeros(len(recorded_time))
    return {"metadata": {
        "scenario": {"target_outer_angle_deg": 0., "seconds_per_degree": 6.},
        "simulation_horizon_s": 1., "command_type": "ramp", "initial_outer_angle_deg": 0.,
        "seconds_per_degree": 6., "calculation_success": True,
        "tracking_pass": True, "trajectory_feasible": True,
        "summary": {"completed": True, "TRACKING_PASS": True, "NUMERICAL_COMPLETED": True},
        "response": {"command_completion_s": .2, "system_settled_s": .3,
                     "all_wheels_settled_s": .3, "all_cylinders_settled_s": .3,
                     "additional_convergence_s": .1, "system_status": "SETTLED",
                     "criteria": {"settled_observation_s": .2}}},
        "samples": samples, "boundary": {"state": state, "commands": np.zeros((len(time), 4))}}


def test_exact_recorded_histories_are_identical_without_solving():
    reference = bundle()
    result = audit.compare_runs(reference, copy.deepcopy(reference))
    assert result["status"] == "PASS"
    assert result["exact_matching_columns"] == result["compared_columns"]
    assert result["exact_matching_elements"] == result["compared_elements"]
    assert result["rows"][0]["sample_count"] == 2001


@pytest.mark.parametrize("column,delta,description", [
    (4, .00025, "channel_front_v_m_s"),
    (1, 10., "channel_front_pA_pa_g"),
    (5, .0001, "channel_front_actual_spool"),
])
def test_interior_excursion_fails_even_when_final_state_matches(column, delta, description):
    reference = bundle(); changed = copy.deepcopy(reference)
    # This point lies between 10 ms output samples and in the final hold.
    changed["boundary"]["state"][1701, column] += delta
    assert np.array_equal(reference["boundary"]["state"][-1], changed["boundary"]["state"][-1])
    result = audit.compare_runs(reference, changed)
    assert result["status"] == "FAIL"
    assert any(description in error for error in result["failures"])
    hold = [r for r in result["rows"] if r["field"] == description and r["window"] == "final_observation"][0]
    assert hold["max_abs_difference"] == pytest.approx(delta)
    assert hold["candidate_rms"] != hold["baseline_rms"]


def test_interior_wheel_discrepancy_and_status_changes_are_reported():
    reference = bundle(); changed = copy.deepcopy(reference)
    changed["samples"]["wheel_axle6_right_actual_deg"][30] = .001
    changed["metadata"]["tracking_pass"] = False
    result = audit.compare_runs(reference, changed)
    assert result["status"] == "FAIL"
    assert any("wheel_axle6_right_actual_deg" in error for error in result["failures"])
    assert "status:tracking_pass" in result["failures"]


def test_different_grid_and_criteria_cannot_be_hidden_with_interpolation():
    reference = bundle(); changed = copy.deepcopy(reference)
    changed["boundary"]["state"][500, 0] += 1e-6
    changed["metadata"]["response"]["criteria"]["settled_observation_s"] = .1
    result = audit.compare_runs(reference, changed)
    assert result["status"] == "FAIL"
    assert "response criteria changed" in result["failures"]
    assert any("time grid differs" in error for error in result["failures"])


def test_roundoff_pass_is_distinguished_from_exact_equality():
    reference = bundle(); changed = copy.deepcopy(reference)
    changed["boundary"]["state"][500, 3] += 1e-13
    result = audit.compare_runs(reference, changed)
    assert result["status"] == "PASS"
    assert result["exact_matching_columns"] < result["compared_columns"]


def test_nonfinite_state_cannot_pass_or_produce_nonstandard_json(tmp_path):
    reference = bundle(); changed = copy.deepcopy(reference)
    changed["boundary"]["state"][100, 4] = np.nan
    result = audit.compare_runs(reference, changed)
    assert result["status"] == "FAIL"
    audit.write_comparison(result, tmp_path)
    output = (tmp_path / "precision_comparison.json").read_text(encoding="utf-8")
    assert "NaN" not in output


def test_added_spool_columns_must_be_exact_raw_integrated_values():
    reference = bundle(); changed = copy.deepcopy(reference)
    for index, channel in enumerate(audit.CHANNELS):
        changed["samples"][f"{channel}_valve_spool_state"] = changed["boundary"]["state"][::20, 1+5*index+4].copy()
    result = audit.compare_runs(reference, changed)
    assert result["status"] == "PASS"
    assert len(result["verified_recording_extensions"]) == 4
    changed["samples"]["channel_front_valve_spool_state"][30] = .001
    result = audit.compare_runs(reference, changed)
    assert result["status"] == "FAIL"
    assert any("not exact integrated state" in message for message in result["failures"])


def test_other_sample_schema_changes_are_not_silently_ignored():
    reference = bundle(); changed = copy.deepcopy(reference)
    changed["samples"]["pretend_spool"] = np.zeros(len(changed["samples"]["time_s"]))
    result = audit.compare_runs(reference, changed)
    assert result["status"] == "FAIL"
    assert any("recorded sample fields changed" in message for message in result["failures"])


def test_fixed_zero_unavailable_response_times_are_nullable_not_failed_physics(tmp_path):
    reference = bundle()
    reference["metadata"]["response"]["wheel_table"] = [dict(
        wheel=wheel, settled_status="FIXED_ZERO_NO_STEERING_REQUIRED",
        first_arrival_s=np.nan, whole_run_first_arrival_s=np.nan,
        settled_time_s=np.nan, additional_convergence_s=np.nan)
        for wheel in ("axle3_left", "axle3_right")]
    changed = copy.deepcopy(reference)
    # JSON null and pandas NaN express the same documented no-action times.
    changed["metadata"]["response"]["wheel_table"][0]["first_arrival_s"] = None
    report = audit.compare_runs(reference, changed)
    assert report["status"] == "PASS"
    fixed = [row for row in report["response_checks"] if row["field"].startswith("axle3")]
    assert len(fixed) == 8
    assert all(row["baseline_s"] is None and row["candidate_s"] is None for row in fixed)
    assert all(row["baseline_time_kind"] == "not_applicable_fixed_zero" for row in fixed)
    assert all(row["finite_or_documented_unavailable"] for row in fixed)
    audit.write_comparison(report, tmp_path)
    assert json.loads((tmp_path / "precision_comparison.json").read_text(encoding="utf-8")) == report
    changed["boundary"]["state"][400, 4] = np.nan
    assert audit.compare_runs(reference, changed)["status"] == "FAIL"


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_nonfinite_times_without_documented_unavailable_status_fail_and_serialize(value, tmp_path):
    reference = bundle(); changed = copy.deepcopy(reference)
    changed["metadata"]["response"]["system_settled_s"] = value
    report = audit.compare_runs(reference, changed)
    assert report["status"] == "FAIL"
    row = next(row for row in report["response_checks"] if row["field"] == "system_settled_s")
    assert not row["finite_or_documented_unavailable"] and row["candidate_time_kind"] == "invalid_nonfinite"
    audit.write_comparison(report, tmp_path)
    json.loads((tmp_path / "precision_comparison.json").read_text(encoding="utf-8"))


def test_unexpected_nonfinite_metadata_remains_failed_diagnostic_not_export_crash(tmp_path):
    reference = bundle(); changed = copy.deepcopy(reference)
    changed["metadata"]["runtime_s"] = float("nan")
    report = audit.compare_runs(reference, changed)
    assert report["status"] == "FAIL"
    assert report["nonfinite_diagnostic_fields"]
    audit.write_comparison(report, tmp_path)
    assert "NaN" not in (tmp_path / "precision_comparison.json").read_text(encoding="utf-8")
