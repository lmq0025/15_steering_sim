from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(r"E:\15_project")
AUD = ROOT / "hydraulic_audit_lumped"
DOC = ROOT / "docs" / "hydraulics" / "phase_L1_R2_macro_mapping_report.md"
OUT = ROOT / "outputs" / "hydraulics" / "phase_L1_R2"
HANDOFF = ROOT / "handoff_to_chatgpt" / "phase_L1_R2"
ZIP = ROOT / "handoff_to_chatgpt" / "phase_L1_R2.zip"


def copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def main() -> None:
    result_path = AUD / "32K_phase_L1_R2_results.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["pytest"] = "216 passed in 296.90s"
    result["final_acceptance"] = {
        "S0_comparability": "FAIL",
        "pump_input_mapping": "PASS",
        "valve_branch_mapping": "PASS",
        "supply_pressure_mapping": "FAIL",
        "supply_flow_conservation": "PASS",
        "ready_for_L2_macro_calibration": False,
        "ready_for_mechanical_integration": False,
    }
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    report_text = DOC.read_text(encoding="utf-8")
    if "## 最终测试" not in report_text:
        with DOC.open("a", encoding="utf-8") as stream:
            stream.write("\n## 最终测试\n\n全仓测试在可写临时目录权限下完成：`216 passed in 296.90s`。首次沙箱内运行的唯一失败来自 Windows 临时目录 ACL；同一测试在沙箱外通过，最终全仓单次运行全部通过。\n")

    if HANDOFF.exists():
        shutil.rmtree(HANDOFF)
    HANDOFF.mkdir(parents=True)
    required = {
        DOC: "01_phase_L1_R2_macro_mapping_report.md",
        result_path: "02_32K_phase_L1_R2_results.json",
        AUD/"32A_S0_comparability_audit.csv": "03_32A_S0_comparability_audit.csv",
        AUD/"32B_pump_valve_branch_mapping.csv": "04_32B_pump_valve_branch_mapping.csv",
        AUD/"32C_supply_sensor_and_loss_map.csv": "05_32C_supply_sensor_and_loss_map.csv",
        AUD/"32D_supply_balance_solver_audit.csv": "06_32D_supply_balance_solver_audit.csv",
        AUD/"32E_actuator_macro_error_trace.csv": "07_32E_actuator_macro_error_trace.csv",
        AUD/"32F_amesim_scenario_run_diagnostics.md": "08_32F_amesim_scenario_run_diagnostics.md",
        AUD/"32G_paired_macro_metrics.csv": "09_32G_paired_macro_metrics.csv",
        AUD/"32I_regression_checks.csv": "10_32I_regression_checks.csv",
        AUD/"32J_runtime_benchmark.csv": "11_32J_runtime_benchmark.csv",
        AUD/"32H_paired_timeseries.csv": "12_32H_paired_timeseries.csv",
        AUD/"32_amesim_paired_raw.json": "evidence/32_amesim_paired_raw.json",
        AUD/"31_amesim_paired_raw.json": "evidence/31_prior_failed_scenario_raw.json",
    }
    for source, name in required.items():
        if not source.exists():
            raise FileNotFoundError(source)
        copy(source, HANDOFF/name)

    for image in sorted(OUT.glob("*.png")):
        copy(image, HANDOFF/"figures"/image.name)
    for log in sorted((AUD/"amesim_r2_isolated").glob("*/ame_api.log")):
        copy(log, HANDOFF/"amesim_logs"/(log.parent.name+"_ame_api.log"))
    for name in ("parameters.py","pump.py","valve.py","actuator.py","supply.py",
                 "model.py","simulation.py","linearize.py","transfer_function.py"):
        path=ROOT/"src"/"steering_sim"/"hydraulics_lumped"/name
        if path.exists(): copy(path,HANDOFF/"source_review"/name)
    for path in sorted((ROOT/"tests"/"hydraulics_lumped").glob("*.py")):
        copy(path,HANDOFF/"tests"/path.name)
    for name in ("run_phase_l1_r2_amesim.py","run_phase_l1_r2_validation.py"):
        copy(ROOT/"scripts"/"hydraulics"/name,HANDOFF/"scripts"/name)

    readme = """PHASE L1-R2 审核包

将整个 phase_L1_R2.zip 上传给 ChatGPT。

结论：Amesim S0/S1/S2 已恢复并安全运行，但 44 个独立宏观动态量中 0 个达到 10%；供油测点/路径与 SC_1 宏观孔口映射尚不可信。不得把泵流量参数转移、S0 的 R_eq 标定点或规定机械运动当作独立验证。

受保护模型未修改；SHA-256 见报告和 JSON。动态状态 16，管路状态 0。L2 标定和机械集成都未就绪。

复现命令见 reproduction_commands.txt。核心代码在 source_review，测试在 tests，原始 Amesim API 日志在 amesim_logs。
"""
    (HANDOFF/"00_README_发给ChatGPT.txt").write_text(readme,encoding="utf-8")
    commands = r'''cd E:\15_project
& "E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe" -c "import sys; print(sys.executable)"
& "E:\Simcenter\2021.1\Amesim\win64\AMEPython.exe" .\scripts\hydraulics\run_phase_l1_r2_amesim.py --output .\hydraulic_audit_lumped\32_amesim_paired_raw.json
& "E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe" .\scripts\hydraulics\run_phase_l1_r2_validation.py
& "E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe" -m pytest -q
'''
    (HANDOFF/"reproduction_commands.txt").write_text(commands,encoding="utf-8")

    if ZIP.exists():
        ZIP.unlink()
    shutil.make_archive(str(ZIP.with_suffix("")), "zip", HANDOFF.parent, HANDOFF.name)
    print("HANDOFF", ZIP, ZIP.stat().st_size)


if __name__ == "__main__":
    main()
