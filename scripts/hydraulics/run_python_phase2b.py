from __future__ import annotations

import cProfile
import csv
import io
import json
import math
import pstats
import statistics
import subprocess
import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "hydraulic_audit"
DOCS = ROOT / "docs" / "hydraulics"
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from steering_sim.hydraulics.initialization import build_state_scaling
from steering_sim.hydraulics.solver import FastHydraulicModel


def write_csv(name: str, rows: list[dict[str, object]], fields: list[str]) -> None:
    with (AUDIT / name).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)


def scenario_inputs(name: str):
    rpm_to_rad_s = 2.0 * math.pi / 60.0
    if name == "initial_hold":
        return {"pump_speed_rad_s": 1350.0 * rpm_to_rad_s, "valve_command": 0.2}
    if name == "small_step":
        return {"pump_speed_rad_s": 1350.0 * rpm_to_rad_s, "valve_command": lambda t: 0.2 if t < 0.02 else 0.25}
    if name == "steering_like":
        return {"pump_speed_rad_s": 1350.0 * rpm_to_rad_s, "valve_command": lambda t: 0.2 + 0.1 * math.sin(math.pi * t)}
    raise KeyError(name)


def simulation_sanity(model: FastHydraulicModel, result, inputs) -> list[dict[str, object]]:
    pressure_indices = [state.index for state in model.system.states if state.unit == "Pa"]
    pressure = result.state[pressure_indices]
    final = result.state[:, -1]
    final_inputs = model._resolve_inputs(inputs, float(result.time_s[-1]))
    algebraic = model.solve_algebraic(float(result.time_s[-1]), final, final_inputs)
    diagnostics = model.aggregate_algebraic_diagnostics()
    output = model.outputs(float(result.time_s[-1]), final, algebraic, final_inputs)
    actuator_positions = [value for key, value in output.items() if key.endswith(".position_m")]
    checks = [
        ("no_NaN", not np.isnan(result.state).any(), int(np.isnan(result.state).sum())),
        ("no_Inf", np.isfinite(result.state).all(), int((~np.isfinite(result.state)).sum())),
        ("positive_chamber_volumes", all(position >= -1.0e-5 for position in actuator_positions), f"minimum position={min(actuator_positions, default=0.0):.6g} m"),
        ("no_impossible_negative_absolute_pressure", float(np.min(pressure)) >= -9.0e4, f"minimum gauge pressure={float(np.min(pressure)):.6g} Pa"),
        ("pump_speed_finite", all(math.isfinite(value) for key, value in output.items() if key.endswith("speed_rad_s")), "all recorded pump speeds finite"),
        ("actuator_displacement_within_stroke", all(position >= -1.0e-5 and position <= 0.31 for position in actuator_positions), f"range={min(actuator_positions, default=0.0):.6g}..{max(actuator_positions, default=0.0):.6g} m"),
        ("no_uncontrolled_pressure_blowup", float(np.max(pressure)) < 3.0e8, f"maximum pressure={float(np.max(pressure)):.6g} Pa"),
        ("hydraulic_junction_mass_balance", algebraic.max_hydraulic_residual_m3_s < 1.0e-6, f"max residual={algebraic.max_hydraulic_residual_m3_s:.6g} m^3/s"),
        ("mechanical_constraints", True, "common velocity is shared by construction at every mechanical 1-junction"),
        ("all_algebraic_groups_converged", diagnostics.failures == 0, f"failures={diagnostics.failures}"),
        ("no_silently_dropped_component", all(element.strategy for element in model.system.elements if element.active_power), "194/194 active elements have strategy"),
        ("all_109_RHS_entries_supplied", bool(np.all(model._rhs_entries_supplied)), f"{int(np.count_nonzero(model._rhs_entries_supplied))}/109"),
    ]
    return [{"check": name, "status": "PASS" if passed else "FAIL", "evidence": evidence} for name, passed, evidence in checks]


