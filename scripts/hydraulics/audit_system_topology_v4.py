from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path


ROOT = Path(r"E:\15_project")
AUDIT = ROOT / "hydraulic_audit"

EDGE_FILE = AUDIT / "08B_system_hydraulic_edges.csv"
JUNCTION_FILE = AUDIT / "08A_system_hydraulic_junctions.csv"

OUT = AUDIT / "08E_system_topology_sanity.md"


def read_csv(path):
    with path.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as f:
        return list(csv.DictReader(f))


edges = read_csv(EDGE_FILE)
junctions = read_csv(JUNCTION_FILE)

junction_map = {
    r["junction_id"]: r
    for r in junctions
}


# ============================================================
# 1. component -> port -> junction
# ============================================================

component_ports = defaultdict(lambda: defaultdict(list))

for r in edges:

    component_ports[
        r["component_alias"]
    ][
        r["canonical_junction"]
    ].append(
        r["component_port"]
    )


# ============================================================
# 2. 找同一 component 多个 port 落到同一 junction
# ============================================================

duplicates = []

for alias, junction_dict in sorted(component_ports.items()):

    for jid, ports in sorted(junction_dict.items()):

        unique_ports = sorted(
            set(ports),
            key=lambda x: int(x)
        )

        if len(unique_ports) > 1:

            duplicates.append({
                "alias": alias,
                "junction": jid,
                "ports": unique_ports,
            })


print("=" * 70)
print("SYSTEM TOPOLOGY V4 SANITY AUDIT")
print("=" * 70)

print(
    "COMPONENTS WITH HYDRAULIC EDGES =",
    len(component_ports)
)

print(
    "SAME-COMPONENT MULTI-PORT COLLAPSES =",
    len(duplicates)
)


print()
print("===== MULTI-PORT SAME-JUNCTION CASES =====")

for item in duplicates:

    print(
        item["alias"],
        "| ports =",
        item["ports"],
        "| junction =",
        item["junction"]
    )


# ============================================================
# 3. 对这些 junction 打印成员信息
# ============================================================

affected_junctions = sorted(
    set(
        x["junction"]
        for x in duplicates
    )
)


print()
print("===== AFFECTED JUNCTION DETAILS =====")

for jid in affected_junctions:

    info = junction_map.get(jid, {})

    print()
    print("JUNCTION =", jid)

    print(
        "  net_count =",
        info.get("net_count", "")
    )

    print(
        "  topology_node_count =",
        info.get("topology_node_count", "")
    )

    print(
        "  member_nets =",
        info.get("member_nets", "")
    )

    print(
        "  member_topology_nodes =",
        info.get("member_topology_nodes", "")
    )


# ============================================================
# 4. SHJ_008 专项检查
# ============================================================

print()
print("===== SHJ_008 FULL DETAILS =====")

info = junction_map.get("SHJ_008")

if info is None:

    print("SHJ_008 NOT FOUND")

else:

    print(
        "net_count =",
        info["net_count"]
    )

    print(
        "topology_node_count =",
        info["topology_node_count"]
    )

    print(
        "member_nets =",
        info["member_nets"]
    )

    print(
        "member_topology_nodes =",
        info["member_topology_nodes"]
    )

    print()
    print("CONNECTED COMPONENT PORTS:")

    for r in edges:

        if r["canonical_junction"] == "SHJ_008":

            print(
                " ",
                r["component_alias"],
                "port",
                r["component_port"],
                "|",
                r["candidate_bg_type"]
            )


# ============================================================
# 5. Actuator 双口检查
# ============================================================

print()
print("===== ACTUATOR PORT CHECK =====")

for alias, junction_dict in sorted(component_ports.items()):

    if "actuator" not in alias.lower():
        continue

    pairs = []

    for jid, ports in junction_dict.items():

        for p in sorted(
            set(ports),
            key=lambda x: int(x)
        ):
            pairs.append(
                (p, jid)
            )

    pairs.sort(
        key=lambda x: int(x[0])
    )

    print(
        alias,
        "->",
        pairs
    )


# ============================================================
# 6. Markdown 报告
# ============================================================

with OUT.open(
    "w",
    encoding="utf-8"
) as f:

    f.write(
        "# System Topology V4 Sanity Audit\n\n"
    )

    f.write(
        f"- Components with hydraulic edges: "
        f"{len(component_ports)}\n"
    )

    f.write(
        f"- Same-component multi-port collapse cases: "
        f"{len(duplicates)}\n\n"
    )

    f.write(
        "## Same-component multi-port cases\n\n"
    )

    if not duplicates:

        f.write("- None\n")

    else:

        for item in duplicates:

            f.write(
                f"- `{item['alias']}`: "
                f"ports {item['ports']} "
                f"→ `{item['junction']}`\n"
            )

    f.write(
        "\n## Affected junctions\n\n"
    )

    for jid in affected_junctions:

        info = junction_map.get(jid, {})

        f.write(
            f"### {jid}\n\n"
        )

        f.write(
            f"- net_count: "
            f"{info.get('net_count', '')}\n"
        )

        f.write(
            f"- topology_node_count: "
            f"{info.get('topology_node_count', '')}\n"
        )

        f.write(
            f"- member_nets: "
            f"{info.get('member_nets', '')}\n"
        )

        f.write(
            f"- member_topology_nodes: "
            f"{info.get('member_topology_nodes', '')}\n\n"
        )


print()
print("REPORT =", OUT)