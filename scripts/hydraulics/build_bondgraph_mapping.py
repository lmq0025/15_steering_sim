"""
Amesim -> Bond Graph 第一阶段自动映射

输入：
    hydraulic_audit/01_components.csv
    hydraulic_audit/02_connections_fullalias.csv

输出：
    hydraulic_audit/06A_bondgraph_component_candidates.csv
    hydraulic_audit/06B_bondgraph_net_candidates.csv
    hydraulic_audit/06C_bondgraph_mapping_summary.md

说明：
1. 本脚本不调用 Amesim，不占用 Amesim license。
2. 当前输出为“Bond Graph 候选映射”，不是最终物理模型。
3. 对 TF / MTF / R / MR / C / I / Se / Sf / 0 / 1 junction
   的最终判定仍需结合元件方程和参数验证。
"""

from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path


# ============================================================
# 0. 路径
# ============================================================

PROJECT_ROOT = Path(r"E:\15_project")
AUDIT_DIR = PROJECT_ROOT / "hydraulic_audit"

COMPONENT_FILE = AUDIT_DIR / "01_components.csv"
CONNECTION_FILE = AUDIT_DIR / "02_connections_fullalias.csv"

COMPONENT_OUTPUT = (
    AUDIT_DIR / "06A_bondgraph_component_candidates.csv"
)

NET_OUTPUT = (
    AUDIT_DIR / "06B_bondgraph_net_candidates.csv"
)

SUMMARY_OUTPUT = (
    AUDIT_DIR / "06C_bondgraph_mapping_summary.md"
)


# ============================================================
# 1. 工具函数
# ============================================================

def read_csv(path: Path):
    with path.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as f:
        return list(csv.DictReader(f))


def to_bool(value):
    return str(value).strip().lower() == "true"


def parent_alias(alias: str) -> str:
    """
    dirvalve_1.orifice_13 -> dirvalve_1
    pump01                -> ""
    """
    if "." in alias:
        return alias.split(".", 1)[0]

    return ""


def leaf_alias(alias: str) -> str:
    """
    dirvalve_1.orifice_13 -> orifice_13
    """
    if "." in alias:
        return alias.split(".", 1)[1]

    return alias


def normalized(text: str) -> str:
    return str(text or "").strip().lower()


# ============================================================
# 2. 根据名称 + 物理域生成 Bond Graph 候选
# ============================================================

