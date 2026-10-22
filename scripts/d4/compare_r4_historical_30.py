"""Audit R4 +30 degree/185 s against the saved R2 0.5 ms run.

Historical data only contain 10 ms recorder samples, not the 0.5 ms state
boundaries or valve spool. This is deliberately a RECORDED-SCOPE comparison,
not a replacement for the fresh R4 2/5/10 degree full-boundary comparisons.
No solver is called, no old raw states are reconstructed, and no interpolation
or smoothing is permitted. Historical elapsed times are descriptive only.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

from compare_r4_precision import (CHANNELS, ENGINEERING_PYTHON, ROOT, TOLERANCES,
                                  WHEELS, _hash, _time_checks, compare_column,
                                  field_kind, load_run)

sys.path.insert(0, str(ROOT / "src"))
from steering_sim.desktop.response_analysis import ResponseCriteria, analyze_response


HISTORICAL_INDEX = ROOT / "outputs/desktop/r2/a/reference_step_matrix/ramp_acceptance_summary.json"
EXPECTED_INDEX_SHA256 = "8c78e8426f5d6899d522cbeda699377444605127417724215e685cdcdde26f8d"
EXPECTED_CSV_SHA256 = "5c2d53a67687aaf45f2862643337d78a03d53b74186dff26926d6d0857f8b573"
CRITERIA = dict(wheel_angle_tolerance_deg=.10, cylinder_position_tolerance_m=.00020,
                wheel_speed_threshold_deg_s=.02, piston_speed_threshold_m_s=.001,
                settled_observation_s=2., maximum_hold_observation_s=10.,
                slow_ramp_hydraulic_step_s=.0005)
PROTECTED = ("configs/j1/engineering_mechanism.json", "configs/j1/engineering_config.json",
             "configs/j1r2/engineering_hydraulics.json", "mechanical_model_input_spec_v1.0.yaml",
             "configs/degradation/d1_degradation_models.json", "configs/degradation/d2_quality_thresholds.json",
             "configs/degradation/d3_rul_models.json")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def normal_hashes(values):
    return {str(key).replace("\\", "/"): value for key, value in values.items()}


def _table(path):
    frame = pd.read_csv(path, float_precision="round_trip")
    return frame.astype(object).where(frame.notna(), None).to_dict(orient="records")


def compare_historical(candidate_folder: Path) -> dict:
    candidate = load_run(candidate_folder)
    metadata = candidate["metadata"]
    failures, rows, status_checks, response_checks, checks = [], [], [], [], []
    files = {}

    def tracked(path):
        path = Path(path).resolve()
        files[str(path.relative_to(ROOT))] = _hash(path)
        return path

    def check(name, expected, actual):
        passed = expected == actual
        checks.append(dict(name=name, expected=expected, actual=actual, passed=passed))
        if not passed:
            failures.append("compatibility:" + name)

    check("historical acceptance index SHA256", EXPECTED_INDEX_SHA256, _hash(tracked(HISTORICAL_INDEX)))
    matches = [item for item in read_json(HISTORICAL_INDEX) if item["case"] == "0_to_p30"]
    if len(matches) != 1:
        raise ValueError("Expected exactly one historical 0_to_p30 entry")
    original = matches[0]
    csv_path = tracked(ROOT / original["timeseries_csv"])
    check("historical actual recorder CSV SHA256", EXPECTED_CSV_SHA256, _hash(csv_path))
    folder = csv_path.parent
    summary = read_json(tracked(folder / "summary.json"))
    frame = pd.read_csv(csv_path, float_precision="round_trip")
    samples = {key: frame[key].to_numpy() for key in frame}
    saved_tables = {"wheel_table": _table(tracked(folder / "wheel_response_times.csv")),
                    "cylinder_table": _table(tracked(folder / "cylinder_response_times.csv"))}
    r2 = read_json(tracked(ROOT / "outputs/desktop/r2/baseline.json"))
    r3 = read_json(tracked(ROOT / "outputs/desktop/r3/baseline.json"))
    r3_audit = read_json(tracked(ROOT / "outputs/desktop/r3/baseline_final_audit.json"))
    r4 = read_json(tracked(ROOT / "outputs/desktop/r4/baseline.json"))
    protected_checks = []
    for name in PROTECTED:
        hashes = dict(r2=r2["sha256"][name], r3=r3["protected"][name],
                      r4_before=r4["source_hashes"][name], current=_hash(tracked(ROOT / name)))
        passed = len(set(hashes.values())) == 1
        protected_checks.append(dict(path=name, hashes=hashes, passed=passed))
        if not passed:
            failures.append("protected configuration changed:" + name)
    response_path = "src/steering_sim/desktop/response_analysis.py"
    check("response analysis implementation unchanged since R2 completion",
          r3["source_hashes"][response_path], _hash(tracked(ROOT / response_path)))
    criterion_path = "configs/desktop/d4_r2_response_analysis.json"
    check("response criteria file unchanged since R4 start", r4["source_hashes"][criterion_path],
          _hash(tracked(ROOT / criterion_path)))
    check("current criterion values", CRITERIA, asdict(ResponseCriteria.load(ROOT / criterion_path)))
    check("candidate criterion values", CRITERIA, metadata["response"]["criteria"])
    source_chain = []
    candidate_hashes = normal_hashes(metadata["source_hashes"])
    for name, unchanged in r3_audit["hydraulic_and_coupling_source_unchanged"].items():
        historical = r3["source_hashes"][name]
        r4_start = r4["source_hashes"][name]
        check("R2-to-R3 source chain:" + name, True, bool(unchanged and historical == r4_start))
        current = _hash(tracked(ROOT / name))
        check("candidate captured source matches current:" + name, candidate_hashes.get(name), current)
        source_chain.append(dict(path=name, r2_completion_sha256=historical,
                                 r4_start_sha256=r4_start, candidate_sha256=candidate_hashes.get(name),
                                 changed_in_r4=current != historical))

    scenario = metadata["scenario"]
    expected_scenario = dict(command_type="ramp", initial_outer_angle_deg=0., target_outer_angle_deg=30.,
                             seconds_per_degree=6., hold_observation_s=5., speed_kmh=5.,
                             friction_coefficient=.8, axle_mass_t=[11.5] * 6)
    for name, expected in expected_scenario.items():
        check("candidate scenario:" + name, expected, scenario.get(name))
    # duration_s is the disabled legacy step input. The actual ramp horizon is
    # checked independently and must remain 180 s instruction + 5 s hold.
    check("candidate actual horizon", 185., metadata["simulation_horizon_s"])
    check("historical actual horizon", 185., summary["duration_s"])
    check("historical command duration", 180., original["command_completion_s"])
    for name in ("actual_hydraulic_step_s", "actual_control_step_s", "recording_period_s",
                 "reference_time_s", "reference_start_outer_angle_deg", "reference_space",
                 "controller_gains", "diagnostic_damping_n_s_per_m", "road_load_scale",
                 "use_feedforward", "feedforward_gain", "hydraulic_model", "mechanical_mode"):
        check("formal model/numerical settings:" + name, summary.get(name), metadata["summary"].get(name))

    # Compare like-for-like formal CSV records. The historical exporter used
    # %.12g, so its decimal timestamps (e.g. 0.35) differ by one ULP from the
    # unrounded new NPZ boundaries (0.35000000000000003). Do not relax the
    # shared raw-grid comparator or interpolate either trajectory. Preserve
    # the new NPZ separately for its raw-boundary provenance audit below.
    raw_record_samples = candidate["samples"]
    current_csv = tracked(Path(metadata["csv_path"]))
    current_frame = pd.read_csv(current_csv, float_precision="round_trip")
    current_samples = {key: current_frame[key].to_numpy() for key in current_frame}
    missing = sorted(set(samples) - set(current_samples))
    if missing:
        failures.append("historical recorder fields absent in candidate:" + ",".join(missing))
    added = sorted(set(current_samples) - set(samples))
    allowed_added = {f"{channel}_valve_spool_state" for channel in CHANNELS}
    if set(added) - allowed_added:
        failures.append("unexplained candidate recorder additions:" + ",".join(sorted(set(added)-allowed_added)))
    time_valid = _time_checks("historical 10 ms recorder", samples["time_s"], current_samples["time_s"], failures)
    if time_valid:
        time = samples["time_s"]
        check("actual sample count", 18501, len(time))
        check("recorder has 10 ms spacing", True,
              bool(np.allclose(np.diff(time), .01, atol=1e-12, rtol=0)))
        for name in sorted(set(samples) & set(current_samples)):
            kind, factor = field_kind(name)
            for window, mask in (("full", np.ones(len(time), dtype=bool)), ("hold", time >= 180.),
                                 ("final_observation", time >= 183.)):
                rows.append(compare_column(name, samples[name][mask]*factor, current_samples[name][mask]*factor,
                                           kind, "historical_10ms_recorder_only", time[mask], window))
        for wheel in WHEELS:
            name = f"wheel_{wheel}_actual_deg"
            if name not in samples or name not in current_samples:
                failures.append("missing actual wheel:" + name)
                continue
            rows.append(compare_column(name + "_speed", np.gradient(samples[name], time),
                                       np.gradient(current_samples[name], time), "angular_velocity",
                                       "historical_10ms_recorder_only", time))

    def response_value(name, a, b, tolerance=.0100000001, fixed_zero=False):
        def time_value(value):
            if value is None:
                return None, True
            number = float(value)
            if np.isfinite(number):
                return number, True
            # pandas numeric time columns encode documented fixed-axle N/A as
            # NaN. This exception applies ONLY to axle3 with the explicit
            # no-steering status, never to an actual state or an unknown time.
            return None, bool(fixed_zero and np.isnan(number))
        av, valid_a = time_value(a)
        bv, valid_b = time_value(b)
        difference = None if av is None or bv is None else abs(bv - av)
        passed = bool(valid_a and valid_b and ((av is None and bv is None) if difference is None else difference <= tolerance))
        response_checks.append(dict(field=name, baseline_s=av, candidate_s=bv,
                                    absolute_difference_s=difference, tolerance_s=tolerance,
                                    fixed_zero_not_applicable=fixed_zero,
                                    finite_or_documented_null=bool(valid_a and valid_b), passed=passed))

    def status_value(source, name, a, b):
        status_checks.append(dict(source=source, field=name, baseline=a, candidate=b, passed=a == b))

    response = metadata["response"]
    # Re-evaluation uses saved 10 ms data and unchanged criteria/analysis only;
    # it is cross-checked against saved original timing tables, never called a
    # recovered 0.5 ms trajectory or a newly executed historical simulation.
    reanalyzed = analyze_response(samples, 180., ResponseCriteria(**CRITERIA))
    for field in ("command_completion_s", "all_wheels_settled_s", "all_cylinders_settled_s", "system_settled_s"):
        tolerance = 1e-12 if field == "command_completion_s" else .0100000001
        response_value(field, original[field], response.get(field), tolerance)
        response_value("historical_reanalysis:" + field, original[field], reanalyzed.get(field), tolerance)
    response_value("additional_convergence_s", original["system_settled_s"] - 180., response.get("additional_convergence_s"))
    for table, identity in (("wheel_table", "wheel"), ("cylinder_table", "channel")):
        aa = {row[identity]: row for row in saved_tables[table]}
        bb = {row[identity]: row for row in response[table]}
        historical_analysis = {row[identity]: row for row in reanalyzed[table].to_dict(orient="records")}
        check("response identities:" + table, sorted(aa), sorted(bb))
        for identity_value in sorted(set(aa) & set(bb)):
            fixed_zero = (table == "wheel_table" and identity_value in ("axle3_left", "axle3_right")
                          and aa[identity_value].get("settled_status") == "FIXED_ZERO_NO_STEERING_REQUIRED"
                          and bb[identity_value].get("settled_status") == "FIXED_ZERO_NO_STEERING_REQUIRED")
            for field in ("first_arrival_s", "whole_run_first_arrival_s", "settled_time_s", "additional_convergence_s"):
                if field in aa[identity_value] or field in bb[identity_value]:
                    response_value(identity_value + "." + field, aa[identity_value].get(field),
                                   bb[identity_value].get(field), fixed_zero=fixed_zero)
                    restored = historical_analysis[identity_value].get(field)
                    response_value("historical_reanalysis:" + identity_value + "." + field,
                                   aa[identity_value].get(field), restored, fixed_zero=fixed_zero)
            status_value(table, identity_value + ".settled_status", aa[identity_value]["settled_status"],
                         bb[identity_value]["settled_status"])
    status_value("service", "calculation_success", original["calculation_success"], metadata["calculation_success"])
    status_value("response", "system_status", original["system_status"], response["system_status"])
    for field in ("completed", "status", "NUMERICAL_COMPLETED", "TRACKING_PASS", "TRANSIENT_TRACKING_PASS",
                  "VEHICLE_DYNAMIC_INFEASIBLE", "failure_reason", "failure_time_s", "envelope_limit_samples"):
        status_value("formal_summary", field, summary.get(field), metadata["summary"].get(field))
    for field in ("max_tracking_error_vs_command_deg", "rms_tracking_error_vs_command_deg", "steady_max_tracking_error_vs_command_deg"):
        rows.append(compare_column(field, [summary[field]], [metadata["summary"][field]], "angle", "formal_summary", [0.]))

    raw = candidate["boundary"]["state"]
    raw_audit = dict(scope="candidate only, NOT historical raw-state equivalence", channels=[])
    raw_valid = raw.ndim == 2 and raw.shape[1] == 23 and np.all(np.isfinite(raw))
    check("candidate raw state t+22 finite", True, bool(raw_valid))
    if raw_valid:
        check("candidate raw 0.5 ms spacing", True, bool(np.allclose(np.diff(raw[:, 0]), .0005, atol=1e-11, rtol=0)))
        check("candidate raw endpoint", 185., float(raw[-1, 0]))
        for i, channel in enumerate(CHANNELS):
            velocity = raw[:, 1 + 5*i + 3]
            final = velocity[raw[:, 0] >= 183.]
            hold = velocity[raw[:, 0] >= 180.]
            raw_audit["channels"].append(dict(channel=channel, hold_peak_abs_velocity_m_s=float(np.max(np.abs(hold))),
                final_observation_peak_abs_velocity_m_s=float(np.max(np.abs(final))),
                final_observation_rms_velocity_m_s=float(np.sqrt(np.mean(final**2))),
                final_observation_meets_original_speed_threshold=bool(np.all(np.abs(final) <= CRITERIA["piston_speed_threshold_m_s"]))))
            check("candidate final raw observation speed below original limit:" + channel, True,
                  raw_audit["channels"][-1]["final_observation_meets_original_speed_threshold"])
        indexes = np.searchsorted(raw[:, 0], raw_record_samples["time_s"])
        aligned = np.all(indexes < len(raw)) and np.array_equal(raw[indexes, 0], raw_record_samples["time_s"])
        check("candidate recorder aligned to real raw boundary", True, bool(aligned))
        if aligned:
            for i, channel in enumerate(CHANNELS):
                field = f"{channel}_valve_spool_state"
                if field in raw_record_samples:
                    check("candidate-only new spool record:" + channel, True,
                          bool(np.array_equal(raw[indexes, 1+5*i+4], raw_record_samples[field])))

    failures.extend("column:"+row["window"]+":"+row["field"] for row in rows if not row["passed"])
    failures.extend("response:"+row["field"] for row in response_checks if not row["passed"])
    failures.extend("status:"+row["field"] for row in status_checks if not row["passed"])
    timings = {}
    for old, new in (("runner_wall_s", "runtime_s"), ("service_wall_s", "service_runtime_s")):
        a, b = original[old], metadata[new]
        timings[new] = dict(historical_s=a, candidate_s=b, descriptive_ratio=a / b)
    return dict(status="PASS" if not failures else "FAIL", coverage_level="HISTORICAL_10MS_RECORDER_ONLY",
        full_22_state_boundary_comparison=False, failures=failures, checks=checks,
        coverage="All common saved 10 ms columns, derived wheel speed, original arrival/settling tables, formal status and summaries. Candidate raw hold-velocity audit is separate.",
        limitations=["No historical 0.5 ms raw states or valve spool records exist: no claim of full 22-state boundary equivalence for 30 degrees.",
                     "Historical and candidate comparisons use the same formal %.12g CSV export precision; raw NPZ provenance is checked separately for the candidate only.",
                     "Pressure peaks compared here are saved 10 ms sample peaks, not all RK4 boundaries or continuous-time peaks.",
                     "Historical runtime predates this session and has different instrumentation/background load; ratios are not controlled same-session speedups.",
                     "Historical scenario uses five seconds of final observation (185 seconds physical), not the ten-second 10 degree performance target."],
        historical_case=original, scenario=scenario, criteria=CRITERIA, rows=rows,
        response_checks=response_checks, status_checks=status_checks,
        protected_configuration_checks=protected_checks, source_chain=source_chain,
        candidate_only_raw_velocity_audit=raw_audit, candidate_added_fields=added,
        source_manifest=dict(historical_and_config_files_sha256=files, candidate_file_sha256=candidate["file_sha256"],
                             candidate_folder=candidate["path"], candidate_platform=metadata.get("platform"),
                             historical_machine_evidence=r3_audit.get("processor")),
        timings=timings, tolerances={key:dict(absolute=a, relative=r, unit=u, rationale=why)
                                   for key, (a, r, u, why) in TOLERANCES.items()},
        compared_columns=len(rows), compared_elements=sum(row["sample_count"] for row in rows),
        exact_matching_columns=sum(row["exact_column_match"] for row in rows))


def main():
    if Path(sys.executable) != ENGINEERING_PYTHON:
        raise RuntimeError(f"Use only {ENGINEERING_PYTHON}")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, default=ROOT / "outputs/desktop/r4/optimized_long/angle_30")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/desktop/r4/historical_30_verified")
    args = parser.parse_args()
    if (args.output / "comparison.json").exists():
        raise RuntimeError("Refuse overwriting existing comparison; choose a new output directory")
    report = compare_historical(args.candidate)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "comparison.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    (args.output / "source_manifest.json").write_text(json.dumps(report["source_manifest"], ensure_ascii=False, indent=2), encoding="utf-8")
    for filename, key in (("column_comparison.csv", "rows"), ("response_comparison.csv", "response_checks"),
                          ("status_comparison.csv", "status_checks")):
        with (args.output / filename).open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(report[key][0]))
            writer.writeheader(); writer.writerows(report[key])
    print(json.dumps({key:report[key] for key in ("status", "coverage_level", "failures", "timings")}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
