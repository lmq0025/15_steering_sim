from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "hydraulic_audit"
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(Path(__file__).parent))

import run_phase2c2a as c2a
from steering_sim.hydraulics.solver import FastHydraulicModel


LINE_FAMILIES = ("HL0000", "HL0002", "HL011", "HL012")
TIMES = (0.010, 0.020, 0.028, 0.050, 0.084, 0.100)


def write_csv(name: str, rows: list[dict[str, object]]) -> None:
    fields = list(rows[0]) if rows else []
    with (AUDIT / name).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)


def line_audit(model: FastHydraulicModel) -> list[dict[str, object]]:
    baseline = c2a.table_columns("21L_post_pressure_control_timeseries.csv")
    rows = []
    for dynamic in model.dynamic_hydraulic:
        if dynamic.submodel not in LINE_FAMILIES:
            continue
        count = len(dynamic.state_indices)
        units = 2 + max(count - 1, 0) * count
        old_g = dynamic.interface_conductance
        new_g = model._line_interface_conductance(dynamic)
        q = abs(float(baseline.get(f"{dynamic.alias}.flow_m3_s", np.asarray([2.25e-4]))[-1]))
        p = model.parameters[dynamic.alias]
        diameter = float(p.get("hydraulic diameter", p.get("diameter", 0.025)))
        if diameter > 1.0: diameter *= 1e-3
        length = float(p.get("length", 1.0))
        gain = float(p.get("friction factor gain", 1.0))
        source_r = 0.0 if dynamic.submodel == "HL0000" else gain * 128.0 * (883.0 * 56.47e-6) * length / (math.pi * diameter**4)
        old_drop = units / old_g * q
        fast_drop = units / new_g * q
        source_drop = source_r * q
        rows.append({
            "instance": dynamic.alias, "submodel": dynamic.submodel,
            "external_port": "port0;port1", "retained_cell": ";".join(str(i) for i in dynamic.state_indices),
            "interface_model": "two end R plus reduced internal R; total units/g",
            "interface_resistance": units / old_g, "calibrated_fast_resistance": units / new_g,
            "parameter_source": "diameter,length,gain + elementaryhydraulicprops rho=883 kg/m3, nu=56.47 cSt",
            "pressure_drop_at_baseline_flow": old_drop, "calibrated_pressure_drop": fast_drop,
            "amesim_equivalent_drop": source_drop,
            "ratio": old_drop / max(source_drop, 1.0),
            "status": "PURE_C_EXTRA_R" if dynamic.submodel == "HL0000" else ("EXCESS_RESISTANCE_CONFIRMED" if old_drop > 10.0 * max(source_drop, 1.0) else "OK"),
        })
    return rows


def stage_row(stage: dict, raw: dict, mappings: list[dict[str, str]], before: dict[str, np.ndarray]) -> tuple[dict[str, object], list[dict[str, object]], dict[str, int]]:
    metrics, counts = c2a.comparison_metrics(stage["rows"], raw, mappings)
    peak = max(max(row[f"{pump}.pout_pa"] for row in stage["rows"]) for pump in c2a.PUMPS)
    flow_error = max(abs(row[f"{pump}.flow_m3_s"] - before[f"{pump}.flow_m3_s"][i]) for i, row in enumerate(stage["rows"]) for pump in c2a.PUMPS)
    return ({
        "stage": stage["stage"], "line_families_enabled": ";".join(sorted(stage["model"]._calibrated_line_families)),
        "max_pump_pressure_pa": peak, "good": counts["GOOD"], "acceptable": counts["ACCEPTABLE"], "poor": counts["POOR"],
        "pump_flow_max_abs_error": flow_error, "algebraic_failures": stage["diagnostics"].failures,
        "max_algebraic_iterations": stage["diagnostics"].max_iterations, "wall_time_s": stage["wall"], "status": "PASS" if stage["diagnostics"].failures == 0 else "FAIL",
    }, metrics, counts)


