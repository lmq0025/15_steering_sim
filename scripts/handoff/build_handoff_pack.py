"""PHASE HANDOFF：从**活代码与实测输出**生成 Codex 交接用的附加资料。

本脚本不修改任何仿真模型、算法、参数或界面，只做只读提取：

* ``codex_interface_map.json`` —— 关键模块的类/方法/字段签名（用 ``ast`` 提取，
  不是手抄），以及配置键、状态布局、时间序列列名；
* ``degradation_interface_audit.csv`` —— 退化参数逐个的作用点与作用范围；
* ``codex_handoff_baseline.json`` —— J1-R2 正式基线的实测数字；
* ``codex_handoff_facts.md`` —— 上面三份资料的人类可读摘要。

用法::

    python scripts/handoff/build_handoff_pack.py
"""
from __future__ import annotations

import argparse
import ast
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

OUT = ROOT / "docs" / "handoff"

#: 需要提取接口的关键模块（相对仓库根）。
MODULES = {
    "mechanical_model": "src/steering_sim/engineering/model.py",
    "mechanical_mechanism": "src/steering_sim/engineering/mechanism.py",
    "hydraulic_parameters": "src/steering_sim/hydraulics_engineering/parameters.py",
    "hydraulic_model": "src/steering_sim/hydraulics_engineering/model.py",
    "hydraulic_authority": "src/steering_sim/hydraulics_engineering/authority.py",
    "j0_config": "src/steering_sim/j0_coupling/config.py",
    "j0_geometry": "src/steering_sim/j0_coupling/geometry.py",
    "j0_road_load": "src/steering_sim/j0_coupling/road_load.py",
    "j0_runner": "src/steering_sim/j0_coupling/runner.py",
    "j0_mechanism_factory": "src/steering_sim/j0_coupling/mechanism.py",
    "control_pid": "src/steering_sim/control/pid.py",
    "control_base": "src/steering_sim/control/base.py",
    "demo_service": "src/steering_sim/demo/service.py",
    "demo_scenario": "src/steering_sim/demo/scenario.py",
    "demo_batch": "src/steering_sim/demo/batch.py",
    "demo_assessment": "src/steering_sim/demo/assessment.py",
    "demo_plots": "src/steering_sim/demo/plots.py",
    "demo_ui": "src/steering_sim/demo/ui.py",
    "demo_degradation_placeholder": "src/steering_sim/demo/degradation.py",
}

CONFIG_FILES = {
    "j0_control": "configs/j0/j0_config.json",
    "mechanical_engineering": "configs/j1/engineering_config.json",
    "mechanical_design": "configs/j1/engineering_mechanism.json",
    "hydraulic_engineering": "configs/j1r2/engineering_hydraulics.json",
}

