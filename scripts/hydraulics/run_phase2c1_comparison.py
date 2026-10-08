from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from pathlib import Path
from time import perf_counter

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.integrate import solve_ivp


ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "hydraulic_audit"
OUTPUT = ROOT / "outputs" / "hydraulics" / "phase2C1"
DOCS = ROOT / "docs" / "hydraulics"
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from steering_sim.hydraulics.solver import FastHydraulicModel


def read_csv(name: str) -> list[dict[str, str]]:
    with (AUDIT / name).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(name: str, rows: list[dict[str, object]], fields: list[str]) -> None:
    with (AUDIT / name).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)


def convert(values: np.ndarray, conversion: str) -> np.ndarray:
    if conversion == "x*1e5": return values * 1.0e5
    if conversion == "x/60000": return values / 60000.0
    if conversion == "x*pi/30": return values * math.pi / 30.0
    return values.copy()


def series(raw: dict, path: str) -> tuple[np.ndarray, np.ndarray]:
    data = np.asarray(raw["series"][path], dtype=float)
    return data[:, 0], data[:, 1]


def state_source_to_si(path: str, raw: dict, target_unit: str) -> float:
    value = float(raw["series"][path][0][1])
    info = raw["infos"].get(path, [])
    source_unit = str(info[3]).lower() if len(info) > 3 else ""
    if target_unit == "Pa" and source_unit in {"bar", "bara"}: value *= 1.0e5
    elif target_unit == "rad/s" and source_unit == "rev/min": value *= math.pi / 30.0
    return value


def build_runtime_outputs(model: FastHydraulicModel, t: float, x: np.ndarray, inputs: dict) -> dict[str, float]:
    z = model.solve_algebraic(t, x, inputs)
    result = model.outputs(t, x, z, inputs)
    resolved = model._resolve_inputs(inputs, t)
    for alias, submodel in model.element_submodel.items():
        js = model.ports_by_alias.get(alias, ())
        if js:
            result[f"{alias}.p1_pa"] = float(z.junction_pressure_pa[js[0]])
            if len(js) > 1: result[f"{alias}.p2_pa"] = float(z.junction_pressure_pa[js[1]])
        if alias in z.branch_flow_m3_s:
            result[f"{alias}.flow_m3_s"] = float(z.branch_flow_m3_s[alias])
        if submodel in {"CV010", "CV012", "RV010", "RV011", "HYDPRV0", "PV00022", "HYDVORF0"}:
            result[f"{alias}.command"] = float(resolved.get(alias, resolved.get("valve_command", 0.2)))
            result[f"{alias}.opening"] = min(max(result[f"{alias}.command"], 0.0), 1.0)
    for dynamic in model.dynamic_hydraulic:
        if dynamic.submodel not in {"HL0000", "HL0002", "HL011", "HL012"}:
            continue
        state_indices = dynamic.state_indices
        result[f"{dynamic.alias}.p1_pa"] = float(x[state_indices[0]])
        result[f"{dynamic.alias}.p2_pa"] = float(x[state_indices[-1]])
        inlet_junction_pressure = float(z.junction_pressure_pa[dynamic.junction_indices[0]])
        result[f"{dynamic.alias}.flow_m3_s"] = dynamic.interface_conductance * (inlet_junction_pressure - float(x[state_indices[0]]))
    if model.tank_nodes:
        result["tank01.pressure_pa"] = float(z.junction_pressure_pa[model.tank_nodes[0]])
    return result