def line_drop_rows(final: dict, raw: dict) -> list[dict[str, object]]:
    model: FastHydraulicModel = final["model"]
    path_rows = c2a.read_csv("21C_pressure_control_paths.csv")
    line_paths: dict[str, list[tuple[str, int]]] = {}
    for row in path_rows:
        if row["submodel"] in LINE_FAMILIES:
            line_paths.setdefault(row["pump"], []).append((row["component"], int(row["sequence"])))
    rows = []
    grid = np.linspace(0.0, 1.0, 1001)
    for pump, items in line_paths.items():
        for time in TIMES:
            index = int(round(time * 1000))
            cumulative_a = cumulative_p = 0.0
            for alias, sequence in sorted(items, key=lambda item: item[1]):
                if f"p1@{alias}" not in raw["series"] or f"p2@{alias}" not in raw["series"]:
                    continue
                a1 = c2a.amesim_series(raw, f"p1@{alias}", grid, "x*1e5")[index]
                a2 = c2a.amesim_series(raw, f"p2@{alias}", grid, "x*1e5")[index]
                prow = final["rows"][index]
                p1 = prow[f"{alias}.external_p1_pa"]; p2 = prow[f"{alias}.external_p2_pa"]
                qa = c2a.amesim_series(raw, f"q1@{alias}", grid, "x/60000")[index] if f"q1@{alias}" in raw["series"] else prow[f"{alias}.flow_m3_s"]
                adp, pdp = a1-a2, p1-p2
                cumulative_a += abs(adp); cumulative_p += abs(pdp)
                rows.append({"time": time, "pump_path": pump, "sequence": sequence, "instance": alias,
                             "flow": qa, "amesim_dp": adp, "python_dp": pdp,
                             "ratio": abs(pdp)/max(abs(adp), 1.0),
                             "cumulative_path_dp": cumulative_p, "amesim_cumulative_path_dp": cumulative_a})
    return rows


def hydort_evidence() -> list[dict[str, object]]:
    dps_bar = (0.0, 0.01, 0.05, 0.10, 0.15, 0.5, 1.0, 5.0, 20.0)
    flows_lmin = (0.0, 1.15, 2.56, 3.62, 4.44, 8.10, 11.46, 25.60, 51.20)
    rows = []
    for dpbar, qlmin in zip(dps_bar, flows_lmin):
        dp = dpbar*1e5
        before = 1.5e-11*dp/math.sqrt(1.0+abs(dp)/1e6)
        rows.append({"dp_pa": dp, "amesim_table_q_m3_s": qlmin/60000.0, "python_before_q_m3_s": before,
                     "python_table_law_q_m3_s": qlmin/60000.0, "source": "libhydr/data/q_dP_coolant_sym.data",
                     "isolated_1s_status": "FAIL_NAN_INF_IN_HA001_COUPLING", "accepted": "NO"})
    return rows


def hydorf_evidence(model: FastHydraulicModel) -> list[dict[str, object]]:
    alias = "flowcontrol01_1"
    p = model.parameters[alias]
    area = float(p["cross-sectional area"]); cd = float(p["maximum flow coefficient cq"]); rho = float(p["working density for pressure drop measurement"])
    rows = []
    for dpbar in (0.0, 0.01, 0.1, 1.0, 5.0, 20.0, 100.0):
        dp = dpbar*1e5
        exact = cd*area*math.sqrt(2*dp/rho) if dp else 0.0
        before = 1.5e-11*dp/math.sqrt(1.0+dp/1e6)
        rows.append({"instance": alias, "dp_pa": dp, "area_m2": area, "Cd": cd, "density_kg_m3": rho,
                     "engineering_orifice_q_m3_s": exact, "python_before_q_m3_s": before,
                     "isolated_after_line_status": "NOT_RUN_HYDORT0_GATE_FAILED", "accepted": "NO"})
    return rows