#: 退化参数的作用点审计。``scope`` 说明它是全系统共用还是部件级。
#: 行号由本脚本在运行时从源码中定位（``anchor`` 是要找的表达式）。
DEGRADATION_AUDIT = (
    # 参数名, 部件, 单位, 作用点(method), 源码锚点, 作用范围, 是否进入动力学
    ("pump_volumetric_efficiency", "泵", "-", "模型", "_supply_equilibrium_pressure",
     "pump.ideal_flow_m3_s * degradation.pump_volumetric_efficiency",
     "GLOBAL", "YES"),
    ("pump_volumetric_efficiency", "泵", "-", "模型", "EngineeringHydraulicSystem.evaluate",
     "pump_flow = pump.ideal_flow_m3_s *",
     "GLOBAL", "YES"),
    ("pump_internal_leakage_m3_s_per_pa", "泵", "m3/s/Pa", "模型",
     "EngineeringHydraulicSystem.evaluate",
     "pump_flow -= degradation.pump_internal_leakage_m3_s_per_pa * pressure",
     "GLOBAL", "YES"),
    ("supply_pressure_scale", "泵/供油轨", "-", "模型", "EngineeringHydraulicSystem.evaluate",
     "degradation.supply_pressure_scale", "GLOBAL", "YES"),
    ("valve_flow_coefficient_scale", "阀", "-", "模型",
     "EngineeringHydraulicSystem.evaluate",
     "valve.maximum_area_m2 * degradation.valve_flow_coefficient_scale",
     "GLOBAL(乘子) x PER_CHANNEL(阀参数)", "YES"),
    ("valve_lag_scale", "阀", "-", "模型", "EngineeringHydraulicSystem.evaluate",
     "valve.lag_time_s * degradation.valve_lag_scale",
     "GLOBAL(乘子) x PER_CHANNEL(阀参数)", "YES"),
    ("cylinder_internal_leakage_m3_s_per_pa", "缸", "m3/s/Pa", "模型",
     "EngineeringHydraulicSystem.evaluate",
     "degradation.cylinder_internal_leakage_m3_s_per_pa * (p_a - p_b)",
     "GLOBAL(乘子) x PER_CHANNEL(缸参数)", "YES"),
    ("cylinder_friction_scale", "缸", "-", "模型",
     "EngineeringHydraulicSystem.evaluate",
     "degradation.cylinder_friction_scale * (",
     "GLOBAL(乘子) x PER_CHANNEL(缸参数)", "YES"),
    ("ValveParameters.deadband", "阀", "-", "参数", "ValveParameters",
     "(per channel field)", "PER_CHANNEL", "YES"),
    ("ValveParameters.lag_time_s", "阀", "s", "参数", "ValveParameters",
     "(per channel field)", "PER_CHANNEL", "YES"),
    ("ValveParameters.discharge_coefficient", "阀", "-", "参数", "ValveParameters",
     "(per channel field)", "PER_CHANNEL", "YES"),
    ("CylinderParameters.coulomb_friction_n", "缸", "N", "参数", "CylinderParameters",
     "(per channel field)", "PER_CHANNEL", "YES"),
    ("CylinderParameters.viscous_damping_n_s_per_m", "缸", "N*s/m", "参数",
     "CylinderParameters", "(per channel field)", "PER_CHANNEL", "YES"),
    ("CylinderParameters.area_a_m2 / area_b_m2", "缸", "m2", "参数",
     "CylinderParameters", "(per channel field)", "PER_CHANNEL", "YES"),
    ("PumpParameters.displacement_m3_per_rad", "泵", "m3/rad", "参数",
     "PumpParameters", "(per supply rail field)", "PER_SUPPLY_RAIL", "YES"),
    ("PumpParameters.relief_pressure_pa", "泵/溢流阀", "Pa", "参数", "PumpParameters",
     "(per supply rail field)", "PER_SUPPLY_RAIL", "YES"),
    ("PumpParameters.relief_area_m2", "溢流阀", "m2", "参数", "PumpParameters",
     "(per supply rail field)", "PER_SUPPLY_RAIL", "YES"),
    ("PumpParameters.nominal_speed_rad_s", "泵", "rad/s", "参数", "PumpParameters",
     "(per supply rail field, constant - NOT a state)", "PER_SUPPLY_RAIL", "YES(常量)"),
)

