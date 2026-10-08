from __future__ import annotations

import csv
from pathlib import Path
from collections import defaultdict


ROOT = Path(r"E:\15_project")
AUDIT = ROOT / "hydraulic_audit"

COMPONENT_FILE = AUDIT / "01_components.csv"
GLOBAL_PARAM_FILE = AUDIT / "03_global_parameters.csv"
PARAM_FILE = AUDIT / "04_parameters.csv"
VARIABLE_FILE = AUDIT / "05_variables.csv"
EDGE_FILE = AUDIT / "08B_system_hydraulic_edges.csv"

CSV_OUT = AUDIT / "09A_pump_constitutive_evidence.csv"
REPORT_OUT = AUDIT / "09B_pump_constitutive_evidence.md"


def read_csv(path: Path):
    with path.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as f:
        return list(csv.DictReader(f))


def safe(v):
    return "" if v is None else str(v)


# ============================================================
# 1. 读取数据
# ============================================================

components = read_csv(COMPONENT_FILE)
global_params = read_csv(GLOBAL_PARAM_FILE)
params = read_csv(PARAM_FILE)
variables = read_csv(VARIABLE_FILE)
edges = read_csv(EDGE_FILE)


component_map = {
    r["alias"]: r
    for r in components
}

global_map = {}

for r in global_params:

    # 兼容不同字段命名
    name = (
        r.get("name")
        or r.get("parameter")
        or r.get("alias")
        or r.get("data_path")
        or ""
    )

    value = (
        r.get("value")
        or r.get("raw_value")
        or r.get("resolved_value")
        or ""
    )

    unit = (
        r.get("unit")
        or r.get("value_unit")
        or ""
    )

    if name:
        global_map[name] = {
            "value": value,
            "unit": unit,
            "raw": r,
        }


param_map = defaultdict(list)
var_map = defaultdict(list)
edge_map = defaultdict(list)

for r in params:
    param_map[r["alias"]].append(r)

for r in variables:
    var_map[r["alias"]].append(r)

for r in edges:
    edge_map[r["component_alias"]].append(r)


# ============================================================
# 2. 找 pump01 系列
# ============================================================

pump_aliases = sorted(
    alias
    for alias in component_map
    if alias == "pump01"
    or alias.startswith("pump01_")
)


print("=" * 72)
print("PUMP CONSTITUTIVE EVIDENCE EXTRACTION")
print("=" * 72)

print("PUMP COUNT =", len(pump_aliases))
print("PUMPS =", pump_aliases)


# ============================================================
# 3. 输出 CSV 记录
# ============================================================

rows = []


for alias in pump_aliases:

    info = component_map.get(alias, {})

    submodel = info.get("submodel", "")
    library = info.get("library", "")
    base_alias = info.get("base_alias", "")

    # --------------------------------------------------------
    # 参数
    # --------------------------------------------------------

    for p in param_map.get(alias, []):

        raw_value = safe(
            p.get("raw_value", "")
        )

        resolved_value = safe(
            p.get("resolved_value", "")
        )

        value_unit = safe(
            p.get("value_unit", "")
        )

        # 如果 raw_value 是全局参数名，则尝试追踪
        global_ref_name = ""
        global_ref_value = ""
        global_ref_unit = ""

        if raw_value in global_map:

            global_ref_name = raw_value
            global_ref_value = safe(
                global_map[raw_value]["value"]
            )
            global_ref_unit = safe(
                global_map[raw_value]["unit"]
            )

        rows.append({
            "pump_alias": alias,
            "record_type": "parameter",
            "base_alias": base_alias,
            "submodel": submodel,
            "library": library,
            "data_path": safe(
                p.get("data_path", "")
            ),
            "name_or_title": safe(
                p.get("title", "")
            ),
            "parameter_or_variable_type": safe(
                p.get("parameter_type", "")
            ),
            "basic_type": "",
            "io_type": "",
            "unit": safe(
                p.get("unit", "")
            ),
            "raw_value": raw_value,
            "resolved_value": resolved_value,
            "value_unit": value_unit,
            "global_reference": global_ref_name,
            "global_reference_value": global_ref_value,
            "global_reference_unit": global_ref_unit,
            "system_junction": "",
            "component_port": "",
        })

    # --------------------------------------------------------
    # 变量
    # --------------------------------------------------------

    for v in var_map.get(alias, []):

        rows.append({
            "pump_alias": alias,
            "record_type": "variable",
            "base_alias": base_alias,
            "submodel": submodel,
            "library": library,
            "data_path": safe(
                v.get("data_path", "")
            ),
            "name_or_title": safe(
                v.get("title", "")
            ),
            "parameter_or_variable_type": safe(
                v.get("variable_type", "")
            ),
            "basic_type": safe(
                v.get("basic_type", "")
            ),
            "io_type": safe(
                v.get("io_type", "")
            ),
            "unit": safe(
                v.get("unit", "")
            ),
            "raw_value": "",
            "resolved_value": "",
            "value_unit": "",
            "global_reference": "",
            "global_reference_value": "",
            "global_reference_unit": "",
            "system_junction": "",
            "component_port": "",
        })

    # --------------------------------------------------------
    # 系统级液压端口
    # --------------------------------------------------------

    for e in edge_map.get(alias, []):

        rows.append({
            "pump_alias": alias,
            "record_type": "hydraulic_connection",
            "base_alias": base_alias,
            "submodel": submodel,
            "library": library,
            "data_path": "",
            "name_or_title": "system hydraulic connection",
            "parameter_or_variable_type": "",
            "basic_type": "",
            "io_type": "",
            "unit": "",
            "raw_value": "",
            "resolved_value": "",
            "value_unit": "",
            "global_reference": "",
            "global_reference_value": "",
            "global_reference_unit": "",
            "system_junction": safe(
                e.get("canonical_junction", "")
            ),
            "component_port": safe(
                e.get("component_port", "")
            ),
        })