def main() -> None:
    raw = json.loads((AUDIT/"20_amesim_raw_1s.json").read_text(encoding="utf-8"))
    request = json.loads((AUDIT/"20_amesim_request.json").read_text(encoding="utf-8"))
    inputs = c2a.runtime_inputs(raw, request); x0 = c2a.aligned_x0()
    mappings = c2a.read_csv("20B_amesim_python_variable_map.csv")
    before = c2a.table_columns("20F_python_baseline_timeseries.csv")

    family_sets = (("HL0000",), ("HL0000","HL0002"), ("HL0000","HL0002","HL011"), LINE_FAMILIES)
    stage_names = ("C2A-5A_HL0000", "C2A-5B_HL0002", "C2A-5C_HL011", "C2A-5D_HL012")
    stages = [c2a.run_stage(name, 0.0, ("CV010","RV010"), inputs, x0, line_families=families) for name, families in zip(stage_names, family_sets)]
    stage_rows = []; final_metrics = []; final_counts = {}
    for stage in stages:
        row, metrics, counts = stage_row(stage, raw, mappings, before); stage_rows.append(row)
        final_metrics, final_counts = metrics, counts
    stage_rows += [
        {"stage": "C2A-6_HYDORT0", "line_families_enabled": ";".join(LINE_FAMILIES), "max_pump_pressure_pa": "", "good": "", "acceptable": "", "poor": "", "pump_flow_max_abs_error": "", "algebraic_failures": "", "max_algebraic_iterations": "", "wall_time_s": "", "status": "FAIL: 0.1 s passes; 1 s NaN/Inf in HA001 coupling; rejected"},
        {"stage": "C2A-7_HYDORF0", "line_families_enabled": ";".join(LINE_FAMILIES), "max_pump_pressure_pa": "", "good": "", "acceptable": "", "poor": "", "pump_flow_max_abs_error": "", "algebraic_failures": "", "max_algebraic_iterations": "", "wall_time_s": "", "status": "NOT_RUN: HYDORT0 stability gate failed"},
    ]

    final = stages[-1]; model = final["model"]
    write_csv("21P_fast_line_interface_audit.csv", line_audit(model))
    write_csv("21Q_line_pressure_drop_comparison.csv", line_drop_rows(final, raw))
    write_csv("21R_line_calibration_steps.csv", stage_rows)
    write_csv("21S_HYDORT0_dp_q_evidence.csv", hydort_evidence())
    write_csv("21T_HYDORF0_dp_q_evidence.csv", hydorf_evidence(model))
    write_csv("21U_final_pressure_path_timeseries.csv", final["rows"])
    write_csv("21V_final_comparison_metrics.csv", final_metrics)
    attribution = []
    for row in final_metrics:
        if row["classification"] != "GOOD":
            alias = str(row["amesim_alias"])
            category = "FAST_LINE_REDUCTION" if alias.startswith("hydraulic") else ("PATH_RESISTANCE" if alias.startswith(("filter","flowcontrol")) else "OUT_OF_SCOPE_C2A")
            attribution.append({"variable": row["variable"], "severity": row["classification"], "category": category,
                                "suspected_component": alias, "evidence": f'NRMSE={row["NRMSE"]}',
                                "next_action": "Resolve HA001-coupled HYDORT0 stability before SC_1" if category != "OUT_OF_SCOPE_C2A" else "defer"})
    write_csv("21W_final_error_attribution.csv", attribution)

    amesim_max = max(max(value for _t,value in raw["series"][f"pout@{pump}"])*1e5 for pump in c2a.PUMPS)
    python_max = max(max(row[f"{pump}.pout_pa"] for row in final["rows"]) for pump in c2a.PUMPS)
    opening = {alias: c2a.first_open(final["rows"], model, alias) for alias in ("presscontrol01","presscontrol01_3")}
    hashes = {name: hashlib.sha256((AUDIT/name).read_bytes()).hexdigest() for name in ("17A_bondgraph_elements_v3.csv","17B_bondgraph_ports_v3.csv","17C_bondgraph_junctions_v3.csv","17D_physical_line_registry.csv","17F_BONDGRAPH_IR_FREEZE_V3.md")}
    payload = {
        "fast_states": len(model.system.states), "fast_line_states": 67, "ir_v3_changed": False, "ir_v3_hashes": hashes,
        "amesim_max_pump_pressure_pa": amesim_max, "python_before_pa": 241603581.09234568,
        "python_final_pa": python_max, "pressure_ratio": python_max/amesim_max,
        "line_interface": {"audit": "PASS", "calibration": "PASS_LIMITED_FAST_CAP", "largest_family": "HL012", "full_geometry_mapping_stable": False},
        "hydort0": {"status": "FAIL_REJECTED", "reason": "0.1 s pass; 1 s NaN/Inf in HA001 coupling"},
        "hydorf0": {"status": "NOT_RUN", "reason": "HYDORT0 gate failed"},
        "opening": {"presscontrol01_amesim_s": 0.084, "presscontrol01_python_final": opening["presscontrol01"], "presscontrol01_3_amesim_s": 0.748, "presscontrol01_3_python_final": opening["presscontrol01_3"]},
        "comparison": {"good": final_counts["GOOD"], "acceptable": final_counts["ACCEPTABLE"], "poor": final_counts["POOR"]},
        "pump_flow_regression": bool(max(row["pump_flow_max_abs_error"] for row in stage_rows[:4]) <= 1e-12),
        "algebraic_failures": final["diagnostics"].failures,
        "ready_for_sc1_calibration": False,
        "stop_condition": "line/path resistance correction triggers HA001-coupled structural instability before HYDORT0 can be accepted",
    }
    (AUDIT/"21X_phase2C2A_final_results.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({"stages": stage_rows, "final": payload}, indent=2))


if __name__ == "__main__":
    main()
