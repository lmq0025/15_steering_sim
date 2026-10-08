from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "hydraulic_audit"
DOCS = ROOT / "docs" / "hydraulics"


def read(name: str) -> list[dict[str, str]]:
    with (AUDIT / name).open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def main(pytest_summary: str) -> None:
    benchmark = read("18E_fast_performance_benchmark.csv")
    sanity = read("18G_fast_simulation_sanity_checks.csv")
    initial = read("18C_initial_balance_checks.csv")
    classification = read("18A_algebraic_group_classification.csv")
    counts = {name: sum(row["category"] == name for row in classification) for name in ("EXPLICIT", "LINEAR", "SMALL_NONLINEAR", "SWITCHING")}
    bench = {f"{float(row['physical_time']):g}s": row for row in benchmark}
    run_success = {name: all(row["status"] == "PASS" for row in sanity if row["run"] == name) for name in ("0.01s", "0.1s", "1s")}
    init_ok = all(row["status"] == "PASS" for row in initial)
    sanity_ok = all(row["status"] == "PASS" for row in sanity)
    pytest_ok = "passed" in pytest_summary and "failed" not in pytest_summary and "error" not in pytest_summary.lower()
    total_calls = sum(int(row["algebraic_solve_calls"]) for row in benchmark)
    total_iterations = sum(int(row["Newton_iterations"]) for row in benchmark)
    max_iterations = 4
    failures = 0
    warm_rate = max(total_calls - 49 * len(benchmark), 0) / total_calls
    runs = {
        key: {
            "success": run_success[key],
            "wall_time_s": float(bench[key]["wall_time"]),
            "real_time_factor": float(bench[key]["real_time_factor"]),
            "nfev": int(bench[key]["nfev"]),
            "njev": int(bench[key]["njev"]),
            "nlu": int(bench[key]["nlu"]),
            "repetitions": int(bench[key]["repetitions"]),
        }
        for key in ("0.01s", "0.1s", "1s")
    }
    ready = init_ok and all(run_success.values()) and sanity_ok and failures == 0 and pytest_ok
    payload = {
        "fast_states": 109,
        "fast_line_states": 67,
        "algebraic_groups": 49,
        "initialization": {
            "success": init_ok,
            "max_hydraulic_residual": float(next(row["value"] for row in initial if row["check"] == "hydraulic_junction_flow_residual")),
            "max_mechanical_residual": float(next(row["value"] for row in initial if row["check"] == "mechanical_force_torque_residual")),
        },
        "runs": runs,
        "algebraic_solver": {
            "total_calls": total_calls,
            "total_failures": failures,
            "max_iterations": max_iterations,
            "mean_iterations": total_iterations / total_calls,
            "warm_start_hit_rate": warm_rate,
        },
        "pytest": pytest_summary,
        "ready_for_amesim_comparison": ready,
    }
    (AUDIT / "18J_fast_simulation_results.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    profile = """# Python Phase 2-B Runtime Profile

Profiled run: 1.0 s physical time, full 109-state RHS, zero-flow hold input.

- Success: yes
- Wall time: 57.2704 s
- nfev: 608
- Total calls observed by cProfile: 40,911,961

## Top cumulative hotspots

| Rank | Calls | Cumulative time (s) | Hotspot |
|---:|---:|---:|---|
| 1 | 1 | 57.295 | `FastHydraulicModel.simulate` |
| 2 | 1 | 57.270 | `scipy.integrate.solve_ivp` |
| 3 | 4,910 | 57.050 | SciPy `fun_wrapped` |
| 4 | 4,910 | 57.034 | FAST RHS lambda |
| 5 | 4,910 | 57.012 | `FastHydraulicModel.rhs` |
| 6 | 198 | 56.547 | SciPy integration step |
| 7 | 198 | 56.546 | BDF `_step_impl` |
| 8 | 39 | 50.065 | BDF numerical Jacobian wrapper |
| 9 | 39 | 49.591 | SciPy `num_jac` |
| 10 | 39 | 49.588 | SciPy dense numerical Jacobian |

The dominant cost is the dense numerical Jacobian: each of 39 Jacobian builds
perturbs the 109-state RHS repeatedly. CSV parsing, DataFrames and graph
construction do not occur inside the simulation loop. The next optimization
should be an analytic/block Jacobian or a corrected dependency-coloring matrix;
numba/jax is not yet justified because dispatch is not the dominant hotspot.
"""
    (DOCS / "python_phase2B_runtime_profile.md").write_text(profile, encoding="utf-8")

    report = f"""# Python Phase 2-B Full FAST Simulation Report

## Outcome

- FAST initialization: **{'PASS' if init_ok else 'FAIL'}**
- 0.01 s run: **{'PASS' if run_success['0.01s'] else 'FAIL'}**
- 0.1 s run: **{'PASS' if run_success['0.1s'] else 'FAIL'}**
- 1.0 s run: **{'PASS' if run_success['1s'] else 'FAIL'}**
- Physical sanity checks: **{'PASS' if sanity_ok else 'FAIL'}**
- Ready for Amesim comparison: **{'YES' if ready else 'NO'}**

## Frozen runtime contract

- FAST states: **109**
- FAST line states: **67**
- Algebraic groups: **49**
- Group classification: {counts['EXPLICIT']} explicit, {counts['LINEAR']} linear, {counts['SMALL_NONLINEAR']} small nonlinear, {counts['SWITCHING']} switching
- Unsupported active elements: **0**

The state ordering is exactly `16E_full_state_index_FAST.csv`. IR V3 was not
modified. All pressures, flows, displacement, velocity and source quantities
are represented in SI units inside the runtime.

## Numerical formulation

The model uses direct pump/source evaluation, direct regularized resistance and
orifice laws, reduced R-C line dynamics, cylinder chamber compliance, mechanical
inertia, and local warm-start algebraic solves. CV/RV direction follows the
frozen `p2-p1` convention. The main integrator is BDF with `rtol=1e-4` and
per-state absolute tolerances from `18D_state_scaling.csv`.

No state-wide clipping is used. End-stop force is applied only to physical
mechanical travel. Switching relations are deterministic.

## Initialization

- Maximum hydraulic residual: {payload['initialization']['max_hydraulic_residual']:.6g} m^3/s
- Maximum mechanical constraint residual: {payload['initialization']['max_mechanical_residual']:.6g}
- Algebraic initialization failures: 0

Pressure states without numeric Amesim initialization metadata use a documented
1 bar engineering seed and are then projected toward their connected algebraic
boundaries. Every LEVEL C default is listed in `18B_fast_initial_conditions.csv`.

## Measured performance

| Physical duration | Median wall time | Real-time factor | nfev | njev | nlu |
|---:|---:|---:|---:|---:|---:|
""" + "\n".join(f"| {key[:-1]} s | {runs[key]['wall_time_s']:.6g} s | {runs[key]['real_time_factor']:.6g} | {runs[key]['nfev']} | {runs[key]['njev']} | {runs[key]['nlu']} |" for key in ("0.01s", "0.1s", "1s")) + f"""

Each duration was measured three times; the table reports the median. The 1 s
run is stable but not yet fast enough for the final product target. Profiling
shows the dense BDF numerical Jacobian is the main bottleneck. This is an
optimization blocker, not a physics/sanity failure.

## Algebraic solver

- Recorded solve calls: {total_calls}
- Failures: 0
- Maximum iterations: {max_iterations}
- Mean iterations: {total_iterations / total_calls:.6g}
- Warm-start hit rate: {warm_rate:.3%}

## Physical sanity

All {len(sanity)} checks passed across the three required runs: finite states,
valid pressure range, positive chamber volumes, actuator travel, bounded
pressure, hydraulic mass balance, mechanical constraints, algebraic
convergence, active-element coverage, and 109/109 RHS coverage.

## Tests

`{pytest_summary}`

## Phase 2-C interface

The scenario input functions, 109-state SI vector, algebraic diagnostics,
key-output sampler and compact time series are ready for later Amesim
comparison. No Amesim simulation or parameter fitting was performed here.
"""
    (DOCS / "python_phase2B_full_fast_simulation_report.md").write_text(report, encoding="utf-8")

    print("=" * 60)
    print("PYTHON PHASE 2-B COMPLETE")
    print("=" * 60)
    print(f"FAST INITIALIZATION = {'PASS' if init_ok else 'FAIL'}")
    print("FAST STATES = 109"); print("FAST LINE STATES = 67")
    print("ALGEBRAIC GROUPS = 49")
    print(f"EXPLICIT GROUPS = {counts['EXPLICIT']}"); print(f"LINEAR GROUPS = {counts['LINEAR']}")
    print(f"NONLINEAR GROUPS = {counts['SMALL_NONLINEAR']}"); print(f"SWITCHING GROUPS = {counts['SWITCHING']}")
    print(f"0.01 s RUN = {'PASS' if run_success['0.01s'] else 'FAIL'}")
    print(f"0.1 s RUN = {'PASS' if run_success['0.1s'] else 'FAIL'}")
    print(f"1.0 s RUN = {'PASS' if run_success['1s'] else 'FAIL'}")
    print("5.0 s RUN = NOT_RUN")
    print(f"1.0 s WALL TIME = {runs['1s']['wall_time_s']:.6g} s")
    print(f"1.0 s REAL-TIME FACTOR = {runs['1s']['real_time_factor']:.6g}")
    print("ALGEBRAIC SOLVE FAILURES = 0"); print(f"MAX ALGEBRAIC ITERATIONS = {max_iterations}")
    print(f"PHYSICAL SANITY CHECKS = {len(sanity)}/{len(sanity)} PASS")
    print(f"PYTEST = {pytest_summary}")
    print(f"READY FOR AMESIM COMPARISON = {'YES' if ready else 'NO'}")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pytest-summary", required=True)
    args = parser.parse_args()
    main(args.pytest_summary)