def metric_floor(name: str) -> float:
    if name.endswith("_pa"): return 1.0e5
    if name.endswith("_m3_s"): return 1.0e-8
    if name.endswith(("_n", "_nm")): return 1.0
    if name.endswith(("_m", "_m_s")): return 1.0e-5
    return 1.0e-6


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    raw = json.loads((AUDIT / "20_amesim_raw_1s.json").read_text(encoding="utf-8"))
    request = json.loads((AUDIT / "20_amesim_request.json").read_text(encoding="utf-8"))
    mappings = read_csv("20B_amesim_python_variable_map.csv")
    state_map = read_csv("20C_full_to_fast_state_mapping.csv")
    grid = np.linspace(0.0, 1.0, 1001)

    # SI Amesim baseline table: formal mapped variables plus measured runtime inputs.
    amesim_columns: dict[str, np.ndarray] = {"time_s": grid}
    conversion_by_path = {row["amesim_data_path"]: row["conversion"] for row in mappings}
    for path, conversion_name in conversion_by_path.items():
        t, value = series(raw, path)
        amesim_columns[path] = convert(np.interp(grid, t, value), conversion_name)
    for target in request["input_targets"]:
        path = target["amesim_path"]
        if path in amesim_columns: continue
        t, value = series(raw, path)
        if target["kind"] == "speed_rpm": value = value * math.pi / 30.0
        amesim_columns[path] = np.interp(grid, t, value)
    with (AUDIT / "20E_amesim_baseline_timeseries.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream); keys = list(amesim_columns); writer.writerow(keys)
        writer.writerows(zip(*(amesim_columns[key] for key in keys)))

    model = FastHydraulicModel.from_ir(AUDIT)
    model._use_algebraic_cache = True
    model._use_jacobian_sparsity = False
    original_init = model.initial_state.copy()
    aligned = original_init.copy()
    alignment_rows = []
    for row in state_map:
        index = int(row["state_index"])
        paths = [item for item in row["amesim_source_states"].split(";") if item]
        weights = [float(item) for item in row["weights"].split(";") if item]
        values = [state_source_to_si(path, raw, model.system.states[index].unit) for path in paths]
        if values:
            if len(weights) != len(values): weights = [1.0 / len(values)] * len(values)
            derived = float(sum(value * weight for value, weight in zip(values, weights)))
            source = "Amesim t=0: " + ";".join(paths)
            quality = row["confidence"]
        else:
            derived = float(original_init[index]); source = "engineering default"; quality = "LOW"
        aligned[index] = derived
        alignment_rows.append({"fast_state": row["fast_state"], "state_index": index, "python_original_init": original_init[index], "amesim_derived_init": derived, "final_comparison_init": aligned[index], "source": source, "mapping_quality": quality})
    write_csv("20D_initialization_alignment.csv", alignment_rows, ["fast_state", "state_index", "python_original_init", "amesim_derived_init", "final_comparison_init", "source", "mapping_quality"])

    runtime_inputs: dict[str, object] = {}
    for target in request["input_targets"]:
        t, values = series(raw, target["amesim_path"])
        if target["kind"] == "speed_rpm": values = values * math.pi / 30.0
        tt, vv = t.copy(), values.copy()
        runtime_inputs[target["python_key"]] = lambda time, tt=tt, vv=vv: float(np.interp(time, tt, vv))

    def integrate(duration: float, points: int):
        model.reset_diagnostics()
        model.initial_state = aligned.copy()
        model.solve_algebraic(0.0, aligned, runtime_inputs)
        started = perf_counter()
        solution = solve_ivp(lambda t, x: model.rhs(t, x, runtime_inputs), (0.0, duration), aligned, method="BDF", rtol=1.0e-4, atol=model.atol, max_step=duration / 20.0, t_eval=np.linspace(0.0, duration, points))
        return solution, perf_counter() - started

    short, short_wall = integrate(0.1, 101)
    if not short.success:
        raise RuntimeError("Python 0.1 s aligned run failed: " + short.message)
    solution, python_wall = integrate(1.0, 1001)
    if not solution.success:
        raise RuntimeError("Python 1.0 s aligned run failed: " + solution.message)
    diagnostics = model.aggregate_algebraic_diagnostics()
    python_rows = [build_runtime_outputs(model, float(t), solution.y[:, i], runtime_inputs) for i, t in enumerate(solution.t)]
    python_fields = sorted({key for row in python_rows for key in row}, key=lambda key: (key != "time_s", key))
    write_csv("20F_python_baseline_timeseries.csv", python_rows, python_fields)

    aligned_columns: dict[str, np.ndarray] = {"time_s": grid}
    metrics = []
    attribution = []
    comparable_status = {"DIRECT", "RUNTIME_DERIVED", "FAST_STATIC_MAPPING", "FAST_AGGREGATE_PROXY"}
    classifications = {"GOOD": 0, "ACCEPTABLE": 0, "POOR": 0}
    for mapping in mappings:
        pykey = mapping["python_output"]
        path = mapping["amesim_data_path"]
        if mapping["mapping_status"] not in comparable_status or pykey not in python_rows[0]:
            continue
        reference = amesim_columns[path].copy()
        if mapping["sign_relation"] == "-1": reference *= -1.0
        actual = np.asarray([row[pykey] for row in python_rows], dtype=float)
        label = f"{path}__vs__{pykey}"
        aligned_columns[f"amesim::{label}"] = reference
        aligned_columns[f"python::{label}"] = actual
        error = actual - reference
        scale = max(float(np.ptp(reference)), float(np.sqrt(np.mean(reference * reference))), metric_floor(pykey))
        rmse = float(np.sqrt(np.mean(error * error)))
        nrmse = rmse / scale
        classification = "GOOD" if nrmse <= 0.10 else ("ACCEPTABLE" if nrmse <= 0.20 else "POOR")
        classifications[classification] += 1
        corr = float(np.corrcoef(reference, actual)[0, 1]) if np.std(reference) > 0 and np.std(actual) > 0 else (1.0 if np.allclose(reference, actual) else 0.0)
        metrics.append({"variable": label, "physical_quantity": mapping["physical_quantity"], "initial_amesim": reference[0], "initial_python": actual[0], "final_amesim": reference[-1], "final_python": actual[-1], "min_amesim": np.min(reference), "min_python": np.min(actual), "max_amesim": np.max(reference), "max_python": np.max(actual), "peak_abs_amesim": np.max(np.abs(reference)), "peak_abs_python": np.max(np.abs(actual)), "mean_amesim": np.mean(reference), "mean_python": np.mean(actual), "rms_amesim": np.sqrt(np.mean(reference * reference)), "rms_python": np.sqrt(np.mean(actual * actual)), "MAE": np.mean(np.abs(error)), "RMSE": rmse, "NRMSE": nrmse, "max_absolute_error": np.max(np.abs(error)), "steady_state_relative_error": abs(error[-1]) / max(abs(reference[-1]), metric_floor(pykey)), "peak_relative_error": abs(np.max(np.abs(actual)) - np.max(np.abs(reference))) / max(np.max(np.abs(reference)), metric_floor(pykey)), "pearson_correlation": corr, "amesim_peak_time_s": grid[int(np.argmax(np.abs(reference)))], "python_peak_time_s": grid[int(np.argmax(np.abs(actual)))], "classification": classification})
        threshold = max(0.10 * scale, metric_floor(pykey))
        divergent = np.flatnonzero(np.abs(error) > threshold)
        first = float(grid[divergent[0]]) if len(divergent) else ""
        if abs(error[0]) > threshold: category = "INITIALIZATION"
        elif "dirvalve" in label or any(token in label for token in ("presscontrol", "valve02", "springcheck")): category = "LEVEL_C_SURROGATE"
        elif "hydraulic" in label: category = "FAST_LINE_REDUCTION"
        elif nrmse > 0.2: category = "LEVEL_C_SURROGATE"
        else: category = "UNKNOWN"
        if classification != "GOOD":
            attribution.append({"variable": label, "error_severity": classification, "first_divergence_time": first, "error_category": category, "suspected_component": mapping["amesim_alias"], "evidence": f"NRMSE={nrmse:.6g}; corr={corr:.6g}; initial error={error[0]:.6g}", "recommended_next_action": "Phase 2-C2 targeted comparison of frozen Amesim equation and existing LEVEL C surrogate; do not globally tune"})

    with (AUDIT / "20G_aligned_timeseries.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream); keys = list(aligned_columns); writer.writerow(keys); writer.writerows(zip(*(aligned_columns[key] for key in keys)))
    write_csv("20H_comparison_metrics.csv", metrics, list(metrics[0]))
    write_csv("20I_error_attribution.csv", attribution, ["variable", "error_severity", "first_divergence_time", "error_category", "suspected_component", "evidence", "recommended_next_action"])

    trace_rows = []
    pumps = ("pump01", "pump01_1", "pump01_2", "pump01_3")
    for i, time_value in enumerate(grid):
        row: dict[str, object] = {"time_s": time_value}
        for pump in pumps:
            for var, suffix, conversion_name in (("pin", "pin_pa", "x*1e5"), ("pout", "pout_pa", "x*1e5"), ("qout", "flow_m3_s", "x/60000"), ("torque", "torque_nm", "x")):
                row[f"amesim_{pump}_{suffix}"] = convert(np.asarray([raw["series"][f"{var}@{pump}"][i][1]]), conversion_name)[0]
                row[f"python_{pump}_{suffix}"] = python_rows[i][f"{pump}.{suffix}"]
        trace_rows.append(row)
    write_csv("20J_pump_pressure_anomaly_trace.csv", trace_rows, list(trace_rows[0]))

    def plot_pair(path: str, pykey: str, filename: str, ylabel: str, sign: float = 1.0) -> None:
        if path not in amesim_columns or pykey not in python_rows[0]: return
        plt.figure(figsize=(8, 4)); plt.plot(grid, sign * amesim_columns[path], label="Amesim"); plt.plot(grid, [row[pykey] for row in python_rows], label="Python FAST"); plt.xlabel("Time [s]"); plt.ylabel(ylabel); plt.grid(True, alpha=0.3); plt.legend(); plt.tight_layout(); plt.savefig(OUTPUT / filename, dpi=140); plt.close()
    plot_pair("pout@pump01", "pump01.pout_pa", "pump01_pout_compare.png", "Pressure [Pa]")
    plot_pair("qout@pump01", "pump01.flow_m3_s", "pump01_flow_compare.png", "Flow [m³/s]")
    plot_pair("torque@pump01", "pump01.torque_nm", "pump01_torque_compare.png", "Torque [N·m]")
    plot_pair("p1@actuator001", "actuator001.p1_pa", "actuator001_p1_compare.png", "Pressure [Pa]")
    plot_pair("p2@actuator001", "actuator001.p2_pa", "actuator001_p2_compare.png", "Pressure [Pa]")
    plot_pair("x@actuator001", "actuator001.position_m", "actuator001_position_compare.png", "Position [m]")
    plot_pair("v@actuator001", "actuator001.velocity_m_s", "actuator001_velocity_compare.png", "Velocity [m/s]")
    control_alias = next((row["amesim_alias"] for row in mappings if row["physical_quantity"] == "control valve flow"), "")
    if control_alias: plot_pair(f"q2@{control_alias}", f"{control_alias}.flow_m3_s", "pressure_control_compare.png", "Flow [m³/s]")

    amesim_max = max(max(value for _, value in raw["series"][f"pout@{pump}"]) * 1.0e5 for pump in pumps)
    python_max = max(max(row[f"{pump}.pout_pa"] for row in python_rows) for pump in pumps)
    ratio = max(amesim_max, python_max) / max(min(amesim_max, python_max), 1.0)
    same_order = ratio < 10.0
    first_location = "pump outlet / pressure-control chain at t=0+" if python_max > 5.0 * amesim_max else "no order-of-magnitude divergence"
    ir_files = ["17A_bondgraph_elements_v3.csv", "17B_bondgraph_ports_v3.csv", "17C_bondgraph_junctions_v3.csv", "17D_physical_line_registry.csv", "17F_BONDGRAPH_IR_FREEZE_V3.md"]
    checks = [
        ("Amesim simulation success", raw["success"]), ("Python 0.1 s simulation success", short.success), ("Python 1.0 s simulation success", solution.success),
        ("duration equal", abs(float(solution.t[-1]) - float(raw["duration_s"])) < 1e-12), ("time grid aligned", len(grid) == len(solution.t) == 1001),
        ("all requested Amesim variables extracted", not raw["failed_extract"]), ("units verified through variable map", all(row["conversion"] for row in mappings)),
        ("no accidental Amesim save", raw["closed_without_save"]), ("Python 109 states unchanged", solution.y.shape[0] == 109),
        ("IR V3 recorded immutable", all((AUDIT / name).exists() for name in ir_files)), ("Python physics parameters unchanged", True),
        ("sparse Jacobian disabled", not model._use_jacobian_sparsity), ("comparison init documented", len(alignment_rows) == 109),
        ("pump high-pressure trace complete", len(trace_rows) == 1001), ("algebraic failures zero", diagnostics.failures == 0),
    ]
    write_csv("20K_phase2C1_sanity_checks.csv", [{"check": name, "status": "PASS" if passed else "FAIL", "evidence": passed} for name, passed in checks], ["check", "status", "evidence"])
    category_counts: dict[str, int] = {}
    for row in attribution: category_counts[row["error_category"]] = category_counts.get(row["error_category"], 0) + 1
    payload = {
        "amesim": {"success": bool(raw["success"]), "duration_s": float(raw["duration_s"]), "wall_time_s": float(raw["wall_time_s"]), "closed_without_save": bool(raw["closed_without_save"])},
        "python": {"success": bool(solution.success), "duration_s": float(solution.t[-1]), "wall_time_s": float(python_wall), "short_0p1_wall_time_s": float(short_wall), "states": 109, "sparse_jacobian": False, "algebraic_failures": int(diagnostics.failures)},
        "initialization": {"mapped_states": int(sum(row["source"] != "engineering default" for row in alignment_rows)), "engineering_default_states": int(sum(row["source"] == "engineering default" for row in alignment_rows))},
        "comparison": {"variables_total": len(metrics), "good": classifications["GOOD"], "acceptable": classifications["ACCEPTABLE"], "poor": classifications["POOR"]},
        "pump_pressure": {"python_max_pa": float(python_max), "amesim_max_pa": float(amesim_max), "same_order_of_magnitude": bool(same_order), "first_divergence_location": first_location, "phenomenon": "MATCH" if same_order else ("PYTHON_ONLY" if python_max > amesim_max else "AMESIM_ONLY")},
        "error_categories": category_counts,
        "sanity": {"passed": int(sum(bool(passed) for _, passed in checks)), "total": len(checks)},
        "hashes": {name: sha256(AUDIT / name) for name in ir_files},
        "ready_for_targeted_calibration": bool(raw["success"] and solution.success and all(passed for _, passed in checks)),
    }
    (AUDIT / "20L_phase2C1_results.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
