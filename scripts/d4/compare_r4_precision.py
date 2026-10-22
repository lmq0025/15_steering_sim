"""Compare complete recorded R4 runs without running or changing a solver.

The acceptance tolerances below bound implementation round-off, not model
accuracy. They do not replace J1-R2 tracking/settling criteria. All 22 states
and four held commands are checked at every recorded 0.5 ms RK4 boundary;
the twelve mechanically mapped wheel histories use the original 10 ms
recorder. There is no time interpolation, smoothing or terminal-only match.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
ENGINEERING_PYTHON = Path(r"E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe")
CHANNELS = ("channel_front", "channel_rear_1", "channel_rear_2", "channel_rear_3")
WHEELS = tuple(f"axle{a}_{side}" for a in range(1, 7) for side in ("left", "right"))

# Absolute + relative tolerance at each point. Comparisons also expose exact
# element/column matches so a pass is not presented as bitwise equivalence.
TOLERANCES = {
    "pressure": (1.0, 1e-10, "Pa", "1 Pa: far below a kPa display unit"),
    "position": (1e-9, 1e-10, "m", "1 nm: 200,000 times smaller than 0.20 mm settling band"),
    "velocity": (1e-8, 1e-9, "m/s", "0.00001 mm/s: rejects the known 2 ms residual near 0.25 mm/s"),
    "command": (1e-8, 1e-9, "1", "1e-8 of normalized valve command/spool full scale"),
    "angle": (1e-6, 1e-10, "deg", "one millionth degree: 100,000 times smaller than 0.10 degree band"),
    "angular_velocity": (1e-5, 1e-9, "deg/s", "0.00001 deg/s: 2,000 times smaller than 0.02 deg/s threshold"),
    "flow": (1e-10, 1e-9, "m3/s", "0.000006 L/min"),
    "force": (1e-3, 1e-9, "N", "1 mN absolute allowance for equivalent arithmetic"),
    "moment": (1e-3, 1e-9, "N*m", "1 mN*m absolute allowance"),
    "radian": (1e-8, 1e-10, "rad", "less than 0.000001 degree"),
    "time": (1e-12, 0.0, "s", "time grid unchanged; no interpolation"),
    "numeric": (1e-10, 1e-9, "field SI unit", "small round-off for secondary diagnostics"),
    "discrete": (0.0, 0.0, "1", "status and event flags must agree exactly"),
}


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_run(folder: Path) -> dict:
    folder = folder.resolve()
    metadata = json.loads((folder / "result.json").read_text(encoding="utf-8-sig"))
    with np.load(folder / "samples.npz", allow_pickle=False) as packed:
        samples = {key: packed[key].copy() for key in packed.files}
    with np.load(folder / "rk_boundaries.npz", allow_pickle=False) as packed:
        boundary = {key: packed[key].copy() for key in packed.files}
    return {"path": str(folder), "metadata": metadata, "samples": samples,
            "boundary": boundary, "file_sha256": {
                name: _hash(folder / name)
                for name in ("result.json", "samples.npz", "rk_boundaries.npz")}}


def field_kind(name: str) -> tuple[str, float]:
    """Return physical group and conversion into comparison SI/display units."""
    if name == "time_s": return "time", 1.0
    if any(word in name for word in ("status", "at_limit", "anti_windup", "insufficient",
                                     "infeasible", "source_is_actual", "exact_linkage_error")):
        return "discrete", 1.0
    if "mpa" in name: return "pressure", 1e6
    if name.endswith("_v_m_s") or "reference_velocity_m_s" in name:
        return "velocity", 1.0
    if name.endswith("_m3_s"): return "flow", 1.0
    if ("command" in name and not name.endswith("_deg")) or "_spool_" in name:
        return "command", 1.0
    if "pid_" in name: return "command", 1.0
    if name.endswith("_deg"): return "angle", 1.0
    if name.endswith("_rad"): return "radian", 1.0
    if name.endswith("_n"): return "force", 1.0
    if name.endswith("_nm"): return "moment", 1.0
    if name.endswith("_m") and ("stroke" in name or "_x_" in name):
        return "position", 1.0
    return "numeric", 1.0


def compare_column(name, baseline, candidate, kind, scope, time_s, window="full"):
    a, b = np.asarray(baseline, dtype=float), np.asarray(candidate, dtype=float)
    atol, rtol, unit, rationale = TOLERANCES[kind]
    finite = bool(np.all(np.isfinite(a)) and np.all(np.isfinite(b)))
    same_shape = a.shape == b.shape
    valid = finite and same_shape and a.size > 0
    difference = b - a if valid else np.array([])
    passed = bool(valid and np.all(np.abs(difference) <= atol + rtol * np.abs(a)))
    peak = lambda values: float(np.max(np.abs(values))) if valid else None
    exact_count = int(np.sum(a == b)) if same_shape else 0
    return {"scope": scope, "window": window, "field": name, "group": kind, "unit": unit,
            "sample_count": int(a.size), "start_s": float(time_s[0]) if len(time_s) else None,
            "end_s": float(time_s[-1]) if len(time_s) else None,
            "max_abs_difference": peak(difference),
            "rms_difference": float(np.sqrt(np.mean(difference ** 2))) if valid else None,
            "baseline_abs_peak": peak(a), "candidate_abs_peak": peak(b),
            "abs_peak_difference": abs(peak(a)-peak(b)) if valid else None,
            "baseline_rms": float(np.sqrt(np.mean(a ** 2))) if valid else None,
            "candidate_rms": float(np.sqrt(np.mean(b ** 2))) if valid else None,
            "baseline_final": float(a[-1]) if valid else None,
            "candidate_final": float(b[-1]) if valid else None,
            "exact_match_count": exact_count, "exact_match_fraction": exact_count / a.size if a.size else 0.,
            "exact_column_match": bool(valid and np.array_equal(a, b)),
            "absolute_tolerance": atol, "relative_tolerance": rtol,
            "tolerance_rationale": rationale, "finite": finite,
            "passed": passed}


def _time_checks(name, a, b, failures):
    a, b = np.asarray(a), np.asarray(b)
    if a.ndim != 1 or b.ndim != 1 or len(a) < 2 or len(b) < 2:
        failures.append(f"{name}: insufficient one-dimensional time samples")
        return False
    if not np.all(np.isfinite(a)) or not np.all(np.isfinite(b)):
        failures.append(f"{name}: non-finite time")
        return False
    if np.any(np.diff(a) <= 0) or np.any(np.diff(b) <= 0):
        failures.append(f"{name}: non-increasing time")
        return False
    if a.shape != b.shape or not np.array_equal(a, b):
        failures.append(f"{name}: time grid differs; no interpolation permitted")
        return False
    return True


def compare_runs(baseline: dict, candidate: dict) -> dict:
    """Pure comparison, also usable with synthetic bundles in low-cost tests."""
    rows, failures, response_checks, status_checks = [], [], [], []
    ma, mb = baseline["metadata"], candidate["metadata"]
    for key in ("scenario", "simulation_horizon_s", "command_type", "initial_outer_angle_deg",
                "seconds_per_degree"):
        if ma.get(key) != mb.get(key): failures.append(f"input/result scope changed: {key}")
    ra, rb = ma.get("response", {}), mb.get("response", {})
    if ra.get("criteria") != rb.get("criteria"):
        failures.append("response criteria changed")
    completion = float(ra.get("command_completion_s", 0.))
    ba, bb = baseline["boundary"], candidate["boundary"]
    sa, sb = np.asarray(ba["state"]), np.asarray(bb["state"])
    boundaries_valid = sa.ndim == 2 and sb.ndim == 2 and sa.shape[1] == sb.shape[1] == 23
    if not boundaries_valid:
        failures.append("raw boundary state must contain t + 22 states")
    elif _time_checks("RK4 boundaries", sa[:, 0], sb[:, 0], failures):
        time = sa[:, 0]
        if not np.allclose(np.diff(time), .0005, atol=1e-11, rtol=0.):
            failures.append("RK4 boundary grid is not the 0.5 ms reference step")
        names = []
        for channel in CHANNELS:
            names.extend([(f"{channel}_pA_pa_g", "pressure"), (f"{channel}_pB_pa_g", "pressure"),
                          (f"{channel}_x_m", "position"), (f"{channel}_v_m_s", "velocity"),
                          (f"{channel}_actual_spool", "command")])
        names.extend([("front_supply_pressure_pa_g", "pressure"), ("rear_supply_pressure_pa_g", "pressure")])
        criteria = ra.get("criteria", {})
        observation = float(criteria.get("settled_observation_s", 2.)) if isinstance(criteria, dict) else 2.
        for column, (name, kind) in enumerate(names, 1):
            for window, mask in (("full", np.ones(len(time), dtype=bool)),
                                 ("hold", time >= completion - 1e-12),
                                 ("final_observation", time >= max(completion, time[-1] - observation) - 1e-12)):
                if np.any(mask):
                    rows.append(compare_column(name, sa[mask, column], sb[mask, column], kind,
                                               "all_RK4_boundaries", time[mask], window))
        ca, cb = np.asarray(ba["commands"]), np.asarray(bb["commands"])
        if ca.shape != (len(time), 4) or cb.shape != (len(time), 4):
            failures.append("held commands must contain four commands per RK4 boundary")
        else:
            for i, channel in enumerate(CHANNELS):
                rows.append(compare_column(f"{channel}_held_command", ca[:, i], cb[:, i],
                                           "command", "all_RK4_boundaries", time))
    samples_a, samples_b = baseline["samples"], candidate["samples"]
    # R4 adds genuine integrated spool readings to the ordinary recorder.
    # This sole permitted schema extension must be validated against BOTH
    # runs' independently captured raw state, never accepted by name alone.
    spool_fields = {f"{channel}_valve_spool_state" for channel in CHANNELS}
    added = set(samples_b) - set(samples_a)
    allowed_added = added & spool_fields
    if allowed_added and allowed_added != spool_fields:
        failures.append("incomplete added spool recording; all four channels are required")
    missing = sorted((set(samples_a) ^ set(samples_b)) - allowed_added)
    if missing: failures.append("recorded sample fields changed: " + ", ".join(missing))
    if "time_s" not in samples_a or "time_s" not in samples_b:
        failures.append("missing recorder time grid")
    elif _time_checks("recorded samples", samples_a["time_s"], samples_b["time_s"], failures):
        time = np.asarray(samples_a["time_s"])
        if allowed_added:
            if not boundaries_valid:
                failures.append("new spool fields cannot be verified without 22-state boundary arrays")
            else:
                raw_a_indexes = np.searchsorted(sa[:, 0], time)
                raw_b_indexes = np.searchsorted(sb[:, 0], time)
                raw_match = (np.all(raw_a_indexes < len(sa)) and np.all(raw_b_indexes < len(sb))
                             and np.array_equal(sa[raw_a_indexes, 0], time)
                             and np.array_equal(sb[raw_b_indexes, 0], time))
                if not raw_match:
                    failures.append("new spool fields do not align with actual RK4 boundaries")
                else:
                    for i, channel in enumerate(CHANNELS):
                        name = f"{channel}_valve_spool_state"
                        if name not in allowed_added:
                            continue
                        recorded = np.asarray(samples_b[name])
                        baseline_spool = sa[raw_a_indexes, 1+5*i+4]
                        candidate_spool = sb[raw_b_indexes, 1+5*i+4]
                        rows.append(compare_column(name, baseline_spool, recorded,
                                                   "command", "new_spool_vs_baseline_raw", time))
                        if not np.array_equal(candidate_spool, recorded):
                            failures.append(f"new spool recorder is not exact integrated state: {name}")
                        rows.append(compare_column(name, candidate_spool, recorded,
                                                   "command", "new_spool_vs_candidate_raw", time))
        for name in sorted(set(samples_a) & set(samples_b)):
            kind, factor = field_kind(name)
            rows.append(compare_column(name, np.asarray(samples_a[name])*factor,
                                       np.asarray(samples_b[name])*factor, kind,
                                       "original_recorded_samples", time))
        for wheel in WHEELS:
            name = f"wheel_{wheel}_actual_deg"
            if name not in samples_a or name not in samples_b:
                failures.append(f"missing wheel trajectory: {name}")
                continue
            va = np.gradient(samples_a[name], time); vb = np.gradient(samples_b[name], time)
            rows.append(compare_column(f"wheel_{wheel}_speed_deg_s", va, vb, "angular_velocity",
                                       "original_recorded_samples", time))
    for source, a, b, fields in (
        ("service", ma, mb, ("calculation_success", "tracking_pass", "trajectory_feasible")),
        ("summary", ma.get("summary", {}), mb.get("summary", {}),
         ("completed", "status", "NUMERICAL_COMPLETED", "TRACKING_PASS", "TRANSIENT_TRACKING_PASS",
          "VEHICLE_DYNAMIC_INFEASIBLE", "failure_reason", "failure_time_s", "envelope_limit_samples")),
        ("response", ra, rb, ("system_status",))):
        for field in fields:
            if field not in a and field not in b: continue
            passed = a.get(field) == b.get(field)
            status_checks.append({"source": source, "field": field, "baseline": a.get(field),
                                  "candidate": b.get(field), "passed": passed})
    def response_value(name, a, b, tolerance=.0100000001, unavailable_a=None, unavailable_b=None):
        def normalized(value, reason):
            if value is None:
                return None, True, "missing" if reason is None else reason, False
            number = float(value)
            if np.isfinite(number):
                return number, True, "finite", False
            # pandas represents missing times in otherwise numeric columns as
            # NaN. Only documented no-action/not-reached time entries are
            # nullable; infinity or an unexpected NaN remains a failed check.
            allowed = bool(np.isnan(number) and reason is not None)
            return None, allowed, reason if allowed else "invalid_nonfinite", True
        a, valid_a, kind_a, nonfinite_a = normalized(a, unavailable_a)
        b, valid_b, kind_b, nonfinite_b = normalized(b, unavailable_b)
        if not valid_a or not valid_b:
            passed = False; delta = None
        elif a is None or b is None:
            passed = a is None and b is None; delta = None
        else:
            delta = abs(float(b)-float(a)); passed = bool(np.isfinite(delta) and delta <= tolerance)
        response_checks.append({"field": name, "baseline_s": a, "candidate_s": b,
                                "absolute_difference_s": delta, "tolerance_s": tolerance,
                                "baseline_time_kind": kind_a, "candidate_time_kind": kind_b,
                                "baseline_input_nonfinite": nonfinite_a,
                                "candidate_input_nonfinite": nonfinite_b,
                                "finite_or_documented_unavailable": valid_a and valid_b,
                                "passed": passed})
    for key in ("command_completion_s", "all_wheels_settled_s", "all_cylinders_settled_s",
                "system_settled_s", "additional_convergence_s"):
        response_value(key, ra.get(key), rb.get(key), 1e-12 if key == "command_completion_s" else .0100000001,
                       "not_reached" if key != "command_completion_s" and ra.get("system_status") == "NOT_SETTLED_WITHIN_HORIZON" else None,
                       "not_reached" if key != "command_completion_s" and rb.get("system_status") == "NOT_SETTLED_WITHIN_HORIZON" else None)
    for table, identity in (("wheel_table", "wheel"), ("cylinder_table", "channel")):
        aa = {row[identity]: row for row in ra.get(table, [])}
        ab = {row[identity]: row for row in rb.get(table, [])}
        if set(aa) != set(ab): failures.append(f"response identities changed: {table}")
        for key in sorted(set(aa) & set(ab)):
            def unavailable_reason(row):
                if table == "wheel_table" and key in ("axle3_left", "axle3_right") and row.get("settled_status") == "FIXED_ZERO_NO_STEERING_REQUIRED":
                    return "not_applicable_fixed_zero"
                if row.get("settled_status") == "NOT_SETTLED_WITHIN_HORIZON":
                    return "not_reached"
                return None
            for metric in ("first_arrival_s", "whole_run_first_arrival_s", "settled_time_s", "additional_convergence_s"):
                if metric in aa[key] or metric in ab[key]:
                    response_value(f"{key}.{metric}", aa[key].get(metric), ab[key].get(metric),
                                   unavailable_a=unavailable_reason(aa[key]), unavailable_b=unavailable_reason(ab[key]))
            status_checks.append({"source": table, "field": f"{key}.settled_status",
                "baseline": aa[key].get("settled_status"), "candidate": ab[key].get("settled_status"),
                "passed": aa[key].get("settled_status") == ab[key].get("settled_status")})
    for field, kind in (("max_tracking_error_vs_command_deg", "angle"),
                        ("rms_tracking_error_vs_command_deg", "angle"),
                        ("steady_max_tracking_error_vs_command_deg", "angle")):
        a, b = ma.get("summary", {}).get(field), mb.get("summary", {}).get(field)
        if a is not None and b is not None:
            rows.append(compare_column(field, [a], [b], kind, "formal_summary", [0.]))
    failed_rows = [row["scope"] + ":" + row["window"] + ":" + row["field"] for row in rows if not row["passed"]]
    failures.extend(failed_rows)
    failures.extend("response:"+row["field"] for row in response_checks if not row["passed"])
    failures.extend("status:"+row["field"] for row in status_checks if not row["passed"])
    timings = {}
    for key in ("runtime_s", "service_runtime_s", "benchmark_wall_s", "rk_stage_wall_s"):
        a, b = ma.get(key), mb.get(key)
        timings[key] = {"baseline_s": a, "candidate_s": b,
                        "speedup": float(a)/float(b) if a is not None and b and float(b)>0 else None}
    report = {"status": "PASS" if not failures else "FAIL", "failures": failures,
            "baseline_path": baseline.get("path"), "candidate_path": candidate.get("path"),
            "baseline_file_sha256": baseline.get("file_sha256"), "candidate_file_sha256": candidate.get("file_sha256"),
            "scenario": ma.get("scenario"), "criteria": ra.get("criteria"),
            "verified_recording_extensions": sorted(allowed_added),
            "tolerances": {key: dict(absolute=a, relative=r, unit=u, rationale=why)
                           for key, (a,r,u,why) in TOLERANCES.items()},
            "response_time_tolerance_explanation": "At most one original 10 ms recorder interval; command completion is unchanged within 1e-12 s.",
            "coverage": "All 22 states and 4 commands at every actual 0.5 ms RK4 boundary. Twelve wheel angles and computed wheel speeds at every original 10 ms sample. No interpolation, smoothing, resampling, or solver calls.",
            "peak_scope": "All accepted RK4 boundaries; does not claim intra-stage or continuous-time extrema.",
            "rows": rows, "response_checks": response_checks, "status_checks": status_checks,
            "compared_columns": len(rows), "exact_matching_columns": sum(row["exact_column_match"] for row in rows),
            "exact_matching_elements": sum(row["exact_match_count"] for row in rows),
            "compared_elements": sum(row["sample_count"] for row in rows), "timings": timings,
            "profiling_enabled": {"baseline": ma.get("profiling_enabled"), "candidate": mb.get("profiling_enabled")}}
    # Unexpected nonfinite metadata must remain reportable rather than causing
    # JSON export itself to crash. These are explicitly failed diagnostics,
    # unlike the documented nullable response times normalized above.
    diagnostic_nonfinite = []
    def safe_diagnostic(value, path):
        if isinstance(value, dict):
            return {key: safe_diagnostic(item, path + "." + str(key)) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [safe_diagnostic(item, path + "." + str(index)) for index, item in enumerate(value)]
        if isinstance(value, (float, np.floating)) and not np.isfinite(value):
            diagnostic_nonfinite.append(path)
            return None
        return value
    report = safe_diagnostic(report, "report")
    report["nonfinite_diagnostic_fields"] = diagnostic_nonfinite
    if diagnostic_nonfinite:
        report["status"] = "FAIL"
        report["failures"].extend("nonfinite diagnostic:" + path for path in diagnostic_nonfinite)
    return report


def write_comparison(report: dict, target: Path):
    target.mkdir(parents=True, exist_ok=True)
    (target / "precision_comparison.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    for filename, rows in (("precision_columns.csv", report["rows"]),
                           ("response_time_comparison.csv", report["response_checks"]),
                           ("status_comparison.csv", report["status_checks"])):
        if not rows: continue
        with (target / filename).open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader(); writer.writerows(rows)


def main():
    if Path(sys.executable) != ENGINEERING_PYTHON:
        raise RuntimeError(f"Use the authorized engineering Python: {ENGINEERING_PYTHON}")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=ROOT / "outputs/desktop/r4/baseline")
    parser.add_argument("--candidate", type=Path, default=ROOT / "outputs/desktop/r4/optimized")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/desktop/r4/precision")
    parser.add_argument("--angles", type=float, nargs="+", default=[2., 5., 10.])
    args = parser.parse_args()
    reports = []
    for angle in args.angles:
        name = f"angle_{angle:g}"
        report = compare_runs(load_run(args.baseline / name), load_run(args.candidate / name))
        write_comparison(report, args.output / name)
        reports.append({"angle_deg": angle, "status": report["status"], "failure_count": len(report["failures"]),
                        "timings": report["timings"], "report": str(args.output / name / "precision_comparison.json")})
        print(json.dumps(reports[-1], ensure_ascii=False), flush=True)
    (args.output / "summary.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if all(row["status"] == "PASS" for row in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