#: 退化驱动特征：时间序列里已有的列（由 runner._row 写入）。
FEATURE_HINTS = (
    ("泵", "供油压力", "supply_pressure_front_mpa_g / supply_pressure_rear_mpa_g", "逐采样点"),
    ("泵", "理论流量", "EngineeringOutput.pump_flow_m3_s（未写入 CSV）", "逐采样点"),
    ("泵", "取用流量", "EngineeringOutput.demand_flow_m3_s（未写入 CSV）", "逐采样点"),
    ("泵", "流量余量", "pump_capacity_margin_front_m3_s / _rear_m3_s", "逐采样点"),
    ("泵", "供油不足标志", "pump_capacity_insufficient_front / _rear", "逐采样点"),
    ("泵", "泵压差", "需用 supply_pressures_pa_g[j] − tank_pressure_pa 现算", "派生"),
    ("泵", "泵转速", "PumpParameters.nominal_speed_rad_s（常量，非状态）", "**缺口**"),
    ("阀", "阀命令（阀芯位置）", "<channel>_valve_command", "逐采样点"),
    ("阀", "未限幅请求", "<channel>_pid_unclipped_request", "逐采样点"),
    ("阀", "贴限幅标志", "<channel>_pid_at_limit", "逐采样点"),
    ("阀", "流量", "<channel>_flow_a_m3_s / <channel>_flow_b_m3_s", "逐采样点"),
    ("缸", "位移", "<channel>_x_m", "逐采样点"),
    ("缸", "速度", "<channel>_v_m_s", "逐采样点"),
    ("缸", "两腔压力", "<channel>_pA_mpa_g / <channel>_pB_mpa_g", "逐采样点"),
    ("缸", "液压力", "<channel>_hydraulic_force_n", "逐采样点"),
    ("缸", "负载力", "<channel>_load_force_n", "逐采样点"),
    ("缸", "泄漏流量", "未单独输出（已并入 flow_a/flow_b）", "**缺口**"),
    ("缸", "累计行程/累计流量", "未累计（需在调用方对时间序列积分）", "**缺口**"),
    ("系统", "目标/实际行程", "<channel>_x_ref_eff_m / <channel>_x_m", "逐采样点"),
    ("系统", "机构坐标", "<channel>_q_ref_rad / <channel>_q_actual_rad", "逐采样点"),
    ("系统", "道路力矩", "<channel>_Q_road_nm", "逐采样点"),
    ("系统", "十二轮角", "wheel_<wheel>_actual_deg / _command_deg / _target_mechanism_deg", "逐采样点"),
)


def _signature(node: ast.AST) -> str:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return ast.unparse(node)
    args = node.args
    parts: list[str] = []
    positional = args.posonlyargs + args.args
    defaults: list[ast.expr | None] = [None] * (len(positional) - len(args.defaults))
    defaults += list(args.defaults)
    for argument, default in zip(positional, defaults):
        parts.append(argument.arg if default is None else f"{argument.arg}=…")
    if args.vararg:
        parts.append("*" + args.vararg.arg)
    elif args.kwonlyargs:
        parts.append("*")
    for argument, default in zip(args.kwonlyargs, args.kw_defaults):
        parts.append(argument.arg if default is None else f"{argument.arg}=…")
    if args.kwarg:
        parts.append("**" + args.kwarg.arg)
    returns = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    return f"def {node.name}({', '.join(parts)}){returns}"


