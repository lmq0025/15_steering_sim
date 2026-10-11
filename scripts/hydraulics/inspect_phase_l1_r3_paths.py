from __future__ import annotations

from pathlib import Path

import pandas as pd


ROOT = Path(r"E:\15_project")


def main() -> None:
    ports = pd.read_csv(ROOT / "hydraulic_audit" / "17B_bondgraph_ports_v3.csv")
    ports = ports[(ports["domain"] == "hydraulic") & ports["element_id"].str.startswith("L1_")]
    graph: dict[str, set[str]] = {}
    for row in ports.itertuples():
        left, right = str(row.element_id), str(row.connected_junction)
        graph.setdefault(left, set()).add(right)
        graph.setdefault(right, set()).add(left)
    pairs = [
        ("L1_dirvalve_1", "L1_actuator001"),
        ("L1_dirvalve_2", "L1_actuator001"),
        ("L1_dirvalve_8", "L1_actuator001_1"),
        ("L1_dirvalve_9", "L1_actuator001_1"),
        ("L1_dirvalve_11", "L1_actuator001_2"),
        ("L1_dirvalve_12", "L1_actuator001_2"),
        ("L1_dirvalve_6", "L1_actuator002"),
    ]
    for left, right in pairs:
        print(f"\n{left} -> {right}")
        queue: list[list[str]] = [[left]]
        found: list[list[str]] = []
        while queue and len(found) < 5:
            path = queue.pop(0)
            if path[-1] == right:
                found.append(path)
                continue
            for neighbor in sorted(graph.get(path[-1], ())):
                if neighbor not in path and len(path) < 18:
                    queue.append(path + [neighbor])
        for index, path in enumerate(found):
            print(" -> ".join(path))


if __name__ == "__main__":
    main()