def classify_component(
    alias: str,
    domains: set[str],
    base_alias: str = "",
    submodel: str = "",
    library: str = "",
):
    """
    返回：
        bg_type
        physical_role
        confidence
        reason
        review_required
    """

    name = normalized(alias)
    leaf = normalized(leaf_alias(alias))
    base = normalized(base_alias)
    sub = normalized(submodel)

    search_text = " ".join(
        [
            name,
            leaf,
            base,
            sub,
            normalized(library),
        ]
    )

    combo = "+".join(sorted(domains))

    # --------------------------------------------------------
    # A. 信号域
    # --------------------------------------------------------

    if domains == {"signal"}:

        return (
            "SIGNAL",
            "information/control element",
            "high",
            "Only signal-domain ports detected; "
            "not treated as a power bond element.",
            "no",
        )

    # --------------------------------------------------------
    # B. 泵 / 液压马达类
    # hydraulic <-> rotational mechanical
    # --------------------------------------------------------

    if domains == {"hflow", "rshaft"}:

        if "pump" in search_text:
            return (
                "TF/MTF",
                "hydraulic-rotational energy converter (pump)",
                "high",
                "Component couples hydraulic flow/pressure "
                "and rotational shaft torque/speed.",
                "yes",
            )

        if "motor" in search_text:
            return (
                "TF/MTF",
                "hydraulic-rotational energy converter (motor)",
                "high",
                "Component couples hydraulic and rotational "
                "mechanical power domains.",
                "yes",
            )

        return (
            "TF/MTF",
            "hydraulic-rotational energy converter",
            "medium",
            "Detected simultaneous hflow and rshaft ports.",
            "yes",
        )

    # --------------------------------------------------------
    # C. 液压缸 / 执行器
    # hydraulic <-> translational mechanical
    # --------------------------------------------------------

    if domains == {"hflow", "lshaft"}:

        return (
            "TF/MTF",
            "hydraulic-linear mechanical converter",
            "high",
            "Component couples hydraulic flow/pressure "
            "and translational force/velocity domains.",
            "yes",
        )

    # --------------------------------------------------------
    # D. 受控液压阻性元件
    # --------------------------------------------------------

    if domains == {"hflow", "signal"}:

        if (
            "dirvalve" in search_text
            or "valve" in search_text
        ):
            return (
                "MR / COMPOSITE",
                "signal-modulated hydraulic valve",
                "high",
                "Hydraulic power ports plus signal port; "
                "model as modulated resistance or "
                "internal valve Bond Graph submodel.",
                "yes",
            )

        if "orifice" in search_text:
            return (
                "MR",
                "signal-modulated hydraulic restriction",
                "high",
                "Variable orifice controlled by signal.",
                "yes",
            )

        return (
            "MR / COMPOSITE",
            "signal-controlled hydraulic element",
            "medium",
            "Simultaneous hydraulic and signal domains detected.",
            "yes",
        )

    # --------------------------------------------------------
    # E. 线性机械 + 信号
    # --------------------------------------------------------

    if domains == {"lshaft", "signal"}:

        return (
            "DETECTOR / MSe / MSf candidate",
            "linear mechanical-signal interface",
            "medium",
            "Component couples translational mechanical "
            "and signal domains; function must be checked "
            "from submodel equations.",
            "yes",
        )

    # --------------------------------------------------------
    # F. 纯液压元件
    # --------------------------------------------------------

    if domains == {"hflow"}:

        # 内部方向阀孔口
        if "orifice" in search_text:
            return (
                "R/MR",
                "hydraulic restriction/orifice",
                "high",
                "Orifice dissipates hydraulic energy; "
                "if opening is controlled, use MR.",
                "yes",
            )

        # 节点类
        if (
            "node" in search_text
            or "hydrnode" in search_text
        ):
            return (
                "0-JUNCTION candidate",
                "common hydraulic pressure node",
                "high",
                "Hydraulic node represents common pressure "
                "with flow conservation.",
                "yes",
            )

        # 油箱
        if "tank" in search_text:
            return (
                "Se/C candidate",
                "hydraulic reservoir/compliance",
                "medium",
                "Tank may behave as pressure source or "
                "hydraulic compliance depending on submodel.",
                "yes",
            )

        # 流阻类
        if any(
            k in search_text
            for k in [
                "filter",
                "cooler",
                "restrict",
                "checkvalve",
                "check_valve",
                "flowcontrol",
                "presscontrol",
                "relief",
                "valve",
            ]
        ):
            return (
                "R/MR",
                "hydraulic dissipative element",
                "medium",
                "Component is likely governed by "
                "pressure-drop / flow relation.",
                "yes",
            )

        return (
            "HYDRAULIC_ELEMENT",
            "unclassified hydraulic component",
            "low",
            "Only hydraulic ports detected; constitutive "
            "equation is required for final classification.",
            "yes",
        )

    # --------------------------------------------------------
    # G. 纯旋转机械域
    # --------------------------------------------------------

    if domains == {"rshaft"}:

        if (
            "pmover" in search_text
            or "source" in search_text
        ):
            return (
                "Se/Sf candidate",
                "rotational mechanical source",
                "medium",
                "Prime mover/source-like component in "
                "rotational mechanical domain.",
                "yes",
            )

        if (
            "inertia" in search_text
            or "mass" in search_text
        ):
            return (
                "I",
                "rotational inertia",
                "medium",
                "Rotational energy storage candidate.",
                "yes",
            )

        return (
            "ROT_MECH_ELEMENT",
            "rotational mechanical element",
            "low",
            "Pure rotational mechanical domain.",
            "yes",
        )

    # --------------------------------------------------------
    # H. 纯平移机械域
    # --------------------------------------------------------

    if domains == {"lshaft"}:

        if (
            "mass" in search_text
            or "inertia" in search_text
        ):
            return (
                "I",
                "translational inertia",
                "medium",
                "Linear mechanical energy-storage candidate.",
                "yes",
            )

        if "spring" in search_text:
            return (
                "C",
                "mechanical compliance",
                "medium",
                "Spring-like translational mechanical element.",
                "yes",
            )

        if (
            "damper" in search_text
            or "friction" in search_text
        ):
            return (
                "R",
                "mechanical dissipation",
                "medium",
                "Damping/friction-like element.",
                "yes",
            )

        return (
            "LIN_MECH_ELEMENT",
            "translational mechanical element",
            "low",
            "Pure linear mechanical domain.",
            "yes",
        )

    # --------------------------------------------------------
    # I. 没有识别到 power domain
    # --------------------------------------------------------

    if not domains:

        return (
            "UNRESOLVED",
            "unresolved/internal object",
            "low",
            "No explicit port domain detected.",
            "yes",
        )

    # --------------------------------------------------------
    # J. 其他多域组合
    # --------------------------------------------------------

    return (
        "COMPOSITE",
        f"multi-domain component ({combo})",
        "low",
        "Multiple physical domains detected; "
        "manual constitutive-equation review required.",
        "yes",
    )


# ============================================================
# 3. 读取已有元件档案
# ============================================================

component_info = {}

for row in read_csv(COMPONENT_FILE):

    component_info[row["alias"]] = row


# ============================================================
# 4. 从 fullalias 连接表重新构造组件域
#
# 注意：
# 不再依赖旧的 02C 表。
# 因为 fullalias 修正之后，应以修正连接表为唯一拓扑真源。
# ============================================================

connections = read_csv(CONNECTION_FILE)

component_domains = defaultdict(set)
component_port_count = Counter()

net_endpoints = defaultdict(list)


for row in connections:

    source = row["source_alias"]
    target = row["target_alias"]

    source_is_line = to_bool(row["source_is_line"])
    target_is_line = to_bool(row["target_is_line"])

    source_type = row["source_port_type"].strip()
    target_type = row["target_port_type"].strip()

    # --------------------------------------------------------
    # component -> line
    # --------------------------------------------------------

    if not source_is_line and target_is_line:

        if source_type:
            component_domains[source].add(source_type)

        component_port_count[source] += 1

        net_endpoints[target].append(
            {
                "component": source,
                "component_port": row["source_port"],
                "domain": (
                    target_type
                    or source_type
                ),
            }
        )

    # --------------------------------------------------------
    # line -> component
    # --------------------------------------------------------

    elif source_is_line and not target_is_line:

        if target_type:
            component_domains[target].add(target_type)

        component_port_count[target] += 1

        net_endpoints[source].append(
            {
                "component": target,
                "component_port": row["target_port"],
                "domain": (
                    source_type
                    or target_type
                ),
            }
        )

    # --------------------------------------------------------
    # component -> component
    #
    # Amesim supercomponent 内部可能存在直接连接，
    # 这种情况不经过 line。
    # --------------------------------------------------------

    elif not source_is_line and not target_is_line:

        if source_type:
            component_domains[source].add(source_type)

        if target_type:
            component_domains[target].add(target_type)

        component_port_count[source] += 1
        component_port_count[target] += 1


# ============================================================
# 5. 输出组件 Bond Graph 候选表
# ============================================================

all_component_aliases = sorted(
    set(component_domains)
    | set(component_info)
)


component_rows = []


for alias in all_component_aliases:

    domains = component_domains.get(alias, set())

    # 如果是超级元件内部对象，优先尝试读取父级元件资料
    info = component_info.get(alias)

    parent = parent_alias(alias)

    if info is None and parent:
        parent_info = component_info.get(parent, {})
    else:
        parent_info = {}

    info = info or {}

    base_alias = (
        info.get("base_alias", "")
        or parent_info.get("base_alias", "")
    )

    submodel = (
        info.get("submodel", "")
        or parent_info.get("submodel", "")
    )

    library = (
        info.get("library", "")
        or parent_info.get("library", "")
    )

    bg_type, role, confidence, reason, review = (
        classify_component(
            alias=alias,
            domains=domains,
            base_alias=base_alias,
            submodel=submodel,
            library=library,
        )
    )

    component_rows.append(
        {
            "alias": alias,
            "parent_alias": parent,
            "is_internal": "yes" if parent else "no",
            "base_alias": base_alias,
            "submodel": submodel,
            "library": library,
            "connected_port_count":
                component_port_count.get(alias, 0),
            "domain_combo":
                "+".join(sorted(domains)),
            "candidate_bg_type": bg_type,
            "physical_role": role,
            "confidence": confidence,
            "review_required": review,
            "reason": reason,
        }
    )


component_fields = [
    "alias",
    "parent_alias",
    "is_internal",
    "base_alias",
    "submodel",
    "library",
    "connected_port_count",
    "domain_combo",
    "candidate_bg_type",
    "physical_role",
    "confidence",
    "review_required",
    "reason",
]


with COMPONENT_OUTPUT.open(
    "w",
    encoding="utf-8-sig",
    newline=""
) as f:

    writer = csv.DictWriter(
        f,
        fieldnames=component_fields
    )

    writer.writeheader()
    writer.writerows(component_rows)


# ============================================================
# 6. Net -> junction 候选
# ============================================================

net_rows = []


