"""R03-A2.5 point closure for parameter references and validation keys.

This tool consumes the accepted R03-A1/R03-A2 CSV evidence.  It does not
rescan or modify qh1_1.ame and it does not implement hydraulic equations.
"""
from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import math
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
AUDIT = ROOT / "configs/hydraulics/amesim_audit"
MODEL = ROOT / "qh1_1.ame"
INSTALLATION = Path(r"E:\Simcenter\2021.1\Amesim")
EXPECTED_PYTHON = Path(r"E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe")
EXPECTED_SHA = "7613615723973d66a7122c74956c5161f720a64b243139fe9736cb270303b767"

KEY_SUBMODELS = {
    "SC_1", "VALVEDYNAMICS0", "HYDVORF0", "PU001", "HJ020", "HJ0022",
    "HJ021", "HA001", "RV010", "RV011", "HYDPRV0", "CV010",
    "HYDCONSHTL0",
}

OUTPUTS = (
    "r03a25_global_parameter_resolution.csv",
    "r03a25_resolved_key_parameters.csv",
    "r03a25_scalar_variable_keys.csv",
    "r03a25_scalar_state_keys.csv",
    "r03a25_validation_channels_rekeyed.csv",
    "r03a25_baseline_validation_channels.csv",
    "r03a25_valvedynamics0_definition.csv",
    "r03a25_discrete_state_relevance.csv",
    "R03A25_VALVEDYNAMICS0_note.md",
    "R03A25_closure_report.md",
    "r03a25_manifest.json",
)


class ClosureError(RuntimeError):
    pass


def read_csv(name: str) -> list[dict[str, str]]:
    with (AUDIT / name).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(name: str, rows: list[dict[str, object]], fields: list[str]) -> None:
    with (AUDIT / name).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def file_identity(path: Path) -> dict[str, object]:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    stat = path.stat()
    return {"sha256": digest.hexdigest(), "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns}


def notes_value(notes: str, key: str) -> str:
    match = re.search(rf"(?:^|;\s*){re.escape(key)}=([^;]+)", notes or "")
    return match.group(1).strip() if match else "missing"


def xml_attr(raw: str, name: str) -> str:
    match = re.search(rf'\b{re.escape(name)}="([^"]*)"', raw or "")
    return match.group(1) if match else "missing"


def normalized_unit(unit: str) -> str:
    return "missing" if not unit or unit.lower() in {"null", "missing"} else unit


def safe_numeric(expression: str) -> str | None:
    """Evaluate only arithmetic, PI and sqrt from trusted AMESim parameter text."""
    try:
        node = ast.parse(expression, mode="eval")
    except SyntaxError:
        return None
    allowed_bin = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
                   ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b,
                   ast.Pow: lambda a, b: a ** b}
    allowed_unary = {ast.UAdd: lambda a: a, ast.USub: lambda a: -a}

    def visit(item: ast.AST) -> float:
        if isinstance(item, ast.Expression):
            return visit(item.body)
        if isinstance(item, ast.Constant) and isinstance(item.value, (int, float)):
            return float(item.value)
        if isinstance(item, ast.Name) and item.id.upper() == "PI":
            return math.pi
        if isinstance(item, ast.UnaryOp) and type(item.op) in allowed_unary:
            return allowed_unary[type(item.op)](visit(item.operand))
        if isinstance(item, ast.BinOp) and type(item.op) in allowed_bin:
            return allowed_bin[type(item.op)](visit(item.left), visit(item.right))
        if (isinstance(item, ast.Call) and isinstance(item.func, ast.Name)
                and item.func.id.lower() == "sqrt" and len(item.args) == 1
                and not item.keywords):
            return math.sqrt(visit(item.args[0]))
        raise ValueError("unsupported expression")

    try:
        return format(visit(node), ".15g")
    except (ValueError, ZeroDivisionError, OverflowError):
        return None