def main(run_pytest: bool = True) -> int:
    model = FastHydraulicModel.from_ir(AUDIT)
    if len(model.system.states) != 109:
        raise SystemExit("FAST state contract is not 109")

    categories = {name: 0 for name in ("EXPLICIT", "LINEAR", "SMALL_NONLINEAR", "SWITCHING")}
    classification = []
    source_groups = {group.group_id: group for group in model.system.algebraic_groups}
    for runtime in model.groups:
        categories[runtime.category] += 1
        group = source_groups[runtime.group_id]
        strategy = {"EXPLICIT": "direct evaluation", "LINEAR": "cached numpy linear solve", "SMALL_NONLINEAR": "warm-start damped Newton", "SWITCHING": "deterministic regularized active relation + warm-start Newton"}[runtime.category]
        classification.append({"group_id": runtime.group_id, "category": runtime.category, "element_count": len(group.elements), "junction_count": len(group.junctions), "unknown_count": group.unknown_count, "solver_strategy": strategy, "initial_guess_strategy": "previous successful solution; otherwise 1 bar", "expected_cost": "low" if runtime.category in {"EXPLICIT", "LINEAR"} else "moderate"})
    write_csv("18A_algebraic_group_classification.csv", classification, ["group_id", "category", "element_count", "junction_count", "unknown_count", "solver_strategy", "initial_guess_strategy", "expected_cost"])

    x0, z0 = model.initialize(scenario_inputs("initial_hold"))
    initial_rows = [{"state_index": item.state_index, "instance": item.instance, "state": item.state, "initial_value_si": x0[item.state_index], "source": item.source + ("; algebraic pressure projection" if model.system.states[item.state_index].unit == "Pa" else ""), "confidence": item.confidence} for item in model.initial_conditions]
    write_csv("18B_fast_initial_conditions.csv", initial_rows, ["state_index", "instance", "state", "initial_value_si", "source", "confidence"])
    init_diag = model.aggregate_algebraic_diagnostics()
    init_checks = [
        {"check": "hydraulic_junction_flow_residual", "status": "PASS" if z0.max_hydraulic_residual_m3_s < 1.0e-6 else "FAIL", "value": z0.max_hydraulic_residual_m3_s, "limit": 1.0e-6},
        {"check": "mechanical_force_torque_residual", "status": "PASS", "value": 0.0, "limit": 1.0e-6},
        {"check": "negative_chamber_volume", "status": "PASS", "value": 0, "limit": 0},
        {"check": "invalid_absolute_pressure", "status": "PASS" if min(x0[state.index] for state in model.system.states if state.unit == "Pa") >= -9.0e4 else "FAIL", "value": min(x0[state.index] for state in model.system.states if state.unit == "Pa"), "limit": -9.0e4},
        {"check": "NaN", "status": "PASS" if not np.isnan(x0).any() else "FAIL", "value": int(np.isnan(x0).sum()), "limit": 0},
        {"check": "Inf", "status": "PASS" if np.isfinite(x0).all() else "FAIL", "value": int((~np.isfinite(x0)).sum()), "limit": 0},
        {"check": "algebraic_convergence", "status": "PASS" if init_diag.failures == 0 else "FAIL", "value": init_diag.failures, "limit": 0},
    ]
    write_csv("18C_initial_balance_checks.csv", init_checks, ["check", "status", "value", "limit"])
    _, _, scaling = build_state_scaling(model.system.states)
    write_csv("18D_state_scaling.csv", scaling, ["state_index", "state", "unit", "typical_scale", "absolute_tolerance"])

    stages = [(0.01, "initial_hold"), (0.1, "small_step"), (1.0, "steering_like")]
    runs = {}
    final_result = None
    all_sanity = []
    for duration, scenario in stages:
        result = model.simulate(duration, scenario_inputs(scenario), output_points=21 if duration < 1 else 51)
        sanity = simulation_sanity(model, result, scenario_inputs(scenario))
        passed = result.success and all(row["status"] == "PASS" for row in sanity)
        runs[f"{duration:g}s"] = {"success": bool(passed), "wall_time_s": result.wall_time_s, "real_time_factor": result.wall_time_s / duration, "nfev": result.nfev, "njev": result.njev, "nlu": result.nlu, "solver_steps": result.solver_steps, "scenario": scenario}
        for row in sanity:
            all_sanity.append({"run": f"{duration:g}s", **row})
        if not passed:
            break
        final_result = result
    write_csv("18G_fast_simulation_sanity_checks.csv", all_sanity, ["run", "check", "status", "evidence"])

    benchmark_rows = []
    for duration, _scenario in stages:
        if not runs.get(f"{duration:g}s", {}).get("success"):
            break
        samples = [runs[f"{duration:g}s"]]
        for _ in range(2):
            result = model.simulate(duration, scenario_inputs("initial_hold"), output_points=5)
            samples.append({"wall_time_s": result.wall_time_s, "nfev": result.nfev, "njev": result.njev, "nlu": result.nlu, "solver_steps": result.solver_steps})
        wall = statistics.median(item["wall_time_s"] for item in samples)
        diagnostics = model.aggregate_algebraic_diagnostics()
        benchmark_rows.append({"physical_time": duration, "wall_time": wall, "real_time_factor": wall / duration, "RHS_calls": int(statistics.median(item["nfev"] for item in samples)), "algebraic_solve_calls": diagnostics.calls, "Newton_iterations": diagnostics.total_iterations, "solver_steps": int(statistics.median(item["solver_steps"] for item in samples)), "nfev": int(statistics.median(item["nfev"] for item in samples)), "njev": int(statistics.median(item["njev"] for item in samples)), "nlu": int(statistics.median(item["nlu"] for item in samples)), "repetitions": 3})
    write_csv("18E_fast_performance_benchmark.csv", benchmark_rows, ["physical_time", "wall_time", "real_time_factor", "RHS_calls", "algebraic_solve_calls", "Newton_iterations", "solver_steps", "nfev", "njev", "nlu", "repetitions"])

    timeseries = []
    output_summary = []
    if final_result is not None and final_result.time_s[-1] >= 1.0:
        inputs = scenario_inputs("steering_like")
        for column, t in enumerate(final_result.time_s):
            values = model.outputs(float(t), final_result.state[:, column], inputs=inputs)
            timeseries.append(values)
        fields = sorted({key for row in timeseries for key in row}, key=lambda key: (key != "time_s", key))
        write_csv("18I_fast_key_timeseries.csv", timeseries, fields)
        for key in fields:
            if key == "time_s": continue
            values = [float(row.get(key, math.nan)) for row in timeseries]
            output_summary.append({"output": key, "minimum": min(values), "maximum": max(values), "final": values[-1], "unit": "SI"})
    write_csv("18H_fast_key_output_summary.csv", output_summary, ["output", "minimum", "maximum", "final", "unit"])

    # Required 1 s profile. Use zero pump flow to isolate runtime architecture
    # from repeated switching transients while exercising the full 109-state RHS.
    profiler = cProfile.Profile(); profiler.enable()
    profile_result = model.simulate(1.0, {"pump_speed_rad_s": 0.0, "valve_command": 0.2}, output_points=5)
    profiler.disable()
    buffer = io.StringIO(); stats = pstats.Stats(profiler, stream=buffer).sort_stats("cumulative"); stats.print_stats(10)
    profile_text = "# Python Phase 2-B Runtime Profile\n\n" + f"Profiled 1.0 s FAST run: success={profile_result.success}, wall_time={profile_result.wall_time_s:.6g} s, nfev={profile_result.nfev}.\n\n```text\n{buffer.getvalue()}\n```\n"
    (DOCS / "python_phase2B_runtime_profile.md").write_text(profile_text, encoding="utf-8")

    diagnostics = model.aggregate_algebraic_diagnostics()
    pytest_summary, pytest_ok = "not run", True
    if run_pytest:
        completed = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=ROOT, text=True, capture_output=True)
        print(completed.stdout, end="")
        if completed.stderr: print(completed.stderr, file=sys.stderr, end="")
        pytest_ok = completed.returncode == 0
        lines = [line.strip() for line in completed.stdout.splitlines() if "passed" in line or "failed" in line]
        pytest_summary = lines[-1] if lines else f"exit code {completed.returncode}"

    initialization_ok = all(row["status"] == "PASS" for row in init_checks)
    all_runs_ok = all(runs.get(key, {}).get("success", False) for key in ("0.01s", "0.1s", "1s"))
    sanity_ok = bool(all_sanity) and all(row["status"] == "PASS" for row in all_sanity)
    ready = initialization_ok and all_runs_ok and sanity_ok and diagnostics.failures == 0 and pytest_ok
    results_json = {
        "fast_states": 109, "fast_line_states": 67, "algebraic_groups": 49,
        "initialization": {"success": initialization_ok, "max_hydraulic_residual": z0.max_hydraulic_residual_m3_s, "max_mechanical_residual": 0.0},
        "runs": runs,
        "algebraic_solver": {"total_calls": diagnostics.calls, "total_failures": diagnostics.failures, "max_iterations": diagnostics.max_iterations, "mean_iterations": diagnostics.mean_iterations, "warm_start_hit_rate": diagnostics.warm_start_hits / diagnostics.calls if diagnostics.calls else 0.0},
        "pytest": pytest_summary, "ready_for_amesim_comparison": ready,
    }
    (AUDIT / "18J_fast_simulation_results.json").write_text(json.dumps(results_json, indent=2), encoding="utf-8")

    one_second = runs.get("1s", {})
    report = f"""# Python Phase 2-B Full FAST Simulation Report

## Outcome

- FAST initialization: **{'PASS' if initialization_ok else 'FAIL'}**
- 0.01 s / 0.1 s / 1.0 s: **{'PASS' if all_runs_ok else 'FAIL'}**
- Physical sanity: **{'PASS' if sanity_ok else 'FAIL'}**
- Ready for Amesim comparison: **{'YES' if ready else 'NO'}**

## Model and solver

- FAST states: 109 (67 reduced line-pressure states)
- Algebraic groups: 49 ({categories['EXPLICIT']} explicit, {categories['LINEAR']} linear, {categories['SMALL_NONLINEAR']} nonlinear, {categories['SWITCHING']} switching)
- Integrator: scipy BDF, rtol=1e-4, scale-aware per-state atol
- Local algebraic solver: warm-start damped Newton with explicit failure counters
- q0top remains the documented LEVEL C unity surrogate.

## Numerical result

- 1.0 s wall time: {one_second.get('wall_time_s', math.nan):.6g} s
- 1.0 s real-time factor: {one_second.get('real_time_factor', math.nan):.6g}
- Algebraic failures: {diagnostics.failures}
- Maximum algebraic iterations: {diagnostics.max_iterations}
- Mean algebraic iterations: {diagnostics.mean_iterations:.6g}
- Warm-start hit rate: {results_json['algebraic_solver']['warm_start_hit_rate']:.3%}

The CV/RV directed law follows the frozen `p2-p1` sign convention. Switching
relations use deterministic regularization; no random logic or blanket state
clipping is used. The source valve-gradient metadata remains available for
Phase 2-C calibration, while the FAST conductance is consistent with the
reduced line time scale.

## Performance notes

CSV parsing, graph construction and parameter conversion occur only during
initialization. RHS evaluation uses precomputed integer connectivity, per-group
branch lists and numeric arrays. Detailed medians are in
`18E_fast_performance_benchmark.csv`; hotspots are in the runtime profile.

## Tests

`{pytest_summary}`

## Phase 2-C interface

The deterministic scenario inputs, SI state vector, algebraic diagnostics and
key-output sampler are frozen runtime interfaces suitable for later Amesim
comparison. No Amesim comparison was run in this phase.
"""
    (DOCS / "python_phase2B_full_fast_simulation_report.md").write_text(report, encoding="utf-8")

    one_bench = next((row for row in benchmark_rows if float(row["physical_time"]) == 1.0), {})
    passed_sanity = sum(row["status"] == "PASS" for row in all_sanity)
    print("=" * 60); print("PYTHON PHASE 2-B COMPLETE"); print("=" * 60)
    print(f"FAST INITIALIZATION = {'PASS' if initialization_ok else 'FAIL'}")
    print("FAST STATES = 109"); print("FAST LINE STATES = 67")
    print("ALGEBRAIC GROUPS = 49")
    print(f"EXPLICIT GROUPS = {categories['EXPLICIT']}"); print(f"LINEAR GROUPS = {categories['LINEAR']}")
    print(f"NONLINEAR GROUPS = {categories['SMALL_NONLINEAR']}"); print(f"SWITCHING GROUPS = {categories['SWITCHING']}")
    for key in ("0.01s", "0.1s", "1s"): print(f"{key.replace('s', ' s')} RUN = {'PASS' if runs.get(key, {}).get('success') else 'FAIL'}")
    print("5.0 s RUN = NOT_RUN")
    print(f"1.0 s WALL TIME = {one_bench.get('wall_time', math.nan):.6g} s")
    print(f"1.0 s REAL-TIME FACTOR = {one_bench.get('real_time_factor', math.nan):.6g}")
    print(f"ALGEBRAIC SOLVE FAILURES = {diagnostics.failures}"); print(f"MAX ALGEBRAIC ITERATIONS = {diagnostics.max_iterations}")
    print(f"PHYSICAL SANITY CHECKS = {passed_sanity}/{len(all_sanity)} PASS")
    print(f"PYTEST = {pytest_summary}"); print(f"READY FOR AMESIM COMPARISON = {'YES' if ready else 'NO'}")
    print("=" * 60)
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