for net_alias, endpoints in sorted(net_endpoints.items()):

    domains = sorted(
        set(
            e["domain"]
            for e in endpoints
            if e["domain"]
        )
    )

    domain = (
        domains[0]
        if len(domains) == 1
        else "+".join(domains)
    )

    degree = len(endpoints)

    # --------------------------------------------------------
    # Hydraulic net
    # --------------------------------------------------------

    if domain == "hflow":

        bg_type = "0-JUNCTION candidate"

        role = (
            "common hydraulic pressure node / "
            "flow conservation"
        )

        confidence = "high"

        review = "yes"

    # --------------------------------------------------------
    # Rotational mechanical net
    # --------------------------------------------------------

    elif domain == "rshaft":

        bg_type = "0/1-JUNCTION candidate"

        role = (
            "rotational mechanical connection"
        )

        confidence = "medium"

        review = "yes"

    # --------------------------------------------------------
    # Translational mechanical net
    # --------------------------------------------------------

    elif domain == "lshaft":

        bg_type = "0/1-JUNCTION candidate"

        role = (
            "translational mechanical connection"
        )

        confidence = "medium"

        review = "yes"

    # --------------------------------------------------------
    # Signal net
    # --------------------------------------------------------

    elif domain == "signal":

        bg_type = "SIGNAL"

        role = (
            "information/control connection"
        )

        confidence = "high"

        review = "no"

    else:

        bg_type = "UNRESOLVED_NET"

        role = "unresolved network"

        confidence = "low"

        review = "yes"

    connected_aliases = "; ".join(
        e["component"]
        for e in endpoints
    )

    net_rows.append(
        {
            "net_alias": net_alias,
            "degree": degree,
            "domain": domain,
            "candidate_bg_type": bg_type,
            "physical_role": role,
            "confidence": confidence,
            "review_required": review,
            "connected_aliases": connected_aliases,
        }
    )


net_fields = [
    "net_alias",
    "degree",
    "domain",
    "candidate_bg_type",
    "physical_role",
    "confidence",
    "review_required",
    "connected_aliases",
]


with NET_OUTPUT.open(
    "w",
    encoding="utf-8-sig",
    newline=""
) as f:

    writer = csv.DictWriter(
        f,
        fieldnames=net_fields
    )

    writer.writeheader()
    writer.writerows(net_rows)


# ============================================================
# 7. 生成 Markdown 审计摘要
# ============================================================

component_type_count = Counter(
    row["candidate_bg_type"]
    for row in component_rows
)

domain_count = Counter(
    row["domain_combo"]
    for row in component_rows
)

net_domain_count = Counter(
    row["domain"]
    for row in net_rows
)

low_confidence = [
    row
    for row in component_rows
    if row["confidence"] == "low"
]

internal_objects = [
    row
    for row in component_rows
    if row["is_internal"] == "yes"
]


with SUMMARY_OUTPUT.open(
    "w",
    encoding="utf-8"
) as f:

    f.write(
        "# Amesim → Bond Graph 初始映射审计\n\n"
    )

    f.write(
        "本文件由 "
        "`scripts/hydraulics/"
        "build_bondgraph_mapping.py` "
        "自动生成。\n\n"
    )

    f.write(
        "> 注意：当前结果是候选映射，"
        "不是最终 Bond Graph。"
        "最终分类必须结合元件方程、参数和因果关系确认。\n\n"
    )

    f.write("## 1. 总体统计\n\n")

    f.write(
        f"- Component objects: "
        f"{len(component_rows)}\n"
    )

    f.write(
        f"- Internal objects: "
        f"{len(internal_objects)}\n"
    )

    f.write(
        f"- Nets: "
        f"{len(net_rows)}\n"
    )

    f.write(
        f"- Low-confidence components: "
        f"{len(low_confidence)}\n\n"
    )

    f.write(
        "## 2. Component Bond Graph 候选类型\n\n"
    )

    for key, value in sorted(
        component_type_count.items(),
        key=lambda x: (-x[1], x[0])
    ):

        f.write(
            f"- `{key}`: {value}\n"
        )

    f.write(
        "\n## 3. Component 物理域组合\n\n"
    )

    for key, value in sorted(
        domain_count.items(),
        key=lambda x: (-x[1], x[0])
    ):

        f.write(
            f"- `{key or 'EMPTY'}`: {value}\n"
        )

    f.write(
        "\n## 4. Net 物理域\n\n"
    )

    for key, value in sorted(
        net_domain_count.items(),
        key=lambda x: (-x[1], x[0])
    ):

        f.write(
            f"- `{key or 'EMPTY'}`: {value}\n"
        )

    f.write(
        "\n## 5. 低置信度、需要人工复核的元件\n\n"
    )

    for row in low_confidence[:100]:

        f.write(
            f"- `{row['alias']}`: "
            f"{row['domain_combo']} → "
            f"{row['candidate_bg_type']}\n"
        )


# ============================================================
# 8. 控制台输出
# ============================================================

print("=" * 60)
print("Amesim -> Bond Graph candidate mapping complete")
print("=" * 60)

print(
    "COMPONENT OBJECTS =",
    len(component_rows)
)

print(
    "NET OBJECTS =",
    len(net_rows)
)

print(
    "INTERNAL OBJECTS =",
    len(internal_objects)
)

print(
    "LOW CONFIDENCE =",
    len(low_confidence)
)

print()

print(
    "COMPONENT OUTPUT =",
    COMPONENT_OUTPUT
)

print(
    "NET OUTPUT =",
    NET_OUTPUT
)

print(
    "SUMMARY OUTPUT =",
    SUMMARY_OUTPUT
)

print()

print(
    "IMPORTANT: These are candidate mappings, "
    "not final Bond Graph assignments."
)