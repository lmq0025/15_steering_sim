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

JUNCTION_OUT = AUDIT / "07A_canonical_hydraulic_junctions.csv"
EDGE_OUT = AUDIT / "07B_normalized_hydraulic_edges.csv"
MAP_OUT = AUDIT / "07C_topology_node_to_junction.csv"
REPORT_OUT = AUDIT / "07D_bondgraph_topology_normalization.md"


def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def is_true(v):
    return str(v).strip().lower() == "true"


# ============================================================
# 1. 读取数据
# ============================================================

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
# 2. 找出“纯液压拓扑节点”
#
# 判据：
# - domain_combo == hflow
# - candidate_bg_type == 0-JUNCTION candidate
# - 无参数
# - 无 state variable
# ============================================================

topology_nodes = set()

rejected_topology_nodes = []


for alias, info in component_map.items():

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
    else:
        rejected_topology_nodes.append(
            (
                alias,
                len(ps),
                len(state_vars),
            )
        )


# ============================================================
# 3. 找出 hydraulic line/net
# ============================================================

hydraulic_nets = set()

for r in connections:

    if (
        is_true(r["source_is_line"])
        and r["source_port_type"] == "hflow"
    ):
        hydraulic_nets.add(r["source_alias"])

    if (
        is_true(r["target_is_line"])
        and r["target_port_type"] == "hflow"
    ):
        hydraulic_nets.add(r["target_alias"])


# ============================================================
# 4. Union-Find
#
# topology node 连通的 hydraulic nets
# 应折叠为同一个 canonical 0-junction
# ============================================================

parent = {n: n for n in hydraulic_nets}