def _module_api(path: Path) -> dict:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions: list[str] = []
    classes: dict[str, dict] = {}
    constants: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            methods, attributes, properties = [], [], []
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if sub.name.startswith("_") and not sub.name.startswith("__"):
                        continue
                    decorated = {ast.unparse(d) for d in sub.decorator_list}
                    if "property" in decorated:
                        properties.append(sub.name)
                    else:
                        methods.append(_signature(sub))
                elif isinstance(sub, ast.AnnAssign) and isinstance(sub.target, ast.Name):
                    attributes.append({
                        "name": sub.target.id,
                        "type": ast.unparse(sub.annotation)})
            classes[node.name] = {
                "bases": [ast.unparse(b) for b in node.bases],
                "methods": methods,
                "properties": properties,
                "attributes": attributes,
            }
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                functions.append(_signature(node))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    constants[target.id] = ast.unparse(node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id.isupper():
                constants[node.target.id] = ast.unparse(node.annotation)
    return {"path": str(path.relative_to(ROOT)).replace("\\", "/"),
            "module_functions": functions, "constants": constants,
            "classes": classes}


def _line_of(anchor: str, source: str) -> int | None:
    needle = anchor.split("\\\n")[0].strip()
    for number, line in enumerate(source.splitlines(), start=1):
        if needle and needle.replace(" ", "") in line.replace(" ", ""):
            return number
    return None


def build_interface_map() -> dict:
    payload = {
        "note": ("本文件由 scripts/handoff/build_handoff_pack.py 用 ast 从活代码提取，"
                 "不是手抄。行号仅供定位，接口以签名与名称为准。"),
        "modules": {}, "configs": {},
    }
    for key, relative in MODULES.items():
        payload["modules"][key] = _module_api(ROOT / relative)
    for key, relative in CONFIG_FILES.items():
        payload["configs"][key] = {
            "path": relative,
            "raw": json.loads((ROOT / relative).read_text(encoding="utf-8")),
        }

    from steering_sim.hydraulics_engineering import (EngineeringHydraulicSystem,
                                                     load_parameters, state_layout)
    from steering_sim.hydraulics_engineering.model import CHANNEL_STATE_SIZE
    parameters = load_parameters(ROOT / "configs" / "j1r2"
                                 / "engineering_hydraulics.json")
    system = EngineeringHydraulicSystem(parameters)
    payload["hydraulic_state_layout"] = {
        "channel_state_size": CHANNEL_STATE_SIZE,
        "channel_state_fields": ["pA", "pB", "x", "v", "u_valve_spool"],
        "state_size": int(system.state_size),
        "offsets": {key: int(value) for key, value in state_layout(parameters).items()},
        "supply_order": list(system.supply_names),
        "channels_on_supply": {
            name: [c.name for c in parameters.channels if c.supply == name]
            for name in system.supply_names},
    }

    from steering_sim.j0_coupling.config import CHANNEL_ORDER, DOF_BY_CHANNEL
    from steering_sim.engineering.model import EngineeringSteeringModel
    model = EngineeringSteeringModel(
        ROOT / "mechanical_model_input_spec_v1.0.yaml",
        ROOT / "configs" / "j1" / "engineering_config.json",
        ROOT / "configs" / "j1" / "engineering_mechanism.json")
    payload["mechanical_mapping"] = {
        "dof_order": ["q_front", "q4", "q5", "q6"],
        "channel_order": list(CHANNEL_ORDER),
        "channel_to_dof": dict(DOF_BY_CHANNEL),
        "group_to_axles": {key: list(group.axles)
                           for key, group in model.design.groups.items()},
        "rear_axles_steer_opposite": [4, 5, 6],
        "third_axle_locked": True,
        "q_envelopes_rad": {key: list(value)
                            for key, value in model.q_envelopes.items()},
        "front_stroke_per_q_m_per_rad": model._front_stroke_per_q,
    }

    from steering_sim.demo.batch import build_context
    context = build_context()
    payload["hydraulic_capability_baseline"] = {
        "availability_n": dict(context.availability_n),
        "half_stroke_mm": dict(context.half_stroke_mm),
    }

    samples = ROOT / "outputs" / "j1r2" / "dynamic" / "低速5_+30deg_timeseries.csv"
    if samples.exists():
        with samples.open(encoding="utf-8-sig", newline="") as handle:
            payload["timeseries_columns"] = next(csv.reader(handle))
    return payload


def build_degradation_audit() -> list[dict]:
    model_source = (ROOT / "src" / "steering_sim" / "hydraulics_engineering"
                    / "model.py").read_text(encoding="utf-8")
    parameters_source = (ROOT / "src" / "steering_sim" / "hydraulics_engineering"
                         / "parameters.py").read_text(encoding="utf-8")
    rows = []
    for (name, part, unit, kind, where, anchor, scope, applied) in DEGRADATION_AUDIT:
        source = parameters_source if kind == "参数" else model_source
        rows.append({
            "parameter": name, "part": part, "unit": unit,
            "defined_in": ("src/steering_sim/hydraulics_engineering/parameters.py"
                           if kind == "参数"
                           else "src/steering_sim/hydraulics_engineering/parameters.py"),
            "applied_in": where,
            "source_anchor": anchor.split("\\\n")[0],
            "source_line": _line_of(anchor, source),
            "scope": scope, "wired_into_dynamics": applied,
        })
    return rows


def build_baseline() -> dict:
    def load(path: Path, default=None):
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default

    gate1 = load(ROOT / "outputs" / "j1" / "gate1_summary.json", {})
    sizing = load(ROOT / "outputs" / "j1r2" / "hydraulic_sizing.json", {})
    batch = load(ROOT / "outputs" / "j1r2" / "j1r2_full_cases_summary.json", {})
    dynamic = load(ROOT / "outputs" / "j1r2" / "dynamic" / "j1r2_dynamic.json",
                   {"records": []})
    convergence = load(ROOT / "outputs" / "j1r2" / "step_convergence.json", {})
    status = load(ROOT / "outputs" / "j1r2" / "j1r2_status.json", {})
    records = dynamic.get("records", [])
    return {
        "source_of_truth": {
            "mechanical": "ENGINEERING_STEERING_MODEL",
            "hydraulic": "ENGINEERING_HYDRAULIC_V1",
            "report": "docs/integration/phase_J1_R2_report.md",
            "package": "handoff_to_chatgpt/phase_J1_R2.zip",
        },
        "gate1_geometry": gate1,
        "hydraulic_sizing": sizing,
        "batch": batch,
        "dynamic": {
            "cases": len(records),
            "numerical_completed": sum(r["NUMERICAL_COMPLETED"] for r in records),
            "steady_tracking_pass": sum(r["TRACKING_PASS"] for r in records),
            "transient_tracking_pass": sum(r["TRANSIENT_TRACKING_PASS"] for r in records),
            "vehicle_dynamic_infeasible": sum(r["VEHICLE_DYNAMIC_INFEASIBLE"]
                                              for r in records),
            "worst_steady_error_deg": max(
                (r["steady_max_tracking_error_vs_command_deg"] for r in records),
                default=None),
            "worst_transient_error_deg": max(
                (r["max_tracking_error_vs_command_deg"] for r in records), default=None),
            "max_control_saturation_fraction": max(
                (r.get("control_saturation_fraction") or 0.0 for r in records),
                default=None),
            "records": records,
        },
        "step_convergence": convergence,
        "status_block": status,
    }


REPRODUCE = """# 复现命令（PHASE HANDOFF）

唯一 Python：`E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe`
工作目录：`E:_project`

本阶段**不需要安装任何依赖**：`numpy / scipy / pandas / openpyxl / matplotlib /
pytest / Pillow` 全部已装（见 `pyproject.toml` 的 `[project] dependencies` 与
`[project.optional-dependencies]`）。PySide6 未安装，安装需甲方授权。

## 1. 环境核验

```
E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe -c "import sys,numpy,scipy,pandas,openpyxl,matplotlib;print(sys.version);print(numpy.__version__,scipy.__version__,pandas.__version__,openpyxl.__version__,matplotlib.__version__)"
```

## 2. 全仓测试（基线 576 passed，约 17 分钟）

```
E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe -m pytest -q
```

只跑工程模型相关：

```
E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe -m pytest tests/hydraulics_engineering tests/engineering tests/j0_coupling -q
```

## 3. 单工况

```
E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe -m steering_sim.demo.cli run --angle 30 --speed 10 --duration 3.75
E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe -m steering_sim.demo.cli assess --angle 30 --speed 10
```

## 4. 中文界面

```
start_steering_demo.bat
```

## 5. 3111 批量工况（约 30 s）

```
E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe scripts/j1r2/run_j1r2_batch.py
E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe scripts/j1r2/run_j1r2_batch.py --cases 我的工况.xlsx
```

## 6. 代表工况真实动态积分（约 10 分钟）

```
E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe scripts/j1r2/run_j1r2_dynamic.py
E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe scripts/j1r2/run_j1r2_dynamic.py --sequence-only   # 只重跑多段连续指令工况
```

## 7. 从零重建设计与配置（改机械/液压设计时才需要）

```
python scripts/j1r2/retune_front_follower.py --scale 1.39
python scripts/j1/build_engineering_config.py
python scripts/j1/check_gate1_geometry.py
python scripts/j1r2/design_engineering_hydraulics.py --report
python scripts/j1r2/check_step_convergence.py
python scripts/j1r2/run_j1r2_dynamic.py
python scripts/j1r2/run_j1r2_batch.py
python scripts/j1r2/make_j1r2_figures.py
python scripts/j1r2/capture_ui_screenshot.py
python scripts/j1r2/write_j1r2_report.py
python scripts/j1r2/finalize_status.py --tests <测试数>
python scripts/j1r2/package_phase_j1r2.py
```

## 8. 本交接包附加资料重建

```
python scripts/handoff/build_handoff_pack.py
python scripts/handoff/package_codex_handoff.py
```

## 9. 主要结果路径

| 内容 | 路径 |
|---|---|
| J1-R2 报告 | `docs/integration/phase_J1_R2_report.md` |
| 61 角覆盖 | `outputs/j1/gate1_angle_table.csv` |
| 液压选型 | `outputs/j1r2/hydraulic_sizing.json` |
| 3111 结果 | `outputs/j1r2/j1r2_full_cases.csv` / `.xlsx` |
| 18 工况动态 | `outputs/j1r2/dynamic/j1r2_dynamic.json` |
| 时间序列 | `outputs/j1r2/dynamic/<工况>_timeseries.csv` |
| 步长收敛 | `outputs/j1r2/step_convergence.json` |
| 状态块 | `outputs/j1r2/j1r2_status_block.txt` |
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    interface = build_interface_map()
    (out / "codex_interface_map.json").write_text(
        json.dumps(interface, ensure_ascii=False, indent=2), encoding="utf-8")

    audit = build_degradation_audit()
    with (out / "degradation_interface_audit.csv").open(
            "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(audit[0]))
        writer.writeheader()
        writer.writerows(audit)

    baseline = build_baseline()
    (out / "codex_handoff_baseline.json").write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8")

    with (out / "degradation_feature_sources.csv").open(
            "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["部件", "退化驱动特征", "现有来源（列名/接口）", "备注"])
        writer.writerows(FEATURE_HINTS)

    # 四份正式配置的原文快照（便于对照，不必另开仓库文件）
    (out / "CONFIG_SNAPSHOT.json").write_text(json.dumps({
        "note": ("四份正式配置的**原文快照**，取自生成本文件时的仓库状态。"
                 "以仓库里的文件为准，这里只是便于交接对照。"),
        "files": {name: json.loads((ROOT / relative).read_text(encoding="utf-8"))
                  for name, relative in CONFIG_FILES.items()},
        "paths": dict(CONFIG_FILES),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    (out / "REPRODUCE.md").write_text(REPRODUCE, encoding="utf-8")

    lines = [
        "# Codex 交接附加资料（由脚本从活代码生成）",
        "",
        "本目录下的三份机器可读资料由 `scripts/handoff/build_handoff_pack.py` 用",
        "`ast` 从**当前源码**提取，不是手抄，可作为接口的唯一权威来源：",
        "",
        "| 文件 | 内容 |",
        "|---|---|",
        "| `codex_interface_map.json` | 关键模块的类/方法/字段签名、配置键、"
        "液压状态布局、机械映射、时间序列列名 |",
        "| `degradation_interface_audit.csv` | 退化参数逐个的作用点、源码行号、"
        "作用范围、是否真正进入动力学 |",
        "| `degradation_feature_sources.csv` | 退化驱动特征在现有模型里的来源，"
        "并显式标出缺口 |",
        "| `codex_handoff_baseline.json` | J1-R2 正式基线的实测数字"
        "（61 角、液压选型、3111 批算、18 工况动态、步长收敛、状态块） |",
        "",
        "接口清单中：",
        "",
        f"* 关键模块数：{len(interface['modules'])}",
        f"* 配置键组数：{len(interface['configs'])}",
        f"* 液压状态维度：{interface['hydraulic_state_layout']['state_size']}"
        f"（每通道 {interface['hydraulic_state_layout']['channel_state_size']}）",
        f"* 时间序列列数：{len(interface.get('timeseries_columns', []))}",
        f"* 退化参数审计行数：{len(audit)}",
        "",
    ]
    (out / "README.md").write_text("\n".join(lines), encoding="utf-8")

    print(json.dumps({
        "interface_map": str(out / "codex_interface_map.json"),
        "degradation_audit": str(out / "degradation_interface_audit.csv"),
        "baseline": str(out / "codex_handoff_baseline.json"),
        "state_size": interface["hydraulic_state_layout"]["state_size"],
        "timeseries_columns": len(interface.get("timeseries_columns", [])),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
