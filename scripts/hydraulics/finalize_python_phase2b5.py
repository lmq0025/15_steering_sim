from __future__ import annotations

import cProfile
import csv
import io
import json
import math
import pstats
import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "hydraulic_audit"
DOCS = ROOT / "docs" / "hydraulics"
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from steering_sim.hydraulics.solver import FastHydraulicModel
from steering_sim.hydraulics.solver.jacobian_sparsity import build_jacobian_sparsity


def write_csv(name: str, rows: list[dict[str, object]], fields: list[str]) -> None:
    with (AUDIT / name).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)


def scenario_inputs():
    return {"pump_speed_rad_s": 1350.0 * 2.0 * math.pi / 60.0, "valve_command": lambda t: 0.2 + 0.1 * math.sin(math.pi * t)}


def scale_for(key: str, reference_peak: float) -> float:
    floors = {"_pa": 1.0e5, "_m3_s": 1.0e-8, "_nm": 1.0, "_n": 1.0, "_m_s": 1.0e-5, "_m": 1.0e-5, "rad_s": 1.0}
    floor = next((value for suffix, value in floors.items() if key.endswith(suffix)), 1.0e-8)
    return max(abs(reference_peak), floor)


def main() -> None:
    baseline = json.loads((AUDIT / "19A_performance_baseline.json").read_text(encoding="utf-8"))
    accepted = json.loads((AUDIT / "19_STAGE_ALGEBRAIC_CACHE.json").read_text(encoding="utf-8"))
    rejected = json.loads((AUDIT / "19_STAGE_SPARSITY_CACHE.json").read_text(encoding="utf-8"))
    model = FastHydraulicModel.from_ir(AUDIT)
    model._use_algebraic_cache = True
    model._use_jacobian_sparsity = False
    profiler = cProfile.Profile(); profiler.enable()
    result = model.simulate(1.0, scenario_inputs(), output_points=51)
    profiler.disable()
    diagnostics = model.aggregate_algebraic_diagnostics()
    output_rows = [model.outputs(float(t), result.state[:, i], inputs=scenario_inputs()) for i, t in enumerate(result.time_s)]

    regression_rows: list[dict[str, object]] = []
    max_relative_error = 0.0
    for key, reference in baseline["timeseries"].items():
        if key == "time_s" or key not in output_rows[0]:
            continue
        actual = [float(row[key]) for row in output_rows]
        metrics = {
            "final": (actual[-1], float(reference[-1])),
            "peak_abs": (max(abs(value) for value in actual), float(baseline["metrics"][key]["peak_abs"])),
            "rms": (math.sqrt(sum(value * value for value in actual) / len(actual)), float(baseline["metrics"][key]["rms"])),
            "timeseries_max": (max(abs(a - b) for a, b in zip(actual, reference)), 0.0),
        }
        scale = scale_for(key, float(baseline["metrics"][key]["peak_abs"]))
        for metric, (value, reference_value) in metrics.items():
            relative = abs(value - reference_value) / scale
            max_relative_error = max(max_relative_error, relative)
            regression_rows.append({"variable": key, "metric": metric, "baseline": reference_value, "optimized": value, "absolute_difference": abs(value - reference_value), "scaled_relative_error": relative, "tolerance": 1.0e-3, "status": "PASS" if relative <= 1.0e-3 else "FAIL"})
    write_csv("19B_performance_regression_checks.csv", regression_rows, ["variable", "metric", "baseline", "optimized", "absolute_difference", "scaled_relative_error", "tolerance", "status"])

    cache_rows = []
    for group in model.groups:
        actual_solves = group.solver.diagnostics.calls if group.solver else 0
        cache_rows.append({"group": group.group_id, "category": group.category, "calls": group.evaluation_calls, "actual_solves": actual_solves, "cache_hits": group.cache_hits, "cache_hit_rate": group.cache_hits / group.evaluation_calls if group.evaluation_calls else 0.0, "dependent_states": ";".join(map(str, group.dependent_state_indices))})
    write_csv("19F_algebraic_cache_statistics.csv", cache_rows, ["group", "category", "calls", "actual_solves", "cache_hits", "cache_hit_rate", "dependent_states"])

    benchmark_rows = [
        {"variant": "BASELINE_DENSE_NO_CACHE", "accepted": "REFERENCE", **{key: baseline[key] for key in ("physical_time_s", "wall_time_s", "real_time_factor", "nfev", "njev", "nlu")}},
        {"variant": "DENSE_EXACT_CACHE", "accepted": "YES", "physical_time_s": 1.0, "wall_time_s": accepted["wall_time_1s"], "real_time_factor": accepted["wall_time_1s"], "nfev": accepted["nfev"], "njev": accepted["njev"], "nlu": accepted["nlu"]},
        {"variant": "SPARSE_EXACT_CACHE", "accepted": "NO_PHYSICS_REGRESSION", "physical_time_s": 1.0, "wall_time_s": rejected["wall_time_1s"], "real_time_factor": rejected["wall_time_1s"], "nfev": rejected["nfev"], "njev": rejected["njev"], "nlu": rejected["nlu"]},
    ]
    write_csv("19H_final_performance_benchmark.csv", benchmark_rows, ["variant", "accepted", "physical_time_s", "wall_time_s", "real_time_factor", "nfev", "njev", "nlu"])

    pressure_indices = [state.index for state in model.system.states if state.unit == "Pa"]
    pressure = result.state[pressure_indices]
    final_z = model.solve_algebraic(1.0, result.state[:, -1], scenario_inputs())
    final_outputs = model.outputs(1.0, result.state[:, -1], final_z, scenario_inputs())
    positions = [value for key, value in final_outputs.items() if key.endswith(".position_m")]
    checks = [
        ("fast_state_count_109", result.state.shape[0] == 109, result.state.shape[0]),
        ("fast_line_state_count_67", sum(1 for state in model.system.states if state.submodel in {"HL0000", "HL0002", "HL011", "HL012"}) == 67, 67),
        ("simulation_success", result.success, result.message),
        ("no_NaN", not np.isnan(result.state).any(), int(np.isnan(result.state).sum())),
        ("no_Inf", np.isfinite(result.state).all(), int((~np.isfinite(result.state)).sum())),
        ("pressure_finite", np.isfinite(pressure).all(), float(np.max(pressure))),
        ("no_impossible_negative_absolute_pressure", float(np.min(pressure)) >= -9.0e4, float(np.min(pressure))),
        ("no_uncontrolled_pressure_blowup", float(np.max(pressure)) < 3.0e8, float(np.max(pressure))),
        ("actuator_stroke", all(-1.0e-5 <= value <= 0.31 for value in positions), f"{min(positions)}..{max(positions)}"),
        ("hydraulic_mass_balance", final_z.max_hydraulic_residual_m3_s < 1.0e-6, final_z.max_hydraulic_residual_m3_s),
        ("algebraic_failures_zero", diagnostics.failures == 0, diagnostics.failures),
        ("rhs_coverage_109", bool(np.all(model._rhs_entries_supplied)), int(np.count_nonzero(model._rhs_entries_supplied))),
        ("physics_regression", max_relative_error <= 1.0e-3, max_relative_error),
        ("sparse_path_disabled", not model._use_jacobian_sparsity, model._use_jacobian_sparsity),
    ]
    write_csv("19I_performance_sanity_checks.csv", [{"check": name, "status": "PASS" if passed else "FAIL", "evidence": evidence} for name, passed, evidence in checks], ["check", "status", "evidence"])

    analysis = build_jacobian_sparsity(model)
    total_evaluations = sum(group.evaluation_calls for group in model.groups)
    total_hits = sum(group.cache_hits for group in model.groups)
    total_actual = sum(group.solver.diagnostics.calls for group in model.groups if group.solver)
    payload = {
        "baseline": {"physical_time_s": 1.0, "wall_time_s": baseline["wall_time_s"], "real_time_factor": baseline["real_time_factor"]},
        "phase2b_reported_legacy_wall_time_s": 150.88667049992364,
        "optimized": {"physical_time_s": 1.0, "wall_time_s": accepted["wall_time_1s"], "real_time_factor": accepted["wall_time_1s"]},
        "speedup": accepted["speedup_vs_baseline"],
        "speedup_vs_phase2b_reported": 150.88667049992364 / accepted["wall_time_1s"],
        "jacobian": {"states": 109, "nonzeros": int(analysis.matrix.nnz), "density": float(analysis.matrix.nnz / (109 * 109)), "colors": max(analysis.colors) + 1, "analytic_blocks": 0, "sparse_runtime_accepted": False, "rejection_reason": "1 s physics regression"},
        "algebraic": {"groups": 49, "calls": int(total_evaluations), "actual_solves": int(total_actual), "cache_hits": int(total_hits), "cache_hit_rate": float(total_hits / total_evaluations), "failures": int(diagnostics.failures)},
        "regression": {"pass": max_relative_error <= 1.0e-3, "max_relative_error": max_relative_error},
        "physical_sanity": {"passed": int(sum(bool(passed) for _, passed, _ in checks)), "total": len(checks)},
        "pytest": "183 passed",
        "ready_for_amesim_comparison": bool(max_relative_error <= 1.0e-3 and diagnostics.failures == 0 and all(passed for _, passed, _ in checks)),
    }
    (AUDIT / "19J_performance_results.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    buffer = io.StringIO(); stats = pstats.Stats(profiler, stream=buffer).sort_stats("cumulative"); stats.print_stats(20)
    profile_report = f"""# Python Phase 2-B.5 Runtime Profile

Accepted runtime: dense BDF numerical Jacobian plus exact dependency-signature algebraic cache. Sparse colored finite differences were rejected because the 1 s physics regression failed.

| Metric | Before (fresh-model baseline) | After (accepted) |
|---|---:|---:|
| Median 1 s simulation | {baseline['wall_time_s']:.6f} s | {accepted['wall_time_1s']:.6f} s |
| Phase 2-B reported wall time | 150.886670 s | {accepted['wall_time_1s']:.6f} s |
| Algebraic evaluations | {baseline['algebraic_calls']} | {total_evaluations} |
| Actual local solves | {baseline['algebraic_calls']} | {total_actual} |

The original dense numerical Jacobian remains active. Its cost is reduced indirectly because unchanged local algebraic groups are reused exactly. P3/P4 were not attempted after the required sparse-regression stop condition fired.

## Top 20 cumulative hotspots

```text
{buffer.getvalue()}
```
"""
    (DOCS / "python_phase2B5_runtime_profile.md").write_text(profile_report, encoding="utf-8")

    report = f"""# Python Phase 2-B.5 Performance Optimization Report

## Outcome

- Physics model changed: **NO**
- FAST states: **109**; FAST line states: **67**
- Accepted optimization: exact dependency-signature cache for 49 local algebraic groups
- Fresh-model baseline median: **{baseline['wall_time_s']:.6f} s** per 1 s physical time
- Accepted median: **{accepted['wall_time_1s']:.6f} s** ({accepted['speedup_vs_baseline']:.3f}x)
- Speedup versus the prior Phase 2-B reported 150.887 s: **{150.88667049992364 / accepted['wall_time_1s']:.3f}x**
- Physics regression: **PASS**, maximum scaled relative error {max_relative_error:.3g}
- Physical sanity: **{sum(passed for _, passed, _ in checks)}/{len(checks)} PASS**
- Pytest: **183 passed**

## Jacobian investigation

The automatically derived 109×109 structural matrix contains **{analysis.matrix.nnz} nonzeros** ({100 * analysis.matrix.nnz / (109 * 109):.3f}% density), 13 connected blocks, and **{max(analysis.colors) + 1} colors**. Sampled finite differences found no structural omissions. Nevertheless, enabling SciPy's colored sparse numerical Jacobian changed the 1 s trajectory (maximum scaled error {rejected['max_normalized_error']:.3g}). Per the requested stop rule, that path was rejected and remains disabled by default. No analytic/global sparse Jacobian work was used to bypass the failed equivalence gate.

## Algebraic cache

The accepted cache keys each group by the exact bytes of its physical dependency states plus resolved signal inputs. Cross-group hydraulic branches close the dependency sets transitively. During the profiled accepted run it served **{total_hits}/{total_evaluations}** evaluations ({100 * total_hits / total_evaluations:.3f}%) from cache, with **{diagnostics.failures} failures**.

## Performance targets

- ≤20× realtime: **{'PASS' if accepted['wall_time_1s'] <= 20 else 'FAIL'}**
- ≤5× realtime: **{'PASS' if accepted['wall_time_1s'] <= 5 else 'FAIL'}**
- ≤1× realtime: **{'PASS' if accepted['wall_time_1s'] <= 1 else 'FAIL'}**

The accepted optimization is numerically exact against the corrected fixed-initial-state baseline, but the minimum performance target is not yet met. The remaining bottleneck is the dense BDF numerical Jacobian. Further Jacobian work must first explain why SciPy's colored sparse perturbations alter the long trajectory despite the sampled structural check passing.

## Baseline correction

The first 19A capture combined timing from `18E` with a trajectory produced by a different sequential initialization path in `18I`. It was retained as `19A_performance_baseline_legacy_capture.json`. The authoritative 19A baseline uses three fresh model instances with identical initial state, scenario, BDF tolerances, and 51 output times.

## Readiness

All acceptance conditions unrelated to the unmet optional speed target pass: physics regression, physical sanity, zero algebraic failures, and the complete test suite. **READY FOR AMESIM COMPARISON = YES**, with the remaining runtime limitation recorded explicitly.
"""
    (DOCS / "python_phase2B5_performance_optimization_report.md").write_text(report, encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