def find(x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


def union(a, b):
    ra = find(a)
    rb = find(b)

    if ra != rb:
        parent[rb] = ra


# topology node -> connected hydraulic nets
node_nets = defaultdict(set)


for r in connections:

    s = r["source_alias"]
    t = r["target_alias"]

    s_line = is_true(r["source_is_line"])
    t_line = is_true(r["target_is_line"])

    # topology node -> hydraulic line
    if (
        s in topology_nodes
        and t_line
        and t in hydraulic_nets
    ):
        node_nets[s].add(t)

    # hydraulic line -> topology node
    if (
        t in topology_nodes
        and s_line
        and s in hydraulic_nets
    ):
        node_nets[t].add(s)


# 所有通过 topology node 相连的 nets 做 union
for node, nets in node_nets.items():

    nets = sorted(nets)

    if len(nets) < 2:
        continue

    first = nets[0]

    for other in nets[1:]:
        union(first, other)


# ============================================================
# 5. 构造 canonical junction groups
# ============================================================

groups = defaultdict(set)

for net in hydraulic_nets:
    groups[find(net)].add(net)


# 确保 root 压缩
normalized_groups = defaultdict(set)

for net in hydraulic_nets:
    normalized_groups[find(net)].add(net)

groups = normalized_groups


# 每个 topology node 属于哪个 group
node_group_root = {}

for node, nets in node_nets.items():

    if not nets:
        continue

    roots = {find(n) for n in nets}

    if len(roots) == 1:
        node_group_root[node] = next(iter(roots))
    else:
        # 理论上 union 后不应该发生
        node_group_root[node] = sorted(roots)[0]


# 给 canonical junction 编号
sorted_roots = sorted(
    groups,
    key=lambda r: sorted(groups[r])[0]
)

junction_id = {
    root: f"HJ_{i:03d}"
    for i, root in enumerate(sorted_roots, start=1)
}


# ============================================================
# 6. 收集每个 canonical junction 的成员
# ============================================================

junction_nodes = defaultdict(set)

for node, root in node_group_root.items():
    junction_nodes[root].add(node)


junction_rows = []

for root in sorted_roots:

    jid = junction_id[root]

    nets = sorted(groups[root])
    nodes = sorted(junction_nodes.get(root, set()))

    junction_rows.append({
        "junction_id": jid,
        "domain": "hydraulic",
        "bg_type": "0-JUNCTION",
        "net_count": len(nets),
        "topology_node_count": len(nodes),
        "member_nets": "; ".join(nets),
        "member_topology_nodes": "; ".join(nodes),
    })


# ============================================================
# 7. topology node -> canonical junction 映射
# ============================================================

map_rows = []

for node in sorted(topology_nodes):

    root = node_group_root.get(node)

    if root is None:
        jid = ""
    else:
        jid = junction_id[root]

    map_rows.append({
        "amesim_topology_node": node,
        "canonical_junction": jid,
        "parameter_count": len(param_map.get(node, [])),
        "variable_count": len(var_map.get(node, [])),
        "state_variable_count": len([
            v for v in var_map.get(node, [])
            if "state" in v.get("basic_type", "").lower()
        ]),
    })


# ============================================================
# 8. 非拓扑 hydraulic component -> canonical junction
# ============================================================

edge_seen = set()
edge_rows = []


for r in connections:

    s = r["source_alias"]
    t = r["target_alias"]

    s_line = is_true(r["source_is_line"])
    t_line = is_true(r["target_is_line"])

    component = None
    component_port = None
    net = None

    # component -> hydraulic net
    if (
        not s_line
        and t_line
        and t in hydraulic_nets
        and r["source_port_type"] == "hflow"
    ):
        component = s
        component_port = r["source_port"]
        net = t

    # hydraulic net -> component
    elif (
        s_line
        and not t_line
        and s in hydraulic_nets
        and r["target_port_type"] == "hflow"
    ):
        component = t
        component_port = r["target_port"]
        net = s

    else:
        continue

    # 纯 topology node 不再作为 power element 输出
    if component in topology_nodes:
        continue

    root = find(net)
    jid = junction_id[root]

    key = (
        component,
        component_port,
        jid,
    )

    if key in edge_seen:
        continue

    edge_seen.add(key)

    info = component_map.get(component, {})

    edge_rows.append({
        "component_alias": component,
        "component_port": component_port,
        "domain": "hydraulic",
        "canonical_junction": jid,
        "candidate_bg_type":
            info.get("candidate_bg_type", ""),
        "physical_role":
            info.get("physical_role", ""),
        "confidence":
            info.get("confidence", ""),
        "source_net": net,
    })


# ============================================================
# 9. 写文件
# ============================================================

with JUNCTION_OUT.open(
    "w",
    encoding="utf-8-sig",
    newline=""
) as f:

    fields = [
        "junction_id",
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
        "domain",
        "canonical_junction",
        "candidate_bg_type",
        "physical_role",
        "confidence",
        "source_net",
    ]

    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    w.writerows(edge_rows)


with MAP_OUT.open(
    "w",
    encoding="utf-8-sig",
    newline=""
) as f:

    fields = [
        "amesim_topology_node",
        "canonical_junction",
        "parameter_count",
        "variable_count",
        "state_variable_count",
    ]

    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    w.writerows(map_rows)


# ============================================================
# 10. 报告
# ============================================================

junction_size_counter = Counter(
    len(groups[root])
    for root in groups
)

with REPORT_OUT.open(
    "w",
    encoding="utf-8"
) as f:

    f.write("# Bond Graph Topology Normalization V3\n\n")

    f.write(
        f"- Hydraulic line/net objects: "
        f"{len(hydraulic_nets)}\n"
    )

    f.write(
        f"- Verified pure topology nodes: "
        f"{len(topology_nodes)}\n"
    )

    f.write(
        f"- Rejected topology nodes: "
        f"{len(rejected_topology_nodes)}\n"
    )

    f.write(
        f"- Canonical hydraulic 0-junctions: "
        f"{len(junction_rows)}\n"
    )

    f.write(
        f"- Normalized hydraulic component edges: "
        f"{len(edge_rows)}\n\n"
    )

    f.write("## Junction net-count distribution\n\n")

    for size, count in sorted(junction_size_counter.items()):
        f.write(
            f"- {size} original net(s): {count}\n"
        )

    f.write(
        "\n## Rejected topology-node candidates\n\n"
    )

    if not rejected_topology_nodes:
        f.write("- None\n")
    else:
        for alias, pc, sc in rejected_topology_nodes:
            f.write(
                f"- `{alias}`: "
                f"parameters={pc}, states={sc}\n"
            )


# ============================================================
# 11. 控制台
# ============================================================

print("=" * 60)
print("Bond Graph topology normalization V3 complete")
print("=" * 60)

print("HYDRAULIC NETS =", len(hydraulic_nets))
print("TOPOLOGY NODES =", len(topology_nodes))
print(
    "REJECTED TOPOLOGY NODES =",
    len(rejected_topology_nodes)
)
print(
    "CANONICAL 0-JUNCTIONS =",
    len(junction_rows)
)
print(
    "NORMALIZED HYDRAULIC EDGES =",
    len(edge_rows)
)

print()
print("JUNCTION OUTPUT =", JUNCTION_OUT)
print("EDGE OUTPUT =", EDGE_OUT)
print("NODE MAP OUTPUT =", MAP_OUT)
print("REPORT =", REPORT_OUT)