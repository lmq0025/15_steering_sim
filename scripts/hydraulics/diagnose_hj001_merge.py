from __future__ import annotations

import csv
from collections import defaultdict, deque
from pathlib import Path


ROOT = Path(r"E:\15_project")
AUDIT = ROOT / "hydraulic_audit"

CONNECTION_FILE = AUDIT / "02_connections_fullalias.csv"
COMPONENT_FILE = AUDIT / "06A_bondgraph_component_candidates_v2.csv"
PARAM_FILE = AUDIT / "04_parameters.csv"
VARIABLE_FILE = AUDIT / "05_variables.csv"


def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def is_true(v):
    return str(v).strip().lower() == "true"


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


# ------------------------------------------------------------
# 1. 重建 V3 使用过的 topology node 集合
# ------------------------------------------------------------

topology_nodes = set()

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


# ------------------------------------------------------------
# 2. hydraulic nets
# ------------------------------------------------------------

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


# ------------------------------------------------------------
# 3. 构造二部图
#
# net <-> topology node
#
# 只允许 topology node 作为桥梁
# ------------------------------------------------------------

graph = defaultdict(list)

for r in connections:

    s = r["source_alias"]
    t = r["target_alias"]

    s_line = is_true(r["source_is_line"])
    t_line = is_true(r["target_is_line"])

    # topology node -> hydraulic net
    if (
        s in topology_nodes
        and t_line
        and t in hydraulic_nets
    ):
        graph[s].append(t)
        graph[t].append(s)

    # hydraulic net -> topology node
    if (
        t in topology_nodes
        and s_line
        and s in hydraulic_nets
    ):
        graph[t].append(s)
        graph[s].append(t)


# ------------------------------------------------------------
# 4. 查 pump01 两端
# ------------------------------------------------------------

start = "hydraulic_12"
goal = "hydraulic"

print("=" * 70)
print("SEARCH WRONG MERGE PATH")
print("=" * 70)

print("START =", start)
print("GOAL  =", goal)

if start not in graph:
    print("START NOT IN GRAPH")

if goal not in graph:
    print("GOAL NOT IN GRAPH")


# ------------------------------------------------------------
# 5. BFS
# ------------------------------------------------------------

queue = deque([start])

previous = {
    start: None
}

while queue:

    current = queue.popleft()

    if current == goal:
        break

    for nxt in graph[current]:

        if nxt in previous:
            continue

        previous[nxt] = current
        queue.append(nxt)


if goal not in previous:

    print()
    print("NO TOPOLOGY-ONLY PATH FOUND")
    raise SystemExit(0)


# ------------------------------------------------------------
# 6. 回溯路径
# ------------------------------------------------------------

path = []

cur = goal

while cur is not None:

    path.append(cur)
    cur = previous[cur]

path.reverse()


print()
print("PATH LENGTH =", len(path))
print()

print("===== WRONG MERGE PATH =====")

for i, item in enumerate(path):

    kind = (
        "NET"
        if item in hydraulic_nets
        else "TOPOLOGY_NODE"
    )

    print(
        f"{i:03d}",
        kind.ljust(15),
        item
    )


# ------------------------------------------------------------
# 7. 对路径中的 topology node 输出详细信息
# ------------------------------------------------------------

print()
print("===== TOPOLOGY NODE DETAILS =====")

for item in path:

    if item not in topology_nodes:
        continue

    info = component_map.get(item, {})

    print()
    print("NODE =", item)

    print(
        "  parent_alias =",
        info.get("parent_alias", "")
    )

    print(
        "  base_alias =",
        info.get("base_alias", "")
    )

    print(
        "  submodel =",
        info.get("submodel", "")
    )

    print(
        "  candidate_bg_type =",
        info.get("candidate_bg_type", "")
    )

    print(
        "  connected nets =",
        graph[item]
    )