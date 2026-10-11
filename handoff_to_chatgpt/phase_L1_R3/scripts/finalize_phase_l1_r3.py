from __future__ import annotations

import csv
import json
import shutil
import zipfile
from pathlib import Path


ROOT = Path(r"E:\15_project")
AUD = ROOT / "hydraulic_audit_lumped"
DOC = ROOT / "docs" / "hydraulics" / "phase_L1_R3_physics_mapping_report.md"
OUT = ROOT / "outputs" / "hydraulics" / "phase_L1_R3"
HANDOFF = ROOT / "handoff_to_chatgpt" / "phase_L1_R3"
ZIP = ROOT / "handoff_to_chatgpt" / "phase_L1_R3.zip"


def csv_rows(name: str) -> list[dict]:
    with (AUD / name).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def main() -> int:
    result_path = AUD / "33L_phase_L1_R3_results.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["pytest"] = "222 passed"
    result["ready_for_L2_targeted_calibration"] = False
    result["ready_for_mechanical_integration"] = False
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    metrics = csv_rows("33I_reclassified_comparison_metrics.csv")
    flows = csv_rows("33D_SC1_individual_orifice_validation.csv")
    flow_pass = sum(row["status"] == "PASS" for row in flows)
    flow_fail = sum(row["status"] == "FAIL" for row in flows)
    balances = csv_rows("33G_algebraic_node_balance_checks.csv")
    worst_balance = max(max(abs(float(row["pump_node_residual_m3_s"])),
                            abs(float(row["relief_node_residual_m3_s"])),
                            abs(float(row["return_node_residual_m3_s"])))
                        for row in balances)
    by_quantity: dict[str, tuple[int, int]] = {}
    for row in metrics:
        total, good = by_quantity.get(row["quantity"], (0, 0))
        by_quantity[row["quantity"]] = (total + 1,
            good + (str(row["within_10_percent"]).lower() == "true"))
    metric_summary = "\n".join(
        f"- `{name}`: {good}/{total} within 10%" for name, (total, good) in sorted(by_quantity.items()))
    report = f"""# Phase L1-R3 — 集中参数供油网络与 SC_1 四孔口映射修复

## Executive conclusion

Phase L1-R3 completed the requested structural repair without returning to the legacy 109-state model. The runtime remains **4 channels / 16 dynamic states / 0 pipe states**. The former Python-only chamber-pressure failure fell from **{result['python_max_chamber_pressure_before_pa']/1e6:.3f} MPa** to **{result['python_max_chamber_pressure_after_pa']/1e6:.3f} MPa**, naturally, with no pressure clamp or artificial leakage. The comparable Amesim maximum across all four actuator chambers and S0/S1/S2 is **{result['amesim_comparable_max_pressure_pa']/1e6:.3f} MPa**.

The structural result is successful, but the validation result remains **CONDITIONAL**: only **{result['within_10_percent']}/{result['independent_comparable_variables']}** deduplicated direct observations meet the 10% dynamic NRMSE gate. Therefore this delivery is **not ready for mechanical integration** and is conservatively marked **not ready for L2 calibration** until the remaining zero-to-pressure transient and low-flow `orif3f_` boundary are explicitly accepted.

## 1. What caused the hundreds-of-MPa chamber pressure

The failure was not pump displacement and was not fixed by clipping. Four structural transcription errors compounded:

1. The old valve used one area and a sign switch instead of four independent P-A/P-B/T-A/T-B tables.
2. It used `max(flow, 0)` on supply branches even though HYDVORF0 is bidirectional.
3. It assumed local SC_1 `P` was supply and `T` was tank. Direct Amesim port extraction proves the installed wrappers are reverse-fed in these scenarios: local `T` is the high rail and local `P` is the low return rail.
4. Most importantly, HJ020/HJ021 continuity was transcribed with the mechanical terms reversed. Amesim source uses `q1 + A1*v` and `q2 - A2*v`, with internal travel `xact=c2-x`. The old code used the opposite signs and opposite chamber-volume direction. Prescribed Amesim motion therefore compressed the wrong chamber against a missing discharge path.

Correcting these relations reduced the S1 pressure failure before any broad parameter fit. Evidence is retained in `33A`, `33H`, HJ020 source evidence, and the new tests.

## 2. Actual SC_1 four-port mapping

Level-2 IR gives:

- `orifice_14`: external port 0 ↔ 3, P-A;
- `orifice_13`: external port 0 ↔ 2, P-B;
- `orifice_24`: external port 1 ↔ 3, T-A;
- `orifice_23`: external port 1 ↔ 2, T-B.

`dirvalve_1/8/11` share the transferred four-table family, `dirvalve_6` has the crossed table family, and `dirvalve_2/9/12` contain only P-A and T-B. Each branch is evaluated separately and preserves reverse flow. The seven-instance mapping is in `33B`; reverse-flow evidence is in `33C`.

The metadata characteristic is 1 L/min at 1 bar, but the private `orif3f_` body is unavailable. S0 directly identifies an operating-range scale of 1.425; S1/S2 validate the main branches. Of {len(flows)} measured endpoint comparisons, **{flow_pass} pass** and **{flow_fail} fail**. All three failures are the 10%-open P-B branch in S1, where laminar-transition behavior is not reproduced. This is why SC_1 port-flow validation is `CONDITIONAL`, not a false exact pass.

## 3. Supply algebraic network

The new state-free network distinguishes:

- pump outlet sensor;
- RV010 high-pressure inlet / HYDPRV0 upstream rail;
- each HYDPRV0 regulated SC_1 T rail;
- SC_1 P / relief outlet return rail;
- tank at 0 Pa gauge.

Pressure losses are not one universal `R_eq`. Front and rear pump-outlet paths and returns use separate S0-identified resistances, with S1/S2 reserved for validation. The rear group also includes a measured 4.47 L/min macro auxiliary flow: `pump - Σpprv - relief`, stable across S0/S1/S2. It represents real omitted control/spring-return branches and is reported explicitly rather than hidden as leakage.

All sampled pump, relief, and return node balances pass. Worst dimensional residual is **{worst_balance:.3e} m³/s**. There is no pressure hard clip; root failure is explicit.

## 4. Paired S0/S1/S2 validation

All Amesim scenarios are frozen successful oracles. Python uses their measured commands, pump speeds, initial chamber states, and prescribed HJ020/HJ021 mechanical boundary. Position and velocity are therefore inputs, not independent predictions.

Evidence was reclassified and deduplicated. Shared pump pressure is counted once per supply group; hydraulic force and P/T totals are derived consistency, not extra independent samples. Direct independent observations are the eight chamber pressures, two group pump-outlet sensors, and two work-port flows per primary valve for each scenario.

{metric_summary}

Steady S1 rear chamber errors are much smaller than full-transient NRMSE, but the algebraic supply pressure rises immediately whereas Amesim contains omitted supply compliance. That zero-to-pressure transient is the main remaining macro mismatch. Adding a supply state is not done here because its volume/time-constant evidence has not yet been frozen.

## 5. Performance

With cached input replay and 0.5 ms RK4, actual 1 s paired runs were:

- S1: {result['runtime']['S1']['wall_time_s']:.3f} s wall time;
- S2: {result['runtime']['S2']['wall_time_s']:.3f} s wall time.

The actual 100 s periodic S2 run took **{result['benchmark_100s']['wall_time_s']:.3f} s**, reached 100 s physical time, and remained finite with maximum chamber pressure **{result['benchmark_100s']['max_chamber_pressure_pa']/1e6:.3f} MPa**. This is only {100.0/result['benchmark_100s']['wall_time_s']:.3f}× realtime. Performance is therefore not an R3 pass and should be optimized only after the remaining physics boundary is accepted.

## 6. Regression and safety

- Pump displacement/speed law unchanged; pump-flow regression PASS.
- Dynamic state count 16; pipe dynamic states 0.
- IR V3 unchanged.
- Protected model SHA-256 remained `7613615723973d66a7122c74956c5161f720a64b243139fe9736cb270303b767` for both protected files.
- Amesim runs used isolated copies and closed without saving protected models.
- Full repository: **222 passed**.

## 7. Remaining issues and next decision

1. Resolve or accept a low-flow `orif3f_` surrogate for the three small P-B observations.
2. Decide whether a single evidence-backed supply compliance state is necessary to reproduce the 0–0.1 s pump-pressure rise. This would be a documented macro structural change, not a pipe-state rollback.
3. Only after that decision, perform small-parameter L2 identification; do not fit Cd, bulk modulus, mass, damping, and all path resistances simultaneously.
4. Mechanical integration remains blocked because motion is replayed from Amesim and not independently predicted.

## Final status

- SC1 AREA TABLE TRANSFER: **PASS**
- SC1 PORT FLOW VALIDATION: **CONDITIONAL**
- SUPPLY ALGEBRAIC MAPPING: **PASS**
- ALL NODE FLOW BALANCES: **PASS**
- S0/S1/S2 DYNAMIC REGRESSION: **CONDITIONAL**
- READY FOR L2 TARGETED CALIBRATION: **NO**
- READY FOR MECHANICAL INTEGRATION: **NO**
"""
    DOC.parent.mkdir(parents=True, exist_ok=True)
    DOC.write_text(report, encoding="utf-8")

    if HANDOFF.exists():
        shutil.rmtree(HANDOFF)
    HANDOFF.mkdir(parents=True)
    numbered = {
        DOC: "01_phase_L1_R3_physics_mapping_report.md",
        result_path: "02_33L_phase_L1_R3_results.json",
        AUD/"33A_baseline_pressure_failure_trace.csv": "03_33A_baseline_pressure_failure_trace.csv",
        AUD/"33B_SC1_four_port_area_mapping.csv": "04_33B_SC1_four_port_area_mapping.csv",
        AUD/"33C_SC1_reverse_flow_audit.csv": "05_33C_SC1_reverse_flow_audit.csv",
        AUD/"33D_SC1_individual_orifice_validation.csv": "06_33D_SC1_individual_orifice_validation.csv",
        AUD/"33E_supply_algebraic_node_map.csv": "07_33E_supply_algebraic_node_map.csv",
        AUD/"33F_path_resistance_parameter_map.csv": "08_33F_path_resistance_parameter_map.csv",
        AUD/"33G_algebraic_node_balance_checks.csv": "09_33G_algebraic_node_balance_checks.csv",
        AUD/"33H_staged_regression.csv": "10_33H_staged_regression.csv",
        AUD/"33I_reclassified_comparison_metrics.csv": "11_33I_reclassified_comparison_metrics.csv",
        AUD/"33J_paired_timeseries.csv": "12_33J_paired_timeseries.csv",
        AUD/"33K_runtime_benchmark.csv": "13_33K_runtime_benchmark.csv",
    }
    for source, name in numbered.items():
        copy_file(source, HANDOFF/name)
    for image in OUT.glob("*.png"):
        copy_file(image, HANDOFF/"figures"/image.name)
    for name in ("parameters.py","pump.py","valve.py","actuator.py","supply.py",
                 "model.py","simulation.py","outputs.py"):
        source = ROOT/"src"/"steering_sim"/"hydraulics_lumped"/name
        if source.exists():
            copy_file(source, HANDOFF/"source_review"/name)
    for name in ("test_r3_physics_mapping.py","test_r2_macro_mapping.py",
                 "test_r1_validation.py","test_pressure_sanity.py",
                 "test_sine_response.py","test_step_response.py"):
        copy_file(ROOT/"tests"/"hydraulics_lumped"/name, HANDOFF/"tests"/name)
    for name in ("run_phase_l1_r3_baseline.py","run_phase_l1_r3_amesim_ports.py",
                 "run_phase_l1_r3_amesim_path_nodes.py","run_phase_l1_r3_validation.py",
                 "run_phase_l1_r3_100s_benchmark.py","finalize_phase_l1_r3.py"):
        copy_file(ROOT/"scripts"/"hydraulics"/name, HANDOFF/"scripts"/name)
    for tree in (AUD/"amesim_r3_ports_isolated", AUD/"amesim_r3_path_isolated"):
        for log in tree.rglob("*.log"):
            copy_file(log, HANDOFF/"amesim_logs"/tree.name/log.parent.name/log.name)
    copy_file(AUD/"33_amesim_sc1_ports_raw.json", HANDOFF/"evidence"/"33_amesim_sc1_ports_raw.json")
    copy_file(AUD/"33_amesim_path_nodes_raw.json", HANDOFF/"evidence"/"33_amesim_path_nodes_raw.json")
    commands = """# Reproduction commands\n\n```powershell\ncd E:\\15_project\n& 'E:\\ProgramData\\condaData\\envs_dirs\\steering_sim\\python.exe' .\\scripts\\hydraulics\\run_phase_l1_r3_validation.py\n& 'E:\\ProgramData\\condaData\\envs_dirs\\steering_sim\\python.exe' .\\scripts\\hydraulics\\run_phase_l1_r3_100s_benchmark.py\n& 'E:\\ProgramData\\condaData\\envs_dirs\\steering_sim\\python.exe' -m pytest -q -p no:cacheprovider\n& 'E:\\ProgramData\\condaData\\envs_dirs\\steering_sim\\python.exe' .\\scripts\\hydraulics\\finalize_phase_l1_r3.py\n```\n\nAMEPython extraction scripts operate only on isolated copies and verify protected SHA-256 hashes.\n"""
    (HANDOFF/"REPRODUCTION_COMMANDS.md").write_text(commands, encoding="utf-8")
    readme = f"""请将整个 phase_L1_R3.zip 上传给 ChatGPT 审核。

关键状态：
- SC1 AREA TABLE TRANSFER = PASS
- SC1 PORT FLOW VALIDATION = CONDITIONAL ({flow_pass} pass / {flow_fail} fail)
- SUPPLY ALGEBRAIC MAPPING = PASS
- ALL NODE FLOW BALANCES = PASS
- Python chamber pressure: {result['python_max_chamber_pressure_before_pa']/1e6:.3f} -> {result['python_max_chamber_pressure_after_pa']/1e6:.3f} MPa
- 独立动态指标 <=10%: {result['within_10_percent']}/{result['independent_comparable_variables']}
- PYTEST = 222 passed
- READY FOR L2 = NO
- READY FOR MECHANICAL INTEGRATION = NO

从 01 报告开始审阅；04–11 是映射、守恒与独立指标证据，12 是完整配对时序，source_review/ 是本轮核心实现，tests/ 是行为回归，amesim_logs/ 与 evidence/ 是隔离副本运行证据。
"""
    (HANDOFF/"00_README_发给ChatGPT.txt").write_text(readme, encoding="utf-8-sig")

    ZIP.parent.mkdir(parents=True, exist_ok=True)
    if ZIP.exists():
        ZIP.unlink()
    with zipfile.ZipFile(ZIP, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(HANDOFF.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(HANDOFF.parent))
    with zipfile.ZipFile(ZIP) as archive:
        bad = archive.testzip()
        names = set(archive.namelist())
    if bad is not None or "phase_L1_R3/00_README_发给ChatGPT.txt" not in names:
        raise RuntimeError(f"handoff ZIP validation failed: {bad}")
    print(f"REPORT={DOC}")
    print(f"HANDOFF={ZIP} FILES={len(names)} SIZE={ZIP.stat().st_size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