fields = [
    "pump_alias",
    "record_type",
    "base_alias",
    "submodel",
    "library",
    "data_path",
    "name_or_title",
    "parameter_or_variable_type",
    "basic_type",
    "io_type",
    "unit",
    "raw_value",
    "resolved_value",
    "value_unit",
    "global_reference",
    "global_reference_value",
    "global_reference_unit",
    "system_junction",
    "component_port",
]


with CSV_OUT.open(
    "w",
    encoding="utf-8-sig",
    newline=""
) as f:

    writer = csv.DictWriter(
        f,
        fieldnames=fields
    )

    writer.writeheader()
    writer.writerows(rows)


# ============================================================
# 4. 生成 Markdown 证据报告
# ============================================================

with REPORT_OUT.open(
    "w",
    encoding="utf-8"
) as f:

    f.write(
        "# Pump PU001 Constitutive Evidence\n\n"
    )

    f.write(
        "本报告只整理 Amesim 审计数据中已经存在的证据，"
        "不额外假设 PU001 的最终本构方程。\n\n"
    )

    f.write(
        f"- Pump instances: {len(pump_aliases)}\n\n"
    )

    for alias in pump_aliases:

        info = component_map.get(alias, {})

        f.write(
            f"## {alias}\n\n"
        )

        f.write(
            f"- base_alias: `{info.get('base_alias', '')}`\n"
        )

        f.write(
            f"- submodel: `{info.get('submodel', '')}`\n"
        )

        f.write(
            f"- library: `{info.get('library', '')}`\n\n"
        )

        # ----------------------------------------------------
        # 参数
        # ----------------------------------------------------

        f.write("### Parameters\n\n")

        pump_params = param_map.get(alias, [])

        if not pump_params:

            f.write("- None\n\n")

        else:

            for p in pump_params:

                raw = safe(
                    p.get("raw_value", "")
                )

                resolved = safe(
                    p.get("resolved_value", "")
                )

                f.write(
                    f"- `{p.get('data_path', '')}`\n"
                )

                f.write(
                    f"  - title: {p.get('title', '')}\n"
                )

                f.write(
                    f"  - unit: {p.get('unit', '')}\n"
                )

                f.write(
                    f"  - raw_value: `{raw}`\n"
                )

                f.write(
                    f"  - resolved_value: `{resolved}`\n"
                )

                if raw in global_map:

                    f.write(
                        f"  - global_reference: `{raw}`\n"
                    )

                    f.write(
                        f"  - global_value: "
                        f"`{global_map[raw]['value']}`\n"
                    )

                f.write("\n")

        # ----------------------------------------------------
        # 变量
        # ----------------------------------------------------

        f.write("### Variables\n\n")

        pump_vars = var_map.get(alias, [])

        if not pump_vars:

            f.write("- None\n\n")

        else:

            for v in pump_vars:

                f.write(
                    f"- `{v.get('data_path', '')}`\n"
                )

                f.write(
                    f"  - title: {v.get('title', '')}\n"
                )

                f.write(
                    f"  - unit: {v.get('unit', '')}\n"
                )

                f.write(
                    f"  - basic_type: "
                    f"`{v.get('basic_type', '')}`\n"
                )

                f.write(
                    f"  - io_type: "
                    f"`{v.get('io_type', '')}`\n"
                )

                f.write("\n")

        # ----------------------------------------------------
        # 状态变量
        # ----------------------------------------------------

        state_vars = [
            v for v in pump_vars
            if "state" in
            safe(
                v.get("basic_type", "")
            ).lower()
        ]

        f.write("### State variables\n\n")

        if not state_vars:

            f.write(
                "- No explicit state variables detected.\n\n"
            )

        else:

            for v in state_vars:

                f.write(
                    f"- `{v.get('data_path', '')}` "
                    f"({v.get('title', '')})\n"
                )

            f.write("\n")

        # ----------------------------------------------------
        # 液压端口
        # ----------------------------------------------------

        f.write(
            "### System-level hydraulic connections\n\n"
        )

        pump_edges = edge_map.get(alias, [])

        if not pump_edges:

            f.write("- None\n\n")

        else:

            for e in sorted(
                pump_edges,
                key=lambda x: int(
                    x.get("component_port", "0")
                )
            ):

                f.write(
                    f"- port `{e.get('component_port', '')}` "
                    f"→ `{e.get('canonical_junction', '')}` "
                    f"(source net "
                    f"`{e.get('source_net', '')}`)\n"
                )

            f.write("\n")

        # ----------------------------------------------------
        # 自动物理提示
        # ----------------------------------------------------

        f.write(
            "### Preliminary Bond Graph interpretation\n\n"
        )

        f.write(
            "- Hydraulic effort candidate: pressure `p`\n"
        )

        f.write(
            "- Hydraulic flow candidate: volume flow `q`\n"
        )

        f.write(
            "- Rotational effort candidate: torque `T`\n"
        )

        f.write(
            "- Rotational flow candidate: angular speed `ω`\n"
        )

        f.write(
            "- Current candidate element: `TF/MTF`\n"
        )

        f.write(
            "- Final constitutive relation: TODO, "
            "must be confirmed from PU001 equations/behavior.\n\n"
        )