def model_globals(raw: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    result = {}
    for row in raw:
        if row["record_type"] != "model_global":
            continue
        name = row["row_index"].split(":", 1)[-1]
        result[name] = row
    return result


def super_globals(raw: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    result = {}
    for row in raw:
        if row["record_type"] != "supercomponent_global":
            continue
        name = xml_attr(row["raw_descriptor"], "GLOB_PARAM_NAME")
        result[(row["component_id"], name)] = row
    return result


def resolve_references(parameters: list[dict[str, str]], raw: list[dict[str, str]]) -> list[dict[str, object]]:
    globals_model = model_globals(raw)
    globals_super = super_globals(raw)
    rows: list[dict[str, object]] = []
    for parameter in parameters:
        if parameter["value_type"] not in {"global_reference", "local_reference"}:
            continue
        reference = parameter["raw_value"].strip()
        current = reference
        path = [f"{parameter['component_id']}::{parameter['parameter_name']}", current]
        visited = set()
        target = None
        status = "UNRESOLVED"
        resolved_raw = "missing"
        resolved_value = "missing"
        depth = 0
        notes = []
        while current and current not in visited:
            visited.add(current)
            depth += 1
            if parameter["value_type"] == "global_reference" or "__SC_" in current:
                base = current.split("__SC_", 1)[0]
                parent = parameter["component_id"].split("/", 1)[0]
                target = globals_super.get((parent, base))
                target_name = f"{parent}::{base}"
            else:
                target = globals_model.get(current)
                target_name = f"MODEL::{current}"
            if target is None:
                notes.append(f"No target found for {current}.")
                break
            resolved_raw = target["cir_raw_value"]
            path.append(target_name)
            if safe_numeric(resolved_raw) is not None:
                resolved_value = safe_numeric(resolved_raw)
                status = "RESOLVED"
                path.append(resolved_value)
                break
            if re.fullmatch(r"[A-Za-z_]\w*", resolved_raw):
                current = resolved_raw
                path.append(current)
                continue
            evaluated = safe_numeric(resolved_raw)
            if evaluated is not None:
                resolved_value = evaluated
                status = "RESOLVED"
                path.append(evaluated)
            else:
                status = "UNRESOLVED_EXPRESSION"
                notes.append("Expression is outside the restricted arithmetic/sqrt evaluator.")
            break
        if current in visited and status == "UNRESOLVED" and depth > 1:
            status = "CYCLE"
            notes.append("Reference cycle detected.")
        unit = normalized_unit(parameter["unit"])
        if unit == "missing" and target is not None:
            unit = normalized_unit(xml_attr(target["raw_descriptor"], "UNITS"))
        rows.append({
            "reference_name": reference,
            "reference_type": parameter["value_type"],
            "source_component": parameter["component_label"],
            "source_component_id": parameter["component_id"],
            "source_submodel": parameter["submodel"],
            "parameter_name": parameter["parameter_name"],
            "raw_reference": reference,
            "resolved_target": target_name if target is not None else "missing",
            "resolved_raw_value": resolved_raw,
            "resolved_value": resolved_value,
            "unit": unit,
            "resolution_depth": depth,
            "resolution_path": " -> ".join(path),
            "source": "ame_cir",
            "confidence": "confirmed" if status == "RESOLVED" else "missing",
            "status": status,
            "notes": " ".join(notes) or "Reference retained and closed against accepted R03-A2 CIR evidence.",
        })
    return sorted(rows, key=lambda r: (str(r["reference_type"]), str(r["reference_name"]),
                                       str(r["source_component_id"]), str(r["parameter_name"])))


def key_parameter(parameter: dict[str, str]) -> bool:
    name = parameter["parameter_name"].lower()
    if parameter["submodel"] == "PU001":
        return True
    if parameter["submodel"] in {"HJ020", "HJ0022", "HJ021"}:
        return any(token in name for token in (
            "diameter", "stroke", "dead volume", "friction", "leakage", "endstop",
            "spring", "hydraulic fluid", "pressure at port", "displacement"))
    if parameter["submodel"] in {"SC_1", "VALVEDYNAMICS0", "HA001", "RV010"}:
        return True
    if parameter["submodel"] == "HYDVORF0":
        return any(token in name for token in (
            "flow rate", "pressure drop", "coefficient", "flow number", "reynolds",
            "diameter", "width", "height", "density", "viscosity", "signal value",
            "hydraulic fluid", "section type", "parallel orifices", "filename"))
    return False


def resolved_key_parameters(parameters: list[dict[str, str]], resolutions: list[dict[str, object]]) -> list[dict[str, object]]:
    lookup = {(str(r["source_component_id"]), str(r["parameter_name"]), str(r["raw_reference"])): r
              for r in resolutions}
    rows = []
    for parameter in parameters:
        if not key_parameter(parameter):
            continue
        resolution = lookup.get((parameter["component_id"], parameter["parameter_name"],
                                 parameter["raw_value"]))
        if resolution:
            value = resolution["resolved_value"]
            unit = resolution["unit"]
            status = resolution["status"]
            reference = parameter["raw_value"]
        else:
            value = parameter["value"]
            unit = normalized_unit(parameter["unit"])
            status = "DIRECT" if value != "missing" else "DIRECT_RAW"
            reference = "missing"
        rows.append({
            "component_id": parameter["component_id"],
            "component_label": parameter["component_label"],
            "submodel": parameter["submodel"],
            "parameter_name": parameter["parameter_name"],
            "raw_value": parameter["raw_value"],
            "resolved_value": value,
            "unit": unit,
            "reference_name": reference,
            "resolution_status": status,
            "source": parameter["source"] if not resolution else "ame_cir",
            "confidence": parameter["confidence"] if status in {"DIRECT", "DIRECT_RAW", "RESOLVED"} else "missing",
            "required_for_r03b": "true",
            "notes": ("Current model value; no default substitution. " + parameter["notes"]),
        })
    return sorted(rows, key=lambda r: (r["submodel"], r["component_id"], r["parameter_name"]))


def scalar_index(name: str, meaning: str) -> str:
    match = re.search(r"_(\d+)$", name or "") or re.match(r"\[(\d+)\]", meaning or "")
    return match.group(1) if match else "missing"


def scalar_variable_keys(variables: list[dict[str, str]]) -> list[dict[str, str]]:
    staged = []
    bases = []
    for row in variables:
        data_path = notes_value(row["notes"], "Data_Path")
        index = scalar_index(row["variable_name"], row["meaning"])
        base = (f"{row['component_id']}::{data_path}" if data_path != "missing" else
                f"{row['component_id']}::{row['amesim_variable_id']}::{row['variable_name']}")
        bases.append(base)
        staged.append((row, data_path, index, base))
    counts = Counter(bases)
    rows = []
    for row, data_path, index, base in staged:
        key = base
        if counts[base] > 1:
            key = f"{row['component_id']}::{row['amesim_variable_id']}::{row['variable_name']}::{index}"
        rows.append({
            "component_id": row["component_id"], "component_label": row["component_label"],
            "submodel": row["submodel"], "amesim_variable_id": row["amesim_variable_id"],
            "variable_name": row["variable_name"], "data_path": data_path,
            "scalar_index": index, "scalar_variable_key": key, "unit": row["unit"],
            "variable_type": row["variable_type"],
            "validation_priority": row["validation_priority"], "source": row["source"],
            "confidence": row["confidence"],
            "notes": "amesim_variable_id is a base/group identifier; scalar key preserves each scalar row.",
        })
    if len({r["scalar_variable_key"] for r in rows}) != len(rows):
        duplicates = Counter(r["scalar_variable_key"] for r in rows)
        raise ClosureError(f"Scalar variable keys remain duplicated: {[k for k,v in duplicates.items() if v>1][:5]}")
    return rows


def scalar_state_keys(states: list[dict[str, str]]) -> list[dict[str, str]]:
    staged = []
    bases = []
    for row in states:
        data_path = notes_value(row["notes"], "Data_Path")
        index = scalar_index(row["state_name"], row["state_name"])
        base = (f"{row['component_id']}::{data_path}" if data_path != "missing" else
                f"{row['component_id']}::{row['state_id']}::{row['state_name']}")
        bases.append(base)
        staged.append((row, data_path, index, base))
    counts = Counter(bases)
    rows = []
    for row, data_path, index, base in staged:
        key = base
        if counts[base] > 1:
            key = f"{row['component_id']}::{row['state_id']}::{row['state_name']}::{row['state_type']}::{index}"
        rows.append({
            "component_id": row["component_id"], "component_label": row["component_label"],
            "submodel": row["submodel"], "amesim_state_id": row["state_id"],
            "state_name": row["state_name"], "data_path": data_path,
            "scalar_index": index, "scalar_state_key": key,
            "state_type": row["state_type"], "unit": row["unit"],
            "source": row["source"], "confidence": row["confidence"],
            "notes": "Scalar state key separates scalar record identity from the AMESim state/base id.",
        })
    if len({r["scalar_state_key"] for r in rows}) != len(rows):
        duplicates = Counter(r["scalar_state_key"] for r in rows)
        raise ClosureError(f"Scalar state keys remain duplicated: {[k for k,v in duplicates.items() if v>1][:5]}")
    return rows


def rekey_channels(channels: list[dict[str, str]], scalar_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    lookup = {(r["component_id"], r["amesim_variable_id"], r["variable_name"]): r
              for r in scalar_rows}
    rows = []
    for old in channels:
        scalar = lookup[(old["component_id"], old["amesim_variable_id"], old["variable_name"])]
        key = scalar["scalar_variable_key"]
        rows.append({
            "old_channel_id": old["channel_id"], "new_channel_id": f"VCH::{key}",
            "scalar_variable_key": key, "component_id": old["component_id"],
            "component_label": old["component_label"], "submodel": old["submodel"],
            "variable_name": old["variable_name"], "unit": old["unit"],
            "old_priority": old["validation_priority"], "availability": old["availability"],
            "source": old["source"], "confidence": old["confidence"],
            "notes": "Re-keyed from the accepted R03-A2 candidate pool; old id retained.",
        })
    if len({r["new_channel_id"] for r in rows}) != len(rows):
        raise ClosureError("Re-keyed validation channel ids are not unique")
    return rows


BASELINE_SELECTION = (
    ("supply", "pressure", "hydraulic", "p1", "input_boundary", "R03-C_standalone", True,
     "Representative pump-adjacent supply-line pressure; exact network naming remains model-topology based."),
    ("return", "pressure", "tank01", "press", "input_boundary", "R03-C_standalone", True,
     "Tank/return boundary pressure."),
    ("pump", "flow", "pump01", "qout", "core_output", "R03-B_component", True,
     "Representative pump outlet flow."),
    ("pump", "speed", "pmover01", "speed", "input_boundary", "R03-B_component", True,
     "Pump drive speed boundary."),
    ("pump", "torque", "pump01", "torque", "energy_check", "R03-D_amesim_compare", False,
     "Pump shaft power diagnostic."),
    ("cylinder", "position", "actuator001", "xact", "core_output", "R03-B_component", True,
     "Representative HJ020 piston displacement."),
    ("cylinder", "pressure_A", "actuator001", "p1", "core_output", "R03-B_component", True,
     "Representative HJ020 port-1 chamber pressure; A naming is a validation convention only."),
    ("cylinder", "pressure_B", "actuator001", "p2", "core_output", "R03-B_component", True,
     "Representative HJ020 port-2 chamber pressure; B naming is a validation convention only."),
    ("cylinder", "force", "actuator001", "frod", "core_output", "R03-B_component", True,
     "Representative cylinder rod force."),
    ("cylinder", "leakage_flow", "actuator001", "qleak", "internal_diagnostic", "R03-D_amesim_compare", False,
     "Representative internal leakage diagnostic."),
    ("valve", "command", "dirvalve_6", "signal_input", "input_boundary", "R03-B_component", True,
     "SC_1 external signal command."),
    ("valve", "spool_position", "dirvalve_6", "frac_spool_position", "core_output", "R03-B_component", True,
     "SC_1 fractional spool position."),
    ("valve", "pressure_P", "dirvalve_6", "p_P", "core_output", "R03-D_amesim_compare", True,
     "SC_1 parent port P pressure; model exposes no unit metadata."),
    ("valve", "pressure_T", "dirvalve_6", "p_T", "core_output", "R03-D_amesim_compare", True,
     "SC_1 parent port T pressure; model exposes no unit metadata."),
    ("valve", "pressure_A", "dirvalve_6", "p_A", "core_output", "R03-D_amesim_compare", True,
     "SC_1 parent port A pressure; model exposes no unit metadata."),
    ("valve", "pressure_B", "dirvalve_6", "p_B", "core_output", "R03-D_amesim_compare", True,
     "SC_1 parent port B pressure; model exposes no unit metadata."),
    ("valve", "flow_P", "dirvalve_6", "q_P", "core_output", "R03-D_amesim_compare", True,
     "SC_1 parent port P flow; model exposes no unit metadata."),
    ("valve", "flow_T", "dirvalve_6", "q_T", "core_output", "R03-D_amesim_compare", True,
     "SC_1 parent port T flow; model exposes no unit metadata."),
    ("valve", "flow_A", "dirvalve_6", "q_A", "core_output", "R03-D_amesim_compare", True,
     "SC_1 parent port A flow; model exposes no unit metadata."),
    ("valve", "flow_B", "dirvalve_6", "q_B", "core_output", "R03-D_amesim_compare", True,
     "SC_1 parent port B flow; model exposes no unit metadata."),
    ("accumulator", "gas_pressure", "accumulator", "pgas", "core_output", "R03-B_component", True,
     "Representative accumulator gas pressure."),
    ("accumulator", "hydraulic_pressure", "accumulator", "pout", "core_output", "R03-B_component", True,
     "Representative accumulator hydraulic port pressure."),
    ("accumulator", "gas_volume", "accumulator", "gasvol", "internal_diagnostic", "R03-D_amesim_compare", False,
     "Accumulator gas-state diagnostic."),
    ("pressure_valve", "flow", "presscontrol01_1", "q1", "core_output", "R03-B_component", True,
     "Representative RV010 relief-valve flow."),
)


def baseline_channels(scalar_rows: list[dict[str, str]]) -> list[dict[str, object]]:
    lookup = {(r["component_id"], r["variable_name"]): r for r in scalar_rows}
    rows = []
    for index, (domain, quantity, component, variable, role, stage, required, reason) in enumerate(BASELINE_SELECTION, 1):
        scalar = lookup.get((component, variable))
        if scalar is None:
            raise ClosureError(f"Baseline channel unavailable: {component}/{variable}")
        rows.append({
            "baseline_channel_id": f"BVC-{index:03d}", "physical_domain": domain,
            "physical_quantity": quantity, "component_id": component,
            "component_label": scalar["component_label"], "submodel": scalar["submodel"],
            "scalar_variable_key": scalar["scalar_variable_key"],
            "variable_name": variable, "unit": scalar["unit"], "role": role,
            "validation_stage": stage, "required": str(required).lower(),
            "selection_reason": reason, "source": scalar["source"],
            "confidence": scalar["confidence"],
            "notes": "Frozen R03-A2.5 baseline channel; not a simulation result or accuracy claim.",
        })
    return rows


def valvedynamics_definition() -> list[dict[str, object]]:
    spe = INSTALLATION / "submodels" / "VALVEDYNAMICS0.spe"
    cfile = INSTALLATION / "submodels" / "VALVEDYNAMICS0.c"
    if not spe.exists() or not cfile.exists():
        raise ClosureError("Official VALVEDYNAMICS0.spe/.c evidence is missing")
    modes = (
        (1, "no (static)", "static clipped algebraic response with endstop/limit memory stores", 0,
         "false", "false", "false", "0", "2 integer stores declared"),
        (2, "1st order", "first-order valve dynamics", 1,
         "true", "false", "false", "1", "2 integer stores declared"),
        (3, "2nd order", "second-order valve dynamics", 2,
         "false", "true", "true", "2", "2 integer stores declared"),
    )
    rows = []
    for value, meaning, equation_mode, order, tau, wn, zeta, continuous, discrete in modes:
        rows.append({
            "submodel": "VALVEDYNAMICS0", "parameter_name": "spool dynamics",
            "parameter_value": "1", "enum_value": value, "enum_meaning": meaning,
            "active_equation_mode": equation_mode, "dynamic_order": order,
            "uses_time_constant": tau, "uses_natural_frequency": wn,
            "uses_damping_ratio": zeta, "continuous_state_expected": continuous,
            "discrete_state_expected": discrete,
            "source_file": f"{spe}; {cfile}",
            "source_location": ("SPE lines 74-109,116-139; C lines 75-83,98-131,"
                                "167-170,192-217"),
            "source": "amesim_spe+amesim_c", "confidence": "confirmed",
            "notes": ("Only enum_value=1 is active in all audited SC_1 instances. "
                      "No official source code has been copied into this table."),
        })
    return rows


def discrete_relevance() -> list[dict[str, str]]:
    specs = (
        ("VALVEDYNAMICS0", "limit/endstop integer stores; static-mode memory/event handling", "YES", "NO",
         "Official C declares DISC_LIMIT and DISC_ENDSTOPS; current mode 1 allocates no continuous state."),
        ("SC_1", "inherits VALVEDYNAMICS0 limit/endstop logic", "YES", "NO",
         "All 10 SC_1 instances use VALVEDYNAMICS0 mode 1; basic static codeization is not blocked."),
        ("HJ020", "endstop/contact or motion-regime event logic possible", "YES", "UNKNOWN",
         "Parameter/state metadata contains endstop terms; unnamed discrete-state ownership is not proven."),
        ("HJ0022", "endstop/contact and spring event logic possible", "YES", "UNKNOWN",
         "Parameter/state metadata contains endstop/spring terms; unnamed ownership is not proven."),
        ("HJ021", "endstop/contact event logic possible", "YES", "UNKNOWN",
         "Parameter/state metadata contains endstop terms; unnamed ownership is not proven."),
        ("RV010", "opening/closing and hysteresis regime logic possible", "YES", "UNKNOWN",
         "Valve hysteresis parameter exists; no per-discrete-state name is available."),
        ("RV011", "opening/closing and hysteresis regime logic possible", "YES", "UNKNOWN",
         "Official/source metadata indicates valve switching features; ownership is not proven."),
        ("HYDPRV0", "opening/closing and flow-regime logic possible", "YES", "UNKNOWN",
         "Pressure-control valve metadata inspected; no per-state mapping is available."),
        ("PV00022", "saturation/endstop or control-event logic possible", "YES", "UNKNOWN",
         "Model parameters/variables include limiter-style behavior; no names for discrete stores."),
        ("HL0000/HL0002/HL011/HL012", "flow-regime/event logic possible", "YES", "UNKNOWN",
         "Line models have explicit continuous pressure/flow states; the 57 unnamed discrete stores are not attributable."),
    )
    return [{"submodel": s, "possible_discrete_logic": logic, "evidence_found": found,
             "source": "amesim_c+amesim_spe+accepted_r03a2_metadata",
             "r03b_relevance": "Preserve feature flags and validate event regimes separately.",
             "blocking": blocking, "notes": notes}
            for s, logic, found, blocking, notes in specs]


def git_clean_for_mechanics() -> bool:
    result = subprocess.run(
        ["git", "diff", "--exit-code", "--", "src/steering_sim/mechanics", "configs/mechanics",
         "examples/run_mechanical_demo_interactive.py"], cwd=ROOT, capture_output=True, text=True)
    return result.returncode == 0


def valvedynamics_note() -> str:
    return """# R03-A2.5 VALVEDYNAMICS0 专项说明

## 结论

Simcenter AMESim 2021.1 的官方 `VALVEDYNAMICS0.spe` 将 `spool dynamics` 定义为三个枚举：`1 = no (static)`、`2 = 1st order`、`3 = 2nd order`。当前 10 个 SC_1 实例均保存为 `1`，因此当前激活的是静态（零阶）模式，不是一阶或二阶模式。

在值 1 下，`valve time constant`、`valve natural frequency` 和 `valve damping ratio` 均不参与激活模式。`.spe` 只在 `spooldyn == 2` 时显示 time constant，只在 `spooldyn == 3` 时显示 natural frequency 与 damping ratio；`.c` 的参数检查分支与此一致。

## 状态解释

官方 `.c` 使用 `cxv_size = spooldyn > 1`、`cxvder_size = spooldyn > 2`。因此值 1 不分配 fractional spool position 或 fractional spool velocity 连续状态，和模型 `.state` 中没有 VALVEDYNAMICS0 连续状态完全一致。它还声明两个整数存储 `DISC_LIMIT`、`DISC_ENDSTOPS`，用于限制/端止点相关记忆或事件处理；这解释了为什么静态模式仍可能涉及内部离散存储，但不能据此给 57 个全模型离散状态逐项命名。

## R03-B 边界

当前证据足以支持 R03-B 将本模型的 SC_1 阀芯响应按静态模式实现，并保留限幅/端止点事件的验证接口。若未来把 `spool dynamics` 改为 2 或 3，必须分别启用一阶 time-constant 或二阶 natural-frequency/damping 参数，并重新冻结状态与验证通道。

## 证据

- `E:\\Simcenter\\2021.1\\Amesim\\submodels\\VALVEDYNAMICS0.spe`：第 17–46、74–109、116–139 行。
- `E:\\Simcenter\\2021.1\\Amesim\\submodels\\VALVEDYNAMICS0.c`：第 40–43、75–83、98–131、167–170、192–217 行。
- A2 参数表：10 个 `VALVEDYNAMICS0` 实例的 `spool dynamics = 1`。

本说明只记录模式定义和参数激活关系，不实现任何液压方程。
"""


def closure_report(manifest: dict[str, object], resolutions: list[dict[str, object]],
                   key_params: list[dict[str, object]], variables: list[dict[str, str]],
                   states: list[dict[str, str]], rekeyed: list[dict[str, str]],
                   baseline: list[dict[str, object]]) -> str:
    ref_counts = Counter((str(r["reference_type"]), str(r["status"])) for r in resolutions)
    unresolved = [r for r in resolutions if r["status"] != "RESOLVED"]
    domains = Counter(str(r["physical_domain"]) for r in baseline)
    key_ready = defaultdict(list)
    for row in key_params:
        key_ready[str(row["submodel"])].append(str(row["resolution_status"]))
    ready_lines = [f"- {submodel}: {len(statuses)} 行，未解析 {sum(s not in {'DIRECT','DIRECT_RAW','RESOLVED'} for s in statuses)} 行，保留非数值 raw {sum(s=='DIRECT_RAW' for s in statuses)} 行。"
                   for submodel, statuses in sorted(key_ready.items())]
    unresolved_lines = [f"- {r['source_component_id']} / {r['parameter_name']}: {r['raw_reference']} ({r['status']})"
                        for r in unresolved] or ["- 无。"]
    return f"""# R03-A2.5 参数闭合、唯一标识修正与验证基准冻结报告

## 1. 任务边界

本轮只消费已验收的 R03-A1/R03-A2 表和只读官方 submodel 元数据，完成引用闭合、标量键修正、验证基准冻结和 VALVEDYNAMICS0 模式确认。未重扫结构，未覆盖 A1/A2 正式表，未编写液压机理方程。

## 2. 原模型完整性

- 路径：`{manifest['model']}`
- 开始/结束 SHA256：`{manifest['start']['sha256']}` / `{manifest['end']['sha256']}`
- 大小：{manifest['start']['size']} bytes
- mtime_ns：{manifest['start']['mtime_ns']}
- 是否修改：NO

## 3. Python 环境

`{manifest['python']}`

## 4. R03-A2 继承数据

输入为 A2 的 4334 行正式参数、369 行初值/状态、2371 行变量和 608 条 A/B 候选验证通道。A2 表保持不变。

## 5. global/local reference 解析方法

局部引用按模型级 `GLOBALPARAM` 名称解析；SC_1 全局引用按内部组件所属 parent 和 `USES_SC_GP` 规范名解析。链保留原始名称、目标、深度和完整路径。只允许数值、四则运算、幂、PI 和 sqrt 的受限表达式求值；循环和不支持表达式不会静默求值。

## 6. 关键参数解析结果

- global_reference：{sum(k[0]=='global_reference' for k in ref_counts.elements())} 行；RESOLVED={ref_counts[('global_reference','RESOLVED')]}。
- local_reference：{sum(k[0]=='local_reference' for k in ref_counts.elements())} 行；RESOLVED={ref_counts[('local_reference','RESOLVED')]}。
- R03-B 关键参数冻结行：{len(key_params)}。

""" + "\n".join(ready_lines) + f"""

## 7. unresolved references

""" + "\n".join(unresolved_lines) + f"""

## 8. scalar variable key 规则

优先使用 `component_id::Data_Path`；若 Data_Path 缺失或不唯一，则使用 `component_id::amesim_variable_id::variable_name::scalar_index`。原 base/group id 不删除。共 {len(variables)} 个标量变量键，重复 0。

## 9. scalar state key 规则

规则与 variable 相同，并在碰撞时加入 state_type。共 {len(states)} 个标量 state/initial-condition 键，重复 0。

## 10. channel re-key 结果

A2 的 {len(rekeyed)} 条候选通道全部保留 old_channel_id，并新增唯一 new_channel_id；重复 0。

## 11. baseline validation set

冻结 {len(baseline)} 条：""" + "，".join(f"{k}={v}" for k, v in sorted(domains.items())) + "。\n" + f"""
该集合覆盖供油、回油、泵、代表 HJ020、代表 SC_1、蓄能器和 RV010。SC_1 父接口单位缺失项继续写 `missing`，未按物理常识补单位。

## 12. 为什么选择这些通道

选择边界输入、组件核心输出、功率/泄漏诊断和可直接绑定的 AMESim scalar key。只取一个代表缸、一个代表阀、一个蓄能器和一个压力阀，避免重复实例淹没验收集合。

## 13. diagnostic pool 与 baseline 的区别

608 条 A/B 记录仍是 candidate pool；HL012 的大量 `pn_n/qn_n` 是 diagnostic pool。baseline 只含一个有明确供油代表意义的管路压力，不批量纳入内部节点。

## 14. VALVEDYNAMICS0 调查结果

官方 `.spe` 和 `.c` 已交叉确认枚举、参数可见性、状态尺寸和代码分支。未修改或编译安装文件。

## 15. spool dynamics=1 的含义

值 1=`no (static)`，dynamic order=0；time constant、natural frequency、damping ratio 均不参与当前模式。值 2 为一阶并使用 time constant；值 3 为二阶并使用 natural frequency 与 damping ratio。

## 16. 57 个离散状态是否阻塞 R03-B

不阻塞第一批静态 SC_1 和基础泵/缸组件代码化。VALVEDYNAMICS0 明确有两个整数 store（limit/endstops）；其他 HJ/RV/PV/line 的逐项归属仍 UNKNOWN，涉及端止点、滞环、切换或流态事件的高保真复现必须后续专项验证。

## 17. remaining missing / unknown

- SC_1 父接口 P/T/A/B 压力、流量单位元数据缺失，baseline 继续保留 `missing`。
- 57 个全模型离散状态没有逐项名称或 owner 映射。
- 代表 supply line 的物理命名基于现有拓扑证据；动态对比阶段应以 AMESim 导出通道再次 spot-check。

## 18. 是否可以进入 R03-B

建议 **YES WITH CONDITIONS**：可以从 PU001、HJ020/HJ0022/HJ021、HA001、RV010 和当前静态模式 SC_1 开始；必须保留单位缺失、离散事件归属和供油通道命名三项限制，且不能宣称已完成动态精度验证。
"""


def run(overwrite: bool = False) -> dict[str, object]:
    if Path(sys.executable).resolve() != EXPECTED_PYTHON.resolve():
        raise ClosureError(f"Wrong Python executable: {sys.executable}")
    existing = [name for name in OUTPUTS if (AUDIT / name).exists()]
    if existing and not overwrite:
        raise ClosureError(f"R03-A2.5 output exists; use --overwrite-r03a25: {existing}")
    start = file_identity(MODEL)
    if start["sha256"] != EXPECTED_SHA:
        raise ClosureError("Original qh1_1.ame SHA256 differs from accepted baseline")

    parameters = read_csv("hydraulic_parameters.csv")
    raw_parameters = read_csv("r03a2_raw_parameters.csv")
    variables = read_csv("hydraulic_variables.csv")
    states = read_csv("hydraulic_initial_states.csv")
    channels = read_csv("r03a2_validation_channels.csv")

    resolutions = resolve_references(parameters, raw_parameters)
    key_params = resolved_key_parameters(parameters, resolutions)
    scalar_variables = scalar_variable_keys(variables)
    scalar_states = scalar_state_keys(states)
    rekeyed = rekey_channels(channels, scalar_variables)
    baseline = baseline_channels(scalar_variables)
    definitions = valvedynamics_definition()
    discrete = discrete_relevance()

    write_csv(OUTPUTS[0], resolutions, list(resolutions[0]))
    write_csv(OUTPUTS[1], key_params, list(key_params[0]))
    write_csv(OUTPUTS[2], scalar_variables, list(scalar_variables[0]))
    write_csv(OUTPUTS[3], scalar_states, list(scalar_states[0]))
    write_csv(OUTPUTS[4], rekeyed, list(rekeyed[0]))
    write_csv(OUTPUTS[5], baseline, list(baseline[0]))
    write_csv(OUTPUTS[6], definitions, list(definitions[0]))
    write_csv(OUTPUTS[7], discrete, list(discrete[0]))
    (AUDIT / OUTPUTS[8]).write_text(valvedynamics_note(), encoding="utf-8")

    end = file_identity(MODEL)
    manifest: dict[str, object] = {
        "task": "R03-A2.5", "model": str(MODEL), "python": sys.executable,
        "start": start, "end": end, "original_unchanged": start == end,
        "mechanics_modified": not git_clean_for_mechanics(),
        "counts": {
            "resolutions": len(resolutions),
            "resolved": sum(r["status"] == "RESOLVED" for r in resolutions),
            "unresolved": sum(r["status"] != "RESOLVED" for r in resolutions),
            "key_parameters": len(key_params), "scalar_variables": len(scalar_variables),
            "scalar_states": len(scalar_states), "rekeyed_channels": len(rekeyed),
            "baseline_channels": len(baseline),
        },
        "outputs": list(OUTPUTS),
    }
    (AUDIT / OUTPUTS[9]).write_text(
        closure_report(manifest, resolutions, key_params, scalar_variables, scalar_states,
                       rekeyed, baseline), encoding="utf-8")
    (AUDIT / OUTPUTS[10]).write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
    if start != end:
        raise ClosureError("Original qh1_1.ame changed during R03-A2.5")
    if manifest["mechanics_modified"]:
        raise ClosureError("Mechanical frozen area has tracked differences")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overwrite-r03a25", action="store_true",
                        help="Explicitly replace only R03-A2.5 derivative outputs.")
    args = parser.parse_args()
    print(json.dumps(run(args.overwrite_r03a25), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
