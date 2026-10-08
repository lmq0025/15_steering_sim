from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from pathlib import Path
from time import perf_counter


ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "hydraulic_audit"
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from steering_sim.hydraulics.solver import FastHydraulicModel


def inputs():
    return {"pump_speed_rad_s": 1350.0 * 2.0 * math.pi / 60.0, "valve_command": lambda t: 0.2 + 0.1 * math.sin(math.pi * t)}


def normalized_error(key: str, value: float, reference: float, peak: float) -> float:
    floors = {"_pa": 1.0e5, "_m3_s": 1.0e-8, "_nm": 1.0, "_n": 1.0, "_m": 1.0e-5, "_m_s": 1.0e-5, "rad_s": 1.0}
    floor = next((scale for suffix, scale in floors.items() if key.endswith(suffix)), 1.0e-8)
    return abs(value - reference) / max(abs(peak), floor)


def main(stage: str, write_baseline: bool = False) -> None:
    baseline_path = AUDIT / "19A_performance_baseline.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8")) if baseline_path.exists() and not write_baseline else None
    stage_upper = stage.upper()
    probe_started = perf_counter(); probe = FastHydraulicModel.from_ir(AUDIT); build_time = perf_counter() - probe_started
    init_started = perf_counter(); probe.initialize(inputs()); initialization_time = perf_counter() - init_started
    runs = []
    results = []
    diagnostics = []
    models = []
    for repetition in range(3):
        model = FastHydraulicModel.from_ir(AUDIT)
        model._use_jacobian_sparsity = "SPARSITY" in stage_upper
        model._use_algebraic_cache = "CACHE" in stage_upper
        result = model.simulate(1.0, inputs(), output_points=51)
        diag = model.aggregate_algebraic_diagnostics()
        if not result.success or diag.failures:
            raise SystemExit(f"{stage} repetition {repetition + 1} failed: {result.message}; algebraic failures={diag.failures}")
        runs.append(result.wall_time_s); results.append(result); diagnostics.append(diag); models.append(model)
        print(f"{stage} repetition {repetition + 1}: {result.wall_time_s:.6f} s, nfev={result.nfev}, njev={result.njev}, nlu={result.nlu}")
    median_index = sorted(range(3), key=lambda index: runs[index])[1]
    result, diag, model = results[median_index], diagnostics[median_index], models[median_index]
    errors = []
    regression_rows = []
    output_series: dict[str, list[float]] = {"time_s": [float(value) for value in result.time_s]}
    output_rows = [model.outputs(float(t), result.state[:, column], inputs=inputs()) for column, t in enumerate(result.time_s)]
    selected_keys = sorted(key for key in output_rows[0] if key.startswith(("pump01.", "actuator001.", "actuator001_1.", "actuator001_2.", "actuator002.")))
    for key in selected_keys:
        output_series[key] = [float(row[key]) for row in output_rows]
    if write_baseline:
        metrics = {key: {"final": values[-1], "peak_abs": max(abs(value) for value in values), "rms": math.sqrt(sum(value * value for value in values) / len(values))} for key, values in output_series.items() if key != "time_s"}
        baseline = {
            "frozen": True, "capture_method": "three fresh-model repeats; median wall-time run",
            "scenario": "steering_like", "solver": {"method": "BDF", "rtol": 1.0e-4, "atol": "18D_state_scaling.csv", "fast_states": 109, "fast_line_states": 67},
            "physical_time_s": 1.0, "wall_time_s": statistics.median(runs), "real_time_factor": statistics.median(runs),
            "nfev": result.nfev, "njev": result.njev, "nlu": result.nlu, "solver_steps": result.solver_steps,
            "algebraic_calls": diag.calls, "algebraic_iterations": diag.total_iterations,
            "metrics": metrics, "timeseries": output_series,
        }
        baseline_path.write_text(json.dumps(baseline, indent=2), encoding="utf-8")
    for column, t in enumerate(result.time_s):
        output = model.outputs(float(t), result.state[:, column], inputs=inputs())
        for key, reference_values in baseline["timeseries"].items():
            if key == "time_s" or "residual" in key or key not in output:
                continue
            reference = float(reference_values[column]); peak = float(baseline["metrics"][key]["peak_abs"])
            error = normalized_error(key, float(output[key]), reference, peak)
            errors.append(error)
    max_error = max(errors, default=0.0)
    regression_pass = write_baseline or max_error <= 1.0e-3
    evaluation_calls = sum(group.evaluation_calls for group in model.groups)
    cache_hits = sum(group.cache_hits for group in model.groups)
    actual_solves = sum(group.solver.diagnostics.calls for group in model.groups if group.solver is not None)
    stats = {
        "optimization_stage": stage,
        "model_build_time": build_time,
        "initialization_time": initialization_time,
        "wall_time_1s": statistics.median(runs),
        "speedup_vs_baseline": baseline["wall_time_s"] / statistics.median(runs),
        "nfev": result.nfev,
        "njev": result.njev,
        "nlu": result.nlu,
        "algebraic_calls": evaluation_calls,
        "actual_algebraic_solves": actual_solves,
        "cache_hits": cache_hits,
        "physics_regression": "REFERENCE" if write_baseline else ("PASS" if regression_pass else "FAIL"),
        "max_normalized_error": max_error,
        "repetitions": 3,
    }
    stage_path = AUDIT / f"19_STAGE_{stage}.json"
    stage_path.write_text(json.dumps(stats, indent=2), encoding="utf-8")
    output_path = AUDIT / "19G_performance_optimization_steps.csv"
    fields = list(stats)
    rows = []
    if output_path.exists():
        with output_path.open("r", encoding="utf-8-sig", newline="") as stream:
            rows = [row for row in csv.DictReader(stream) if row["optimization_stage"] != stage]
    if not write_baseline and not any(row.get("optimization_stage") == "BASELINE" for row in rows):
        rows.insert(0, {"optimization_stage": "BASELINE", "model_build_time": "", "initialization_time": "", "wall_time_1s": baseline["wall_time_s"], "speedup_vs_baseline": 1.0, "nfev": baseline["nfev"], "njev": baseline["njev"], "nlu": baseline["nlu"], "algebraic_calls": baseline["algebraic_calls"], "actual_algebraic_solves": baseline["algebraic_calls"], "cache_hits": 0, "physics_regression": "REFERENCE", "max_normalized_error": 0.0, "repetitions": 3})
    rows.append(stats)
    with output_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader(); writer.writerows(rows)
    print(json.dumps(stats, indent=2))
    if not regression_pass:
        raise SystemExit("physics regression failed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--stage", required=True); parser.add_argument("--write-baseline", action="store_true")
    args = parser.parse_args(); main(args.stage, args.write_baseline)