# ============================================================
# 5. 控制台摘要
# ============================================================

print()
print("===== PUMP SUMMARY =====")

for alias in pump_aliases:

    info = component_map.get(alias, {})

    pump_params = param_map.get(alias, [])
    pump_vars = var_map.get(alias, [])

    state_vars = [
        v for v in pump_vars
        if "state" in
        safe(
            v.get("basic_type", "")
        ).lower()
    ]

    print()
    print("PUMP =", alias)
    print(
        "SUBMODEL =",
        info.get("submodel", "")
    )
    print(
        "PARAMETERS =",
        len(pump_params)
    )
    print(
        "VARIABLES =",
        len(pump_vars)
    )
    print(
        "STATE VARIABLES =",
        len(state_vars)
    )

    for p in pump_params:

        print(
            " PARAM:",
            p.get("data_path", ""),
            "|",
            p.get("title", ""),
            "| unit =",
            p.get("unit", ""),
            "| raw =",
            p.get("raw_value", ""),
            "| resolved =",
            p.get("resolved_value", "")
        )

    for v in pump_vars:

        print(
            " VAR:",
            v.get("data_path", ""),
            "|",
            v.get("title", ""),
            "| unit =",
            v.get("unit", ""),
            "| basic_type =",
            v.get("basic_type", ""),
            "| io_type =",
            v.get("io_type", "")
        )

    for e in sorted(
        edge_map.get(alias, []),
        key=lambda x: int(
            x.get("component_port", "0")
        )
    ):

        print(
            " HYD PORT:",
            e.get("component_port", ""),
            "->",
            e.get("canonical_junction", ""),
            "| net =",
            e.get("source_net", "")
        )


print()
print("=" * 72)
print("EXTRACTION COMPLETE")
print("=" * 72)

print("CSV =", CSV_OUT)
print("REPORT =", REPORT_OUT)
