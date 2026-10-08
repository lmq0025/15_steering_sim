from __future__ import annotations

import csv
from collections import defaultdict, Counter
from pathlib import Path


ROOT = Path(r"E:\15_project")
AUDIT = ROOT / "hydraulic_audit"

CONNECTION_FILE = AUDIT / "02_connections_fullalias.csv"
COMPONENT_FILE = AUDIT / "06A_bondgraph_component_candidates_v2.csv"
PARAM_FILE = AUDIT / "04_parameters.csv"
VARIABLE_FILE = AUDIT / "05_variables.csv"

JUNCTION_OUT = AUDIT / "08A_system_hydraulic_junctions.csv"
EDGE_OUT = AUDIT / "08B_system_hydraulic_edges.csv"
NODE_MAP_OUT = AUDIT / "08C_system_node_to_junction.csv"
REPORT_OUT = AUDIT / "08D_system_bondgraph_topology_v4.md"


def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def is_true(v):
    return str(v).strip().lower() == "true"


def is_top_level(alias):
    return "." not in alias


connections = read_csv(CONNECTION_FILE)
components = read_csv(COMPONENT_FILE)
params = read_csv(PARAM_FILE)
variables = read_csv(VARIABLE_FILE)

component_map = {
    r["alias"]: r
    for r in components
}

param_map = defaultdict(list)
var_map = defaultdict(list)

for r in params:
    param_map[r["alias"]].append(r)

for r in variables:
    var_map[r["alias"]].append(r)


# ============================================================
# 1. 只保留顶层液压 topology nodes
# ============================================================

topology_nodes = set()

for alias, info in component_map.items():

    # V4 核心：系统级只接受顶层 alias
    if not is_top_level(alias):
        continue

    if info["domain_combo"] != "hflow":
        continue

    if info["candidate_bg_type"] != "0-JUNCTION candidate":
        continue

    ps = param_map.get(alias, [])
    vs = var_map.get(alias, [])

    state_vars = [
        v for v in vs
        if "state" in v.get("basic_type", "").lower()
    ]

    if len(ps) == 0 and len(state_vars) == 0:
        topology_nodes.add(alias)


# ============================================================
# 2. 只保留顶层 hydraulic nets
# ============================================================

hydraulic_nets = set()

for r in connections:

    s = r["source_alias"]
    t = r["target_alias"]

    if (
        is_true(r["source_is_line"])
        and r["source_port_type"] == "hflow"
        and is_top_level(s)
    ):
        hydraulic_nets.add(s)

    if (
        is_true(r["target_is_line"])
        and r["target_port_type"] == "hflow"
        and is_top_level(t)
    ):
        hydraulic_nets.add(t)


# ============================================================
# 3. Union-Find
# 只允许：
#
# top-level hydraulic net
#      ↕
# top-level topology node
#
# 绝对不允许通过 dirvalve_x.xxx 等内部节点跨层合并
# ============================================================

parent = {
    net: net
    for net in hydraulic_nets
}


def find(x):
    if parent[x] != x:
        parent[x] = find(parent[x])
    return parent[x]


def union(a, b):

    ra = find(a)
    rb = find(b)

    if ra != rb:
        parent[rb] = ra


node_nets = defaultdict(set)


for r in connections:

    s = r["source_alias"]
    t = r["target_alias"]

    s_line = is_true(r["source_is_line"])
    t_line = is_true(r["target_is_line"])

    # 顶层 topology node -> 顶层 net
    if (
        s in topology_nodes
        and t_line
        and t in hydraulic_nets
    ):
        node_nets[s].add(t)

    # 顶层 net -> 顶层 topology node
    if (
        t in topology_nodes
        and s_line
        and s in hydraulic_nets
    ):
        node_nets[t].add(s)


for node, nets in node_nets.items():

    nets = sorted(nets)

    if len(nets) <= 1:
        continue

    first = nets[0]

    for other in nets[1:]:
        union(first, other)


# ============================================================
# 4. Canonical system-level junctions
# ============================================================

groups = defaultdict(set)

for net in hydraulic_nets:
    groups[find(net)].add(net)


node_group = {}

for node, nets in node_nets.items():

    roots = {
        find(net)
        for net in nets
    }

    if len(roots) == 1:
        node_group[node] = next(iter(roots))


sorted_roots = sorted(
    groups.keys(),
    key=lambda root: sorted(groups[root])[0]
)


junction_id = {
    root: f"SHJ_{i:03d}"
    for i, root in enumerate(sorted_roots, start=1)
}


junction_nodes = defaultdict(set)

for node, root in node_group.items():
    junction_nodes[root].add(node)


junction_rows = []

for root in sorted_roots:

    junction_rows.append({
        "junction_id": junction_id[root],
        "level": "system",
        "domain": "hydraulic",
        "bg_type": "0-JUNCTION",
        "net_count": len(groups[root]),
        "topology_node_count":
            len(junction_nodes.get(root, set())),
        "member_nets":
            "; ".join(sorted(groups[root])),
        "member_topology_nodes":
            "; ".join(
                sorted(junction_nodes.get(root, set()))
            ),
    })


# ============================================================
# 5. 系统级组件 -> canonical junction
#
# 只保留顶层 component。
# dirvalve_1 可以保留；
# dirvalve_1.orifice_13 不允许进入系统级图。
# ============================================================

edges = []
seen = set()


