from __future__ import annotations

import csv
from collections import defaultdict, deque
from pathlib import Path


ROOT = Path(r"E:\15_project")
AUDIT = ROOT / "hydraulic_audit"

CONNECTION_FILE = AUDIT / "02_connections_fullalias.csv"
EDGE_FILE = AUDIT / "08B_system_hydraulic_edges.csv"
JUNCTION_FILE = AUDIT / "08A_system_hydraulic_junctions.csv"
COMPONENT_FILE = AUDIT / "01_components.csv"


def read_csv(path):
    with path.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as f:
        return list(csv.DictReader(f))


def is_true(v):
    return str(v).strip().lower() == "true"


def is_top_level(alias):
    return "." not in alias


connections = read_csv(CONNECTION_FILE)
edges = read_csv(EDGE_FILE)
junctions = read_csv(JUNCTION_FILE)
components = read_csv(COMPONENT_FILE)

component_info = {
    r["alias"]: r
    for r in components
}

junction_info = {
    r["junction_id"]: r
    for r in junctions
}


# ============================================================
# 1. 找 component 中多个 port 落同一个 junction 的情况
# ============================================================

component_junction_ports = defaultdict(
    lambda: defaultdict(list)
)

component_port_net = defaultdict(dict)

for r in edges:

    alias = r["component_alias"]
    port = r["component_port"]
    jid = r["canonical_junction"]
    net = r["source_net"]

    component_junction_ports[
        alias
    ][
        jid
    ].append(port)

    component_port_net[
        alias
    ][
        port
    ] = net


cases = []

for alias, jd in component_junction_ports.items():

    for jid, ports in jd.items():

        ports = sorted(
            set(ports),
            key=lambda x: int(x)
        )

        if len(ports) > 1:

            cases.append(
                (alias, jid, ports)
            )


# ============================================================
# 2. 重建“顶层 net <-> 顶层 topology node”图
# ============================================================

graph = defaultdict(list)

for r in connections:

    s = r["source_alias"]
    t = r["target_alias"]

    s_line = is_true(r["source_is_line"])
    t_line = is_true(r["target_is_line"])

    # 只研究 system-level
    if not is_top_level(s):
        continue

    if not is_top_level(t):
        continue

    # component-line 中只有 hydrnode 作为拓扑桥
    if (
        not s_line
        and t_line
        and s.lower().startswith("hydrnode")
        and r["source_port_type"] == "hflow"
    ):
        graph[s].append(t)
        graph[t].append(s)

    elif (
        s_line
        and not t_line
        and t.lower().startswith("hydrnode")
        and r["target_port_type"] == "hflow"
    ):
        graph[s].append(t)
        graph[t].append(s)


# ============================================================
# 3. BFS
# ============================================================

def shortest_path(start, goal):

    q = deque([start])

    prev = {
        start: None
    }

    while q:

        cur = q.popleft()

        if cur == goal:
            break

        for nxt in graph.get(cur, []):

            if nxt in prev:
                continue

            prev[nxt] = cur
            q.append(nxt)

    if goal not in prev:
        return None

    path = []

    cur = goal

    while cur is not None:

        path.append(cur)
        cur = prev[cur]

    path.reverse()

    return path


# ============================================================
# 4. 输出
# ============================================================

print("=" * 76)
print("SYSTEM V4 SAME-JUNCTION PORT DIAGNOSTIC")
print("=" * 76)

print("CASES =", len(cases))


for alias, jid, ports in sorted(cases):

    print()
    print("=" * 76)
    print("COMPONENT =", alias)
    print("JUNCTION  =", jid)
    print("PORTS     =", ports)

    info = component_info.get(alias, {})

    print(
        "BASE      =",
        info.get("base_alias", "")
    )

    print(
        "SUBMODEL  =",
        info.get("submodel", "")
    )

    print(
        "LIBRARY   =",
        info.get("library", "")
    )

    print()

    port_nets = []

    for p in ports:

        net = component_port_net[
            alias
        ].get(p, "")

        port_nets.append(
            (p, net)
        )

        print(
            "PORT",
            p,
            "ORIGINAL NET =",
            net
        )


    # 两两检查
    for i in range(len(port_nets)):

        for j in range(i + 1, len(port_nets)):

            p1, n1 = port_nets[i]
            p2, n2 = port_nets[j]

            print()
            print(
                f"--- PATH port {p1} ({n1}) "
                f"-> port {p2} ({n2}) ---"
            )

            path = shortest_path(
                n1,
                n2
            )

            if path is None:

                print(
                    "NO TOP-LEVEL HYDRNODE-ONLY PATH FOUND"
                )

            else:

                print(
                    "PATH LENGTH =",
                    len(path)
                )

                for k, item in enumerate(path):

                    kind = (
                        "NODE"
                        if item.lower().startswith(
                            "hydrnode"
                        )
                        else "NET"
                    )

                    print(
                        f"{k:03d}",
                        kind.ljust(6),
                        item
                    )


# ============================================================
# 5. SHJ_003 / SHJ_008 额外打印
# ============================================================

for target in [
    "SHJ_003",
    "SHJ_008"
]:

    print()
    print("=" * 76)
    print("JUNCTION DETAIL =", target)

    ji = junction_info.get(
        target,
        {}
    )

    print(
        "NET COUNT =",
        ji.get("net_count", "")
    )

    print(
        "NODE COUNT =",
        ji.get(
            "topology_node_count",
            ""
        )
    )

    print(
        "MEMBER NETS =",
        ji.get(
            "member_nets",
            ""
        )
    )

    print(
        "MEMBER NODES =",
        ji.get(
            "member_topology_nodes",
            ""
        )
    )