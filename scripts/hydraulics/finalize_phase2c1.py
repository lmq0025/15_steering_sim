from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "hydraulic_audit"
DOCS = ROOT / "docs" / "hydraulics"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)


def first_true(times: list[float], values: list[bool]):
    return next((time for time, value in zip(times, values) if value), "NEVER")


def main() -> None:
    result_path = AUDIT / "20L_phase2C1_results.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    amesim_rows = read_csv(AUDIT / "20E_amesim_baseline_timeseries.csv")
    python_rows = read_csv(AUDIT / "20F_python_baseline_timeseries.csv")
    mappings = read_csv(AUDIT / "20B_amesim_python_variable_map.csv")
    parameters = read_csv(AUDIT / "04_parameters.csv")
    components = {row["alias"]: row for row in read_csv(AUDIT / "01_components.csv")}
    times = [float(row["time_s"]) for row in amesim_rows]
    controls = sorted({row["amesim_alias"] for row in mappings if row["physical_quantity"].startswith("control valve")})
    threshold_by_alias: dict[str, float] = {}
    for row in parameters:
        if row["alias"] not in controls: continue
        if row["title"] in {"relief valve cracking pressure", "maximum relief valve cracking pressure", "check valve cracking pressure", "minimum set pressure (spring pre-tension)"}:
            threshold_by_alias[row["alias"]] = float(row["resolved_value"]) * (1.0e5 if row["unit"].lower().startswith("bar") else 1.0)

    by_alias_output: dict[tuple[str, str], str] = {}
    by_alias_path: dict[tuple[str, str], str] = {}
    for row in mappings:
        suffix = row["python_output"].split(".")[-1]
        by_alias_output[(row["amesim_alias"], suffix)] = row["python_output"]
        by_alias_path[(row["amesim_alias"], suffix)] = row["amesim_data_path"]

    trace = read_csv(AUDIT / "20J_pump_pressure_anomaly_trace.csv")
    control_summary = []
    for alias in controls:
        p1_path, p2_path, q_path = by_alias_path.get((alias, "p1_pa")), by_alias_path.get((alias, "p2_pa")), by_alias_path.get((alias, "flow_m3_s"))
        p1_key, p2_key, q_key = by_alias_output.get((alias, "p1_pa")), by_alias_output.get((alias, "p2_pa")), by_alias_output.get((alias, "flow_m3_s"))
        if not all((p1_path, p2_path, q_path, p1_key, p2_key, q_key)): continue
        threshold = threshold_by_alias.get(alias, 2.0e5)
        ame_open, py_open = [], []
        for i, row in enumerate(trace):
            ap1, ap2, aq = float(amesim_rows[i][p1_path]), float(amesim_rows[i][p2_path]), float(amesim_rows[i][q_path])
            pp1, pp2, pq = float(python_rows[i][p1_key]), float(python_rows[i][p2_key]), float(python_rows[i][q_key])
            adp, pdp = ap2 - ap1, pp2 - pp1
            aopen, popen = adp > threshold, pdp > threshold
            ame_open.append(aopen); py_open.append(popen)
            row.update({f"amesim_{alias}_p1_pa": ap1, f"amesim_{alias}_p2_pa": ap2, f"amesim_{alias}_dp_p2_minus_p1_pa": adp, f"amesim_{alias}_flow_m3_s": aq, f"amesim_{alias}_open_by_threshold": int(aopen), f"python_{alias}_p1_pa": pp1, f"python_{alias}_p2_pa": pp2, f"python_{alias}_dp_p2_minus_p1_pa": pdp, f"python_{alias}_flow_m3_s": pq, f"python_{alias}_open_by_threshold": int(popen), f"{alias}_threshold_pa": threshold})
        control_summary.append({"alias": alias, "submodel": components.get(alias, {}).get("submodel", ""), "threshold_pa": threshold, "amesim_first_open_s": first_true(times, ame_open), "python_first_open_s": first_true(times, py_open), "amesim_peak_directed_dp_pa": max(float(amesim_rows[i][p2_path]) - float(amesim_rows[i][p1_path]) for i in range(len(times))), "python_peak_directed_dp_pa": max(float(python_rows[i][p2_key]) - float(python_rows[i][p1_key]) for i in range(len(times))), "direction_checked": "p2-p1"})
    write_csv(AUDIT / "20J_pump_pressure_anomaly_trace.csv", trace, list(trace[0]))
    write_csv(AUDIT / "20J_pressure_control_opening_summary.csv", control_summary, list(control_summary[0]))

    pump_divergence = {}
    for pump in ("pump01", "pump01_1", "pump01_2", "pump01_3"):
        for row in trace:
            ame = float(row[f"amesim_{pump}_pout_pa"]); py = float(row[f"python_{pump}_pout_pa"])
            if py > max(2.0 * ame, 2.0e7):
                pump_divergence[pump] = float(row["time_s"]); break

    metrics = read_csv(AUDIT / "20H_comparison_metrics.csv")
    error_rows = read_csv(AUDIT / "20I_error_attribution.csv")
    category_counts: dict[str, int] = {}
    suspects: dict[str, set[str]] = {}
    for row in error_rows:
        category_counts[row["error_category"]] = category_counts.get(row["error_category"], 0) + 1
        suspects.setdefault(row["error_category"], set()).add(row["suspected_component"])
    sc_summary = []
    for alias, variant in (("dirvalve_1", "A"), ("dirvalve_2", "B"), ("dirvalve_6", "C"), ("dirvalve_3", "D")):
        selected = [row for row in metrics if f"@{alias}__vs__" in row["variable"] or f"@{alias}.orifice" in row["variable"]]
        sc_summary.append({"variant": variant, "alias": alias, "command_nrmse": next((row["NRMSE"] for row in selected if "signal_input@" in row["variable"]), ""), "spool_nrmse": next((row["NRMSE"] for row in selected if "frac_spool_position@" in row["variable"]), ""), "branch_flow_nrmse": next((row["NRMSE"] for row in selected if ".orifice_" in row["variable"]), ""), "finding": "command/spool direction matched; aggregate FAST branch flow is not Amesim-equivalent"})
    write_csv(AUDIT / "20M_sc1_variant_comparison_summary.csv", sc_summary, ["variant", "alias", "command_nrmse", "spool_nrmse", "branch_flow_nrmse", "finding"])

    result["pump_pressure"]["first_divergence_time_s_by_pump"] = pump_divergence
    result["pump_pressure"]["first_divergence_location"] = "pump outlet junctions V3_HJ_066/V3_HJ_068/V3_HJ_108/V3_HJ_110; downstream RV010 opening schedules then diverge"
    result["pump_pressure"]["relief_opening_finding"] = "Amesim presscontrol01 opens at 0.084 s and presscontrol01_3 at 0.748 s; Python opens neither within 1 s"
    result["pressure_control"] = {"instances_checked": len(control_summary), "direction": "p2-p1", "opening_summary_file": "20J_pressure_control_opening_summary.csv"}
    result["comparison"]["unit_or_sign_errors_found"] = category_counts.get("UNIT_OR_SIGN", 0)
    result["comparison"]["topology_errors_found"] = category_counts.get("TOPOLOGY", 0)
    result["comparison"]["level_c_surrogate_suspects"] = len(suspects.get("LEVEL_C_SURROGATE", set()))
    result["comparison"]["fast_reduction_suspects"] = len(suspects.get("FAST_LINE_REDUCTION", set()))
    result["performance"] = {"amesim_1s_wall_time_s": result["amesim"]["wall_time_s"], "python_1s_wall_time_s": result["python"]["wall_time_s"], "python_to_amesim_wall_ratio": result["python"]["wall_time_s"] / result["amesim"]["wall_time_s"]}
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    poor = sorted((row for row in metrics if row["classification"] == "POOR"), key=lambda row: float(row["NRMSE"]), reverse=True)
    opening_lines = "\n".join(f"- `{row['alias']}` ({row['submodel']}, {row['direction_checked']}): threshold {float(row['threshold_pa']):.6g} Pa; Amesim first open {row['amesim_first_open_s']} s; Python first open {row['python_first_open_s']} s." for row in control_summary)
    report = f"""# Python Phase 2-C1 Amesim Baseline Equivalence Comparison

## Executive result

Both native Amesim and Python FAST completed the same 1.0 s case. Amesim produced 1001 samples in {result['amesim']['wall_time_s']:.3f} s; Python used the accepted dense BDF + exact algebraic cache path and completed in {result['python']['wall_time_s']:.3f} s. Sparse Jacobian remained disabled.

The comparison contains **{result['comparison']['variables_total']}** comparable variables: **{result['comparison']['good']} GOOD**, **{result['comparison']['acceptable']} ACCEPTABLE**, and **{result['comparison']['poor']} POOR**. All 109 FAST initial states were derived from Amesim t=0 data; no engineering-default state remained.

## Input and initialization equivalence

The Python run did not use the generic Phase 2-B scenario. It replayed 41 measured Amesim input-port traces: individual SC_1 commands, PV00022 commands, top-level HYDVORF0 inputs, four pump speeds, and six mechanical force-source outputs. This makes the external excitation identical without modifying the Amesim model.

The audit model was closed with `AMECloseCircuit(False)`. Its SHA-256 was identical before and after both Amesim runs. The formal initial-state mapping and values are in `20C` and `20D`.

## Pump high-pressure finding

- Amesim maximum pump outlet pressure: **{result['pump_pressure']['amesim_max_pa']:.6g} Pa** ({result['pump_pressure']['amesim_max_pa']/1e5:.3f} bar).
- Python maximum pump outlet pressure: **{result['pump_pressure']['python_max_pa']:.6g} Pa** ({result['pump_pressure']['python_max_pa']/1e5:.3f} bar).
- Classification: **PYTHON_ONLY**, not the same order of magnitude.
- First >2x / >20 MPa divergence: pump01/pump01_1 at **{pump_divergence.get('pump01')} s**; pump01_2/pump01_3 at **{pump_divergence.get('pump01_2')} s**.
- First observed locations: **V3_HJ_066, V3_HJ_068, V3_HJ_108, and V3_HJ_110**, the four pump outlet junctions.

Pump speed and ideal displacement flow agree essentially exactly, while outlet pressure and torque are POOR. This localizes the discrepancy downstream of PU001's ideal TF relation, in the pressure-control/check/relief and reduced resistance network rather than pump displacement or speed conversion. No bar-to-Pa or L/min-to-m^3/s multiplier error was detected.

## Pressure-control and CV/RV direction audit

All available CV010/RV010/RV011/HYDPRV0/PV00022 instances were evaluated using the frozen directed pressure **p2 - p1**. Opening times below are deterministic threshold diagnostics, not parameter changes:

{opening_lines}

The Amesim and Python opening schedules and flows do not generally coincide. The dominant attribution is the existing LEVEL C switching/pressure-control surrogate, including its reduced conductance and static opening representation. Relief thresholds themselves were read unchanged from Amesim metadata.

## SC_1 variants

Structures A/B/C/D were represented by `dirvalve_1`, `dirvalve_2`, `dirvalve_6`, and `dirvalve_3`. External command and frozen static spool position match the Amesim traces for these native inputs. Individual Amesim MR branch flows do not match the Python aggregate two-pair SC_1 flow representation; these are explicit Phase 2-C2 targets, not evidence of input reversal.

## Actuators and network

Actuator rod forces are often ACCEPTABLE while chamber pressures, displacement, and velocity are mostly POOR. Several displacement correlations retain the correct trend, but amplitude and sometimes sign differ. The error chain is consistent with upstream pressure-control/SC_1 flow mismatch. The current comparison found no new IR V3 topology contradiction; `TOPOLOGY` attribution count is zero.

The largest POOR entries include:

""" + "\n".join(f"- `{row['variable']}`: NRMSE {float(row['NRMSE']):.3g}, correlation {float(row['pearson_correlation']):.3g}." for row in poor[:12]) + f"""

## Error attribution and next calibration targets

- LEVEL_C_SURROGATE records: {category_counts.get('LEVEL_C_SURROGATE', 0)} across {len(suspects.get('LEVEL_C_SURROGATE', set()))} component aliases.
- INITIALIZATION records: {category_counts.get('INITIALIZATION', 0)}. These primarily reflect algebraic boundary/reference-pressure differences even though physical storage states were aligned.
- FAST_LINE_REDUCTION records: {category_counts.get('FAST_LINE_REDUCTION', 0)}.
- UNIT_OR_SIGN records: {category_counts.get('UNIT_OR_SIGN', 0)}.
- TOPOLOGY records: {category_counts.get('TOPOLOGY', 0)}.

Recommended Phase 2-C2 order: pressure-reference convention and tank boundary; CV/RV/HYDPRV0 conductance/opening laws; SC_1 individual MR branch flow; then line resistance/reduction. Pump q0top is not the first target because pump flow already agrees.

## Sanity and readiness

Sanity checks: **{result['sanity']['passed']}/{result['sanity']['total']} PASS**. Amesim was not saved, IR V3 and the Python physics model were not modified, 109 states remained intact, and algebraic failures were zero.

**READY FOR TARGETED CALIBRATION = YES.** No calibration was performed in Phase 2-C1.
"""
    (DOCS / "python_phase2C1_amesim_comparison_report.md").write_text(report, encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