for r in connections:

    s = r["source_alias"]
    t = r["target_alias"]

    s_line = is_true(r["source_is_line"])
    t_line = is_true(r["target_is_line"])

    component = None
    component_port = None
    net = None

    if (
        not s_line
        and t_line
        and is_top_level(s)
        and t in hydraulic_nets
        and r["source_port_type"] == "hflow"
    ):
        component = s
        component_port = r["source_port"]
        net = t

    elif (
        s_line
        and not t_line
        and is_top_level(t)
        and s in hydraulic_nets
        and r["target_port_type"] == "hflow"
    ):
        component = t
        component_port = r["target_port"]
        net = s

    else:
        continue

    # 顶层 topology nodes 已吸收到 junction，不再作为元件
    if component in topology_nodes:
        continue

    root = find(net)
    jid = junction_id[root]

    key = (
        component,
        component_port,
        jid,
    )

    if key in seen:
        continue

    seen.add(key)

    info = component_map.get(component, {})

    edges.append({
        "component_alias": component,
        "component_port": component_port,
        "canonical_junction": jid,
        "domain": "hydraulic",
        "candidate_bg_type":
            info.get("candidate_bg_type", ""),
        "physical_role":
            info.get("physical_role", ""),
        "confidence":
            info.get("confidence", ""),
        "source_net": net,
    })


# ============================================================
# 6. Node map
# ============================================================

node_rows = []

for node in sorted(topology_nodes):

    root = node_group.get(node)

    node_rows.append({
        "amesim_topology_node": node,
        "canonical_junction":
            junction_id[root] if root else "",
        "level": "system",
        "parameter_count":
            len(param_map.get(node, [])),
        "state_variable_count":
            len([
                v for v in var_map.get(node, [])
                if "state" in
                v.get("basic_type", "").lower()
            ]),
    })


# ============================================================
# 7. 写 CSV
# ============================================================

with JUNCTION_OUT.open(
    "w",
    encoding="utf-8-sig",
    newline=""
) as f:

    fields = [
        "junction_id",
        "level",
        "domain",
        "bg_type",
        "net_count",
        "topology_node_count",
        "member_nets",
        "member_topology_nodes",
    ]

    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    w.writerows(junction_rows)


with EDGE_OUT.open(
    "w",
    encoding="utf-8-sig",
    newline=""
) as f:

    fields = [
        "component_alias",
        "component_port",
        "canonical_junction",
        "domain",
        "candidate_bg_type",
        "physical_role",
        "confidence",
        "source_net",
    ]

    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    w.writerows(edges)


with NODE_MAP_OUT.open(
    "w",
    encoding="utf-8-sig",
    newline=""
) as f:

    fields = [
        "amesim_topology_node",
        "canonical_junction",
        "level",
        "parameter_count",
        "state_variable_count",
    ]

    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    w.writerows(node_rows)


# ============================================================
# 8. 强制物理 sanity checks
# ============================================================

pump_ports = defaultdict(dict)

for e in edges:

    alias = e["component_alias"]

    if alias.startswith("pump01"):
        pump_ports[alias][e["component_port"]] = (
            e["canonical_junction"]
        )


pump_same_junction_errors = []

for alias, ports in pump_ports.items():

    junctions = list(ports.values())

    if len(junctions) >= 2:

        if len(set(junctions)) < len(junctions):
            pump_same_junction_errors.append(
                (alias, ports)
            )


# ============================================================
# 9. 报告
# ============================================================

size_counter = Counter(
    len(nets)
    for nets in groups.values()
)


with REPORT_OUT.open(
    "w",
    encoding="utf-8"
) as f:

    f.write(
        "# System-Level Bond Graph Topology V4\n\n"
    )

    f.write(
        "本版本只使用顶层 Amesim alias，"
        "supercomponent 内部 alias 被明确排除。\n\n"
    )

    f.write(
        f"- Top-level hydraulic nets: "
        f"{len(hydraulic_nets)}\n"
    )

    f.write(
        f"- Top-level pure topology nodes: "
        f"{len(topology_nodes)}\n"
    )

    f.write(
        f"- Canonical system hydraulic junctions: "
        f"{len(junction_rows)}\n"
    )

    f.write(
        f"- System hydraulic component edges: "
        f"{len(edges)}\n"
    )

    f.write(
        f"- Pump same-junction errors: "
        f"{len(pump_same_junction_errors)}\n\n"
    )

    f.write(
        "## Junction original-net distribution\n\n"
    )

    for size, count in sorted(size_counter.items()):
        f.write(
            f"- {size} net(s): {count}\n"
        )

    f.write(
        "\n## Pump port sanity check\n\n"
    )

    for alias, ports in sorted(pump_ports.items()):
        f.write(
            f"- `{alias}`: {ports}\n"
        )

    if pump_same_junction_errors:

        f.write(
            "\n## ERROR: pump ports collapsed\n\n"
        )

        for alias, ports in pump_same_junction_errors:
            f.write(
                f"- `{alias}`: {ports}\n"
            )

    else:

        f.write(
            "\n- PASS: no pump hydraulic ports "
            "were collapsed onto the same canonical junction.\n"
        )


print("=" * 60)
print("System-level Bond Graph topology V4 complete")
print("=" * 60)

print(
    "TOP-LEVEL HYDRAULIC NETS =",
    len(hydraulic_nets)
)

print(
    "TOP-LEVEL TOPOLOGY NODES =",
    len(topology_nodes)
)

print(
    "SYSTEM CANONICAL 0-JUNCTIONS =",
    len(junction_rows)
)

print(
    "SYSTEM HYDRAULIC EDGES =",
    len(edges)
)

print(
    "PUMP SAME-JUNCTION ERRORS =",
    len(pump_same_junction_errors)
)

print()
print("JUNCTION OUTPUT =", JUNCTION_OUT)
print("EDGE OUTPUT =", EDGE_OUT)
print("REPORT =", REPORT_OUT)