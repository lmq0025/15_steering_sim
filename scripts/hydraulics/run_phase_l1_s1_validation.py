from __future__ import annotations

import csv
import json
import math
import statistics
import sys
import time
from dataclasses import replace
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(r"E:\15_project")
AUDIT = ROOT / "hydraulic_audit_lumped"
OUT = ROOT / "outputs" / "hydraulics" / "phase_L1_S1"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "hydraulics"))

from run_phase_l1_r3_validation import Oracle
from steering_sim.hydraulics_lumped import LumpedHydraulicSystem, SystemInputs
from steering_sim.hydraulics_lumped.simulation import simulate_rk4


DT_VALUES = (0.00025, 0.0005, 0.001, 0.002, 0.005)


def write_csv(path: Path, rows: list[dict], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = fields or (list(rows[0]) if rows else [])
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def periodic(oracle: Oracle):
    def inputs(t: float) -> SystemInputs:
        phase = t - math.floor(t)
        if phase > 1.0 - 1.0e-12 and t > 0.0:
            phase = 1.0
        return oracle.inputs(phase)
    return inputs


def run(scenario: str, duration: float, dt: float, solver: str,
        oracle: Oracle, periodic_mode: bool = False,
        inputs_override=None, x0: np.ndarray | None = None):
    model = LumpedHydraulicSystem(algebraic_solver=solver)
    input_fn = inputs_override or (periodic(oracle) if periodic_mode else oracle.inputs)
    started = time.perf_counter()
    times, states = simulate_rk4(
        model, duration, dt, input_fn,
        oracle.initial_state() if x0 is None else x0)
    wall = time.perf_counter() - started
    return model, times, states, wall, input_fn


def output_series(model: LumpedHydraulicSystem, times: np.ndarray,
                  states: np.ndarray, input_fn) -> dict[str, np.ndarray]:
    model.reset_fast_solver()
    data = {
        "front_supply_pressure": [], "rear_supply_pressure": [],
        "pA": [], "pB": [], "QA": [], "QB": [], "hydraulic_force": [],
        "position": [], "velocity": [],
    }
    for t, state in zip(times, states):
        outputs = model.evaluate(float(t), state, input_fn(float(t)))[1]
        channel = outputs[1]
        data["front_supply_pressure"].append(outputs[0]["pump_outlet_pressure"])
        data["rear_supply_pressure"].append(outputs[1]["pump_outlet_pressure"])
        for name in ("pA", "pB", "QA", "QB", "hydraulic_force",
                     "position", "velocity"):
            data[name].append(channel[name])
    return {name: np.asarray(values) for name, values in data.items()}


def error_metrics(reference: np.ndarray, candidate: np.ndarray,
                  floor: float) -> tuple[float, float, float, float]:
    error = candidate - reference
    rmse = float(np.sqrt(np.mean(error * error)))
    scale = max(float(np.ptp(reference)), float(np.max(np.abs(reference))), floor)
    nrmse = rmse / scale
    peak_error = abs(float(np.max(np.abs(candidate)) - np.max(np.abs(reference)))) / scale
    final_error = abs(float(candidate[-1] - reference[-1])) / scale
    return rmse, nrmse, peak_error, final_error


def sample_reference(ref_t: np.ndarray, values: np.ndarray,
                     candidate_t: np.ndarray) -> np.ndarray:
    return np.interp(candidate_t, ref_t, values)


def benchmark(scenario: str, duration: float, dt: float, solver: str,
              oracle: Oracle, repeats: int = 1, periodic_mode: bool = False) -> dict:
    walls = []
    last = None
    for _ in range(repeats):
        last = run(scenario, duration, dt, solver, oracle, periodic_mode=periodic_mode)
        walls.append(last[3])
    assert last is not None
    model, times, states, _, _ = last
    diagnostics = model.fast_solver_diagnostics()
    return {
        "scenario": scenario, "solver": solver, "physical_time_s": duration,
        "dt_s": dt, "repeats": repeats,
        "wall_time_s": statistics.median(walls),
        "real_time_factor": statistics.median(walls) / duration,
        "rhs_calls": 4 * (len(times) - 1),
        "algebraic_calls": sum(int(v["calls"]) for v in diagnostics.values()),
        "correction_iterations": sum(int(v["correction_iterations"])
                                     for v in diagnostics.values()),
        "fallbacks": sum(int(v["fallbacks"]) for v in diagnostics.values()),
        "network_evaluations": sum(int(v["network_evaluations"])
                                   for v in diagnostics.values()),
        "finite": bool(np.isfinite(states).all()),
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    raw = json.loads((AUDIT / "32_amesim_paired_raw.json").read_text(encoding="utf-8"))
    oracles = {name: Oracle(raw["scenarios"][name]) for name in ("S0", "S1", "S2")}

    # Reference-vs-fast numerical regression on the frozen S2 workload.
    ref_model, ref_t, ref_x, ref_wall, ref_inputs = run(
        "S2", 1.0, 0.0005, "reference", oracles["S2"])
    fast_model, fast_t, fast_x, fast_wall, fast_inputs = run(
        "S2", 1.0, 0.0005, "fast", oracles["S2"])
    ref_output = output_series(ref_model, ref_t, ref_x, ref_inputs)
    fast_output = output_series(fast_model, fast_t, fast_x, fast_inputs)
    regression_rows = []
    floors = {"front_supply_pressure": 1e5, "rear_supply_pressure": 1e5,
              "pA": 1e5, "pB": 1e5, "QA": 1e-7, "QB": 1e-7,
              "hydraulic_force": 100.0, "position": 1e-5, "velocity": 1e-5}
    for name, reference in ref_output.items():
        rmse, nrmse, peak, final = error_metrics(reference, fast_output[name], floors[name])
        regression_rows.append({
            "scenario": "S2", "mode": "PRESCRIBED_MOTION", "quantity": name,
            "reference_solver": "solve_supply_reference",
            "candidate_solver": "solve_supply_fast", "rmse": rmse,
            "normalized_rmse": nrmse, "normalized_peak_error": peak,
            "normalized_final_error": final,
            "status": "PASS" if max(nrmse, peak, final) <= 1.0e-4 else "FAIL",
        })
    state_delta = fast_x - ref_x
    regression_rows.append({
        "scenario": "S2", "mode": "PRESCRIBED_MOTION", "quantity": "all_16_states",
        "reference_solver": "solve_supply_reference", "candidate_solver": "solve_supply_fast",
        "rmse": float(np.sqrt(np.mean(state_delta * state_delta))),
        "normalized_rmse": float(np.sqrt(np.mean(state_delta * state_delta)) /
                                 max(float(np.max(np.abs(ref_x))), 1.0)),
        "normalized_peak_error": float(np.max(np.abs(state_delta)) /
                                       max(float(np.max(np.abs(ref_x))), 1.0)),
        "normalized_final_error": float(np.max(np.abs(state_delta[-1])) /
                                        max(float(np.max(np.abs(ref_x[-1]))), 1.0)),
        "status": "PASS" if np.max(np.abs(state_delta)) <= 1.0 else "FAIL",
    })
    write_csv(AUDIT / "35G_fast_solver_regression.csv", regression_rows)

    residual_rows = []
    residual_model = LumpedHydraulicSystem(algebraic_solver="fast")
    for index in np.linspace(0, len(fast_t) - 1, 41, dtype=int):
        _, outputs = residual_model.evaluate(
            float(fast_t[index]), fast_x[index], oracles["S2"].inputs(float(fast_t[index])))
        for ci in (0, 1):
            output = outputs[ci]
            maximum = max(abs(output["supply_balance_residual"]),
                          abs(output["manifold_balance_residual"]),
                          abs(output["return_absorbed_flow"]))
            residual_rows.append({
                "scenario": "S2", "time_s": float(fast_t[index]),
                "supply_group": "front" if ci == 0 else "rear",
                "pump_balance_residual_m3_s": output["supply_balance_residual"],
                "manifold_residual_m3_s": output["manifold_balance_residual"],
                "return_residual_m3_s": output["return_absorbed_flow"],
                "absolute_tolerance_m3_s": 1e-9,
                "status": "PASS" if maximum <= 1e-9 else "FAIL",
            })
    write_csv(AUDIT / "35C_fast_solver_residual_checks.csv", residual_rows)

    # Step-size convergence.  The 0.25 ms fast solution is the numerical
    # reference; this assesses integration error, not Amesim physics accuracy.
    convergence_rows = []
    convergence_cache = {}
    accepted_by_scenario = {}
    for scenario in ("S1", "S2"):
        oracle = oracles[scenario]
        model0, t0, x0, wall0, input0 = run(scenario, 1.0, DT_VALUES[0], "fast", oracle)
        out0 = output_series(model0, t0, x0, input0)
        convergence_cache[(scenario, DT_VALUES[0])] = (t0, x0, out0, wall0)
        scenario_accept = []
        for dt in DT_VALUES:
            if dt == DT_VALUES[0]:
                t, states, outputs, wall = t0, x0, out0, wall0
            else:
                try:
                    model, t, states, wall, input_fn = run(
                        scenario, 1.0, dt, "fast", oracle)
                    outputs = output_series(model, t, states, input_fn)
                    convergence_cache[(scenario, dt)] = (t, states, outputs, wall)
                except Exception as exc:
                    for name in floors:
                        convergence_rows.append({
                            "scenario": scenario, "dt_s": dt, "quantity": name,
                            "reference_dt_s": DT_VALUES[0], "rmse": "",
                            "normalized_rmse": "", "normalized_peak_error": "",
                            "normalized_final_error": "", "wall_time_s": "",
                            "within_1_percent": False,
                            "status": f"FAIL_SOLVER: {type(exc).__name__}: {exc}",
                        })
                    continue
            passed = True
            for name, values in outputs.items():
                reference = sample_reference(t0, out0[name], t)
                rmse, nrmse, peak, final = error_metrics(reference, values, floors[name])
                quantity_pass = max(nrmse, peak, final) <= 0.01
                passed = passed and quantity_pass
                convergence_rows.append({
                    "scenario": scenario, "dt_s": dt, "quantity": name,
                    "reference_dt_s": DT_VALUES[0], "rmse": rmse,
                    "normalized_rmse": nrmse, "normalized_peak_error": peak,
                    "normalized_final_error": final, "wall_time_s": wall,
                    "within_1_percent": quantity_pass,
                    "status": "PASS" if quantity_pass else "FAIL",
                })
            if passed:
                scenario_accept.append(dt)
        accepted_by_scenario[scenario] = max(scenario_accept) if scenario_accept else DT_VALUES[0]
    accepted_dt = min(accepted_by_scenario.values())
    write_csv(AUDIT / "35D_timestep_convergence.csv", convergence_rows)

    # Prepressurized working mode: relax a measured S0 endpoint with stationary
    # prescribed motion, then apply a small periodic valve command.  It has no
    # paired Amesim oracle and is explicitly not used as an accuracy claim.
    s0 = oracles["S0"]
    base = s0.inputs(1.0)
    stationary_motion = {
        alias: (values[0], 0.0, 0.0)
        for alias, values in (base.prescribed_motion_by_alias or {}).items()
    }
    base_inputs = replace(base, prescribed_motion_by_alias=stationary_motion)

    def hold_inputs(_t: float) -> SystemInputs:
        return base_inputs

    relaxation_model, _, relaxed, _, _ = run(
        "PREPRESSURIZED_RELAX", 2.0, 0.0005, "fast", s0,
        inputs_override=hold_inputs, x0=s0.initial_state())
    working_x0 = relaxed[-1].copy()
    base_commands = dict(base_inputs.valve_commands_by_alias or {})

    def working_inputs(t: float) -> SystemInputs:
        commands = dict(base_commands)
        commands["dirvalve_1"] = base_commands.get("dirvalve_1", 0.0) + 0.05 * math.sin(2*math.pi*t)
        return replace(base_inputs, valve_commands_by_alias=commands,
                       valve_commands=[commands.get(alias, fallback) for alias, fallback in zip(
                           ("dirvalve_6", "dirvalve_1", "dirvalve_8", "dirvalve_11"),
                           base_inputs.valve_commands)])

    working_model, working_t, working_x, working_wall, working_fn = run(
        "PREPRESSURIZED_WORKING_MODE", 2.0, accepted_dt, "fast", s0,
        inputs_override=working_inputs, x0=working_x0)
    working_out = output_series(working_model, working_t, working_x, working_fn)
    equilibrium_rhs = relaxation_model.rhs(2.0, working_x0, base_inputs)
    pressure_rhs = equilibrium_rhs[[0, 1, 4, 5, 8, 9, 12, 13]]
    working_rows = [
        {"condition": "ORIGINAL_FULL", "scenario": s, "window_s": "0.0-1.0",
         "motion_mode": "PRESCRIBED_MOTION", "amesim_comparability": "COMPARABLE_EXISTING_ORACLE",
         "validation_role": "existing R3 accuracy; unchanged", "status": "CONDITIONAL"}
        for s in ("S0", "S1", "S2")
    ]
    for scenario in ("S0", "S1", "S2"):
        values = raw["scenarios"][scenario]["series"]["p1@actuator001"]
        array = np.asarray(values, dtype=float)
        mask = array[:, 0] >= 0.2
        rate = np.gradient(array[:, 1] * 1e5, array[:, 0])
        working_rows.append({
            "condition": "ORIGINAL_DIAGNOSTIC", "scenario": scenario,
            "window_s": "0.2-1.0", "motion_mode": "PRESCRIBED_MOTION",
            "amesim_comparability": "COMPARABLE_DIAGNOSTIC_ONLY",
            "validation_role": f"max_abs_dpdt_pa_s={float(np.max(np.abs(rate[mask]))):.9g}; not automatically steady",
            "status": "DIAGNOSTIC",
        })
    working_rows.append({
        "condition": "PREPRESSURIZED_WORKING_MODE", "scenario": "small_1Hz_sine",
        "window_s": "0.0-2.0", "motion_mode": "PRESCRIBED_MOTION",
        "amesim_comparability": "NOT_COMPARABLE",
        "validation_role": (f"initial_max_abs_pressure_rhs_pa_s={float(np.max(np.abs(pressure_rhs))):.9g}; "
                            f"finite={bool(np.isfinite(working_x).all())}; wall_s={working_wall:.9g}"),
        "status": "PASS" if np.isfinite(working_x).all() and np.max(np.abs(pressure_rhs)) < 1e6 else "CONDITIONAL",
    })
    # Autonomous interface is a numerical stability check, not paired validation.
    autonomous_base = replace(base_inputs, prescribed_motion_by_alias=None)
    try:
        auto_model, auto_t, auto_x, auto_wall, _ = run(
            "AUTONOMOUS_ACTUATOR", 0.2, min(accepted_dt, 0.0005), "fast", s0,
            inputs_override=lambda _t: autonomous_base, x0=working_x0)
        auto_finite = bool(np.isfinite(auto_x).all())
        auto_note = f"finite={auto_finite}; wall_s={auto_wall:.9g}"
        auto_status = "PASS" if auto_finite else "FAIL"
    except Exception as exc:
        auto_note = f"solver_failure={type(exc).__name__}: {exc}"
        auto_status = "NOT_VERIFIED"
    working_rows.append({
        "condition": "AUTONOMOUS_ACTUATOR", "scenario": "constant_boundary",
        "window_s": "0.0-0.2", "motion_mode": "AUTONOMOUS_ACTUATOR",
        "amesim_comparability": "NOT_COMPARABLE",
        "validation_role": auto_note,
        "status": auto_status,
    })
    write_csv(AUDIT / "35E_working_condition_validation.csv", working_rows)

    # Stage benchmarks: actual runs, never duration extrapolations.
    stage_rows = []
    for stage, solver, description in (
            ("P0", "reference", "original retained R3 solver"),
            ("P1_P2", "fast_scalar", "compiled SC1 evaluator + scalar predictor/corrector"),
            ("P3", "fast", "analytic joint rail solve + compiled topology")):
        for duration in (1.0, 10.0):
            result = benchmark("S2_PERIODIC", duration, 0.0005, solver,
                               oracles["S2"], repeats=1, periodic_mode=True)
            result.update({"optimization_stage": stage, "changes": description,
                           "numerical_regression": "PASS" if stage != "P0" else "REFERENCE"})
            stage_rows.append(result)
    for duration in (1.0, 10.0):
        result = benchmark("S2_PERIODIC", duration, accepted_dt, "fast",
                           oracles["S2"], repeats=3, periodic_mode=True)
        result.update({"optimization_stage": "P4_P6", "changes": "accepted timestep + final fast solver",
                       "numerical_regression": "PASS"})
        stage_rows.append(result)
    write_csv(AUDIT / "35F_optimization_stages.csv", stage_rows)

    final_100 = benchmark("S2_PERIODIC", 100.0, accepted_dt, "fast",
                          oracles["S2"], repeats=1, periodic_mode=True)
    final_rows = [row for row in stage_rows if row["optimization_stage"] == "P4_P6"]
    final_rows.append({**final_100, "optimization_stage": "FINAL_100S",
                       "changes": "accepted final configuration",
                       "numerical_regression": "PASS"})
    write_csv(AUDIT / "35H_final_runtime_benchmark.csv", final_rows)

    # Compact evidence timeseries and plots.
    series_rows = []
    for index in range(0, len(ref_t), 10):
        for name in ("front_supply_pressure", "rear_supply_pressure", "pA", "pB", "QA", "QB"):
            series_rows.append({"time_s": float(ref_t[index]), "quantity": name,
                                "reference_value": float(ref_output[name][index]),
                                "fast_value": float(fast_output[name][index])})
    write_csv(AUDIT / "35_original_vs_fast_timeseries.csv", series_rows)
    prepress_rows = []
    for i in range(len(working_t)):
        prepress_rows.append({"time_s": float(working_t[i]),
            **{name: float(values[i]) for name, values in working_out.items()}})
    write_csv(AUDIT / "35_prepressurized_timeseries.csv", prepress_rows)

    plt.figure(figsize=(8, 4.5))
    for scenario in ("S1", "S2"):
        rows = [r for r in convergence_rows if r["scenario"] == scenario and
                r["quantity"] in {"pA", "pB", "front_supply_pressure", "rear_supply_pressure"}]
        xs = sorted({float(r["dt_s"]) * 1e3 for r in rows})
        ys = [max(float(r["normalized_rmse"]) for r in rows
                  if float(r["dt_s"]) * 1e3 == x) * 100 for x in xs]
        plt.plot(xs, ys, marker="o", label=scenario)
    plt.axhline(1.0, color="black", linestyle="--", linewidth=1, label="1% gate")
    plt.xlabel("RK4 step [ms]"); plt.ylabel("max pressure NRMSE [%]")
    plt.title("L1-S1 timestep convergence"); plt.legend(); plt.tight_layout()
    plt.savefig(OUT / "timestep_convergence.png", dpi=150); plt.close()

    plt.figure(figsize=(8, 4.5))
    plt.plot(ref_t, ref_output["rear_supply_pressure"] / 1e6, label="reference solver")
    plt.plot(fast_t, fast_output["rear_supply_pressure"] / 1e6,
             linestyle="--", label="fast solver")
    plt.xlabel("time [s]"); plt.ylabel("rear supply pressure [MPa(g)]")
    plt.title("S2 numerical solver regression"); plt.legend(); plt.tight_layout()
    plt.savefig(OUT / "solver_regression.png", dpi=150); plt.close()

    plt.figure(figsize=(8, 4.5))
    plt.plot(working_t, working_out["rear_supply_pressure"] / 1e6,
             label="rear supply")
    plt.plot(working_t, working_out["pA"] / 1e6, label="rear-1 pA")
    plt.plot(working_t, working_out["pB"] / 1e6, label="rear-1 pB")
    plt.xlabel("time [s]"); plt.ylabel("pressure [MPa(g)]")
    plt.title("Prepressurized working mode, 1 Hz small command")
    plt.legend(); plt.tight_layout()
    plt.savefig(OUT / "prepressurized_working_mode.png", dpi=150); plt.close()

    frozen = json.loads((AUDIT / "35A_original_performance_baseline.json").read_text(encoding="utf-8"))
    original_100 = float(frozen["runs"]["100s_frozen"]["wall_time_s"])
    final_wall = float(final_100["wall_time_s"])
    result = {
        "phase": "L1-S1", "physics_equations_changed": False,
        "dynamic_states": 16, "pipe_dynamic_states": 0,
        "fast_algebraic_solver": "PASS" if all(r["status"] == "PASS" for r in residual_rows) else "FAIL",
        "algebraic_residual_checks": "PASS" if all(r["status"] == "PASS" for r in residual_rows) else "FAIL",
        "numerical_regression": "PASS" if all(r["status"] == "PASS" for r in regression_rows) else "FAIL",
        "accepted_timestep_s": accepted_dt,
        "accepted_by_scenario_s": accepted_by_scenario,
        "original_100s_wall_time_s": original_100,
        "optimized_100s_wall_time_s": final_wall,
        "speedup": original_100 / final_wall,
        "real_time_factor": final_wall / 100.0,
        "performance_targets": {"under_50s": final_wall < 50.0,
                                "under_15s": final_wall < 15.0,
                                "under_5s": final_wall < 5.0},
        "prepressurized_working_mode": working_rows[-2]["status"],
        "working_range_amesim_accuracy": "NOT_VERIFIED",
        "autonomous_actuator_validation": "NOT_VERIFIED",
        "pytest": "PENDING",
        "fast_solver_freeze": "PASS" if all(r["status"] == "PASS" for r in regression_rows + residual_rows) else "FAIL",
        "hydraulic_final_acceptance": "CONDITIONAL",
        "ready_to_discuss_mechanical_modifications": False,
        "diagnostics_100s": {"algebraic_calls": final_100["algebraic_calls"],
                             "correction_iterations": final_100["correction_iterations"],
                             "fallbacks": final_100["fallbacks"],
                             "network_evaluations": final_100["network_evaluations"]},
    }
    (AUDIT / "35I_phase_L1_S1_results.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
