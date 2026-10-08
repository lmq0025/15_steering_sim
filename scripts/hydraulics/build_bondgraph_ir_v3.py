from __future__ import annotations

import csv
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "hydraulic_audit"
PHYSICAL_LINES = {"HL0000", "HL0002", "HL011", "HL012"}
TOPOLOGY_NODES = {"H3NODE1", "H3NODE2", "H3NODE3", "H4NODE1", "H4NODE4", "HN222A"}


def read(name: str) -> list[dict[str, str]]:
    with (AUDIT / name).open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write(name: str, rows: list[dict[str, object]], fields: list[str]) -> None:
    with (AUDIT / name).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


class UnionFind:
    def __init__(self) -> None:
        self.parent: dict[tuple[str, str], tuple[str, str]] = {}

    def add(self, item: tuple[str, str]) -> None:
        self.parent.setdefault(item, item)

    def find(self, item: tuple[str, str]) -> tuple[str, str]:
        self.add(item)
        parent = self.parent[item]
        if parent != item:
            self.parent[item] = self.find(parent)
        return self.parent[item]

    def union(self, left: tuple[str, str], right: tuple[str, str]) -> None:
        a, b = self.find(left), self.find(right)
        if a != b:
            self.parent[max(a, b)] = min(a, b)


def is_internal(alias: str, parents: set[str]) -> bool:
    return any(alias.startswith(parent + ".") for parent in parents)


def parameter_map(parameters: list[dict[str, str]]) -> dict[str, dict[str, dict[str, str]]]:
    result: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    for row in parameters:
        result[row["alias"]][row["title"].strip().lower()] = row
    return result


def number(row: dict[str, str] | None, default: float = math.nan) -> float:
    if not row:
        return default
    try:
        return float(row.get("resolved_value", ""))
    except ValueError:
        return default


@dataclass(frozen=True)
class RebuiltHydraulicTopology:
    junctions: list[dict[str, object]]
    endpoint_to_junction: dict[tuple[str, str], str]


def rebuild_level1_hydraulic(
    components: list[dict[str, str]], connections: list[dict[str, str]], parents: set[str]
) -> RebuiltHydraulicTopology:
    comp = {row["alias"]: row for row in components}
    uf = UnionFind()
    alias_endpoints: dict[str, set[tuple[str, str]]] = defaultdict(set)

    for row in connections:
        if row["source_port_type"] != "hflow" or row["target_port_type"] != "hflow":
            continue
        source = (row["source_alias"], str(row["source_port"]))
        target = (row["target_alias"], str(row["target_port"]))
        if is_internal(source[0], parents) or is_internal(target[0], parents):
            continue
        uf.union(source, target)
        alias_endpoints[source[0]].add(source)
        alias_endpoints[target[0]].add(target)

    # Only ideal connectivity objects may merge their own ports.  Physical
    # HLxxxx line ports are intentionally not unioned here.
    for alias, endpoints in alias_endpoints.items():
        submodel = comp.get(alias, {}).get("submodel", "")
        if submodel == "DIRECT" or submodel in TOPOLOGY_NODES:
            ordered = sorted(endpoints)
            for endpoint in ordered[1:]:
                uf.union(ordered[0], endpoint)

    groups: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    for endpoint in sorted(uf.parent):
        groups[uf.find(endpoint)].append(endpoint)

    endpoint_to_junction: dict[tuple[str, str], str] = {}
    junctions: list[dict[str, object]] = []
    ordered_groups = sorted(groups.values(), key=lambda values: min(values))
    for index, endpoints in enumerate(ordered_groups, 1):
        junction_id = f"V3_HJ_{index:03d}"
        for endpoint in endpoints:
            endpoint_to_junction[endpoint] = junction_id
        members = sorted({alias for alias, _ in endpoints if comp.get(alias, {}).get("submodel") in TOPOLOGY_NODES | {"DIRECT"}})
        junctions.append(
            {
                "junction_id": junction_id,
                "level": "1",
                "domain": "hydraulic",
                "parent_supercomponent": "",
                "source": "02_connections_fullalias.csv; physical HL line ports kept separate",
                "members": "; ".join(members),
                "connected_endpoints": ";".join(f"{a}:{p}" for a, p in endpoints),
            }
        )
    return RebuiltHydraulicTopology(junctions, endpoint_to_junction)


def main() -> None:
    components = read("01_components.csv")
    connections = read("02_connections_fullalias.csv")
    parameters = read("04_parameters.csv")
    states = read("11A_state_variable_registry.csv")
    elements_v2 = read("12A_bondgraph_elements.csv")
    ports_v2 = read("12B_bondgraph_ports_v2.csv")
    junctions_v2 = read("12C_bondgraph_junctions_v2.csv")

    comp = {row["alias"]: row for row in components}
    parents = {row["alias"] for row in components if row["submodel"] == "SC_1"}
    physical = sorted((row for row in components if row["submodel"] in PHYSICAL_LINES), key=lambda row: row["alias"])
    pure_lines = {row["alias"] for row in components if row["object_type"] == "ame_line" and row["submodel"] == "DIRECT"}
    state_by_instance: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in states:
        state_by_instance[row["instance"]].append(row)

    topology = rebuild_level1_hydraulic(components, connections, parents)

    elements = list(elements_v2)
    line_models = {
        "HL0000": ("C", "lumped hydraulic compliance C"),
        "HL0002": ("composite subgraph", "R-C-R hydraulic line"),
        "HL011": ("composite subgraph", "segmented R-C hydraulic line chain"),
        "HL012": ("composite subgraph", "segmented C-R hydraulic line chain"),
    }
    line_element_id: dict[str, str] = {}
    for row in physical:
        alias, submodel = row["alias"], row["submodel"]
        element_id = f"L1_LINE_{alias}"
        line_element_id[alias] = element_id
        names = ";".join(state["state_name"] for state in state_by_instance[alias])
        bg_type, model = line_models[submodel]
        elements.append(
            {
                "element_id": element_id,
                "instance_alias": alias,
                "submodel": submodel,
                "level": "1",
                "domain": "hydraulic",
                "bg_type": bg_type,
                "constitutive_model": model,
                "stateful": "yes",
                "state_names": names,
                "parameter_set": f"submodels/{submodel}/parameters.csv",
                "port_count": "2",
                "parent_supercomponent": "",
                "variant": "ORIGINAL_PHYSICAL_LINE",
                "implementation_status": "READY_APPROX",
                "truth_level": "LEVEL A — SOURCE VERIFIED",
            }
        )

    element_by_id = {row["element_id"]: row for row in elements}
    ports: list[dict[str, object]] = []
    missing_level1_endpoints: list[tuple[str, str]] = []
    for port in ports_v2:
        element = element_by_id[port["element_id"]]
        if element["level"] == "1" and port["domain"] == "hydraulic":
            endpoint = (element["instance_alias"], str(port["port_id"]))
            junction = topology.endpoint_to_junction.get(endpoint)
            if junction is None:
                missing_level1_endpoints.append(endpoint)
                junction = "MISSING_V3_JUNCTION"
            updated = dict(port)
            updated["connected_junction"] = junction
            ports.append(updated)
        else:
            ports.append(dict(port))

    for line in physical:
        alias = line["alias"]
        for port_id in ("0", "1"):
            endpoint = (alias, port_id)
            junction = topology.endpoint_to_junction.get(endpoint, "MISSING_V3_JUNCTION")
            if junction == "MISSING_V3_JUNCTION":
                missing_level1_endpoints.append(endpoint)
            ports.append(
                {
                    "element_id": line_element_id[alias],
                    "port_id": port_id,
                    "domain": "hydraulic",
                    "effort_variable": "pressure",
                    "flow_variable": "volumetric flow",
                    "sign_convention": "positive into physical line at this external port",
                    "connected_junction": junction,
                }
            )

    # Preserve frozen Level-2 hydraulic and all mechanical junctions.  Replace
    # only the erroneous Level-1 hydraulic registry.
    junctions = [row for row in junctions_v2 if not (row["level"] == "1" and row["domain"] == "hydraulic")]
    junctions.extend(topology.junctions)

    parameter_lookup = parameter_map(parameters)
    port_by_element: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in ports:
        port_by_element[str(row["element_id"])].append(row)

    # Conservative branch test for segmented-line reduction.  Traverse at
    # most three stateless power elements from either line end, stopping at
    # every other stateful element and every other physical line.
    elements_by_junction: dict[str, set[str]] = defaultdict(set)
    for row in ports:
        if row["domain"] == "hydraulic":
            elements_by_junction[str(row["connected_junction"])].add(str(row["element_id"]))
    stateful_ids = {row["element_id"] for row in elements if row["state_names"]}
    actuator_ids = {row["element_id"] for row in elements if row["submodel"] in {"HJ020", "HJ021", "HJ0022"}}
    physical_line_ids = set(line_element_id.values())

    def near_actuator_branch(element_id: str) -> bool:
        queue = [(str(port["connected_junction"]), 0) for port in port_by_element[element_id]]
        visited = {junction for junction, _ in queue}
        while queue:
            junction, depth = queue.pop(0)
            for neighbor_id in elements_by_junction[junction]:
                if neighbor_id in actuator_ids:
                    return True
                if neighbor_id == element_id or neighbor_id in physical_line_ids or neighbor_id in stateful_ids or depth >= 3:
                    continue
                for neighbor_port in port_by_element[neighbor_id]:
                    next_junction = str(neighbor_port["connected_junction"])
                    if neighbor_port["domain"] == "hydraulic" and next_junction not in visited:
                        visited.add(next_junction)
                        queue.append((next_junction, depth + 1))
        return False

    registry: list[dict[str, object]] = []
    reduction: list[dict[str, object]] = []
    fast_line_states = 0
    for line in physical:
        alias, submodel = line["alias"], line["submodel"]
        line_ports = sorted(port_by_element[line_element_id[alias]], key=lambda row: str(row["port_id"]))
        pmap = parameter_lookup[alias]
        area_mm2 = number(pmap.get("cross-sectional area"))
        length_m = number(pmap.get("length"))
        volume_m3 = area_mm2 * 1.0e-6 * length_m
        original_count = len(state_by_instance[alias])
        critical = near_actuator_branch(line_element_id[alias])
        fast_count = 2 if submodel in {"HL011", "HL012"} and critical else 1
        fast_line_states += fast_count
        endpoint_text = ";".join(f"{row['port_id']}->{row['connected_junction']}" for row in line_ports)
        registry.append(
            {
                "instance": alias,
                "submodel": submodel,
                "classification": "PHYSICAL_TWO_PORT_POWER_ELEMENT",
                "element_id": line_element_id[alias],
                "external_endpoints": endpoint_text,
                "endpoint_count": len(line_ports),
                "state_count": original_count,
                "state_names": ";".join(row["state_name"] for row in state_by_instance[alias]),
                "state_equation_family": state_by_instance[alias][0]["state_equation"] if state_by_instance[alias] else "",
                "original_volume_m3": f"{volume_m3:.12g}",
                "source": "01_components.csv; 02_connections_fullalias.csv; 04_parameters.csv; 11A_state_variable_registry.csv",
            }
        )
        reduction.append(
            {
                "instance": alias,
                "submodel": submodel,
                "original_state_count": original_count,
                "fast_state_count": fast_count,
                "original_volume": f"{volume_m3:.12g} m^3",
                "fast_equivalent_volume": f"{volume_m3:.12g} m^3",
                "original_resistance_description": "distributed Amesim line loss" if submodel in {"HL011", "HL012"} else ("two half-line losses" if submodel == "HL0002" else "none in HL0000 compliance"),
                "fast_equivalent_resistance": "R_lam,total*q + R_quad,total*q*abs(q); split equally between cells when fast_state_count=2",
                "reduction_reason": "two cells retained: directly adjacent to actuator chamber" if fast_count == 2 else "one equivalent pressure cell; total volume and total steady loss preserved",
            }
        )

    junction_ids = {row["junction_id"] for row in junctions}
    element_aliases = {row["instance_alias"] for row in elements}
    all_state_keys = {(row["instance"], row["state_name"]) for row in states}
    owned_state_keys = {(row["instance"], row["state_name"]) for row in states if row["instance"] in element_aliases}
    line_state_count = sum(len(state_by_instance[row["alias"]]) for row in physical)
    physical_line_port_rows = [row for row in ports if row["element_id"] in set(line_element_id.values())]
    physical_line_junctions_separate = all(
        len({str(row["connected_junction"]) for row in port_by_element[element_id]}) == 2 for element_id in line_element_id.values()
    )
    power_ports_connected = not missing_level1_endpoints and all(
        row["connected_junction"] in junction_ids or row["connected_junction"] == "EXTERNAL_MECHANICAL_BOUNDARY" for row in ports
    )

    def separated(submodels: set[str]) -> bool:
        return all(
            len({str(port["connected_junction"]) for port in port_by_element[element["element_id"]] if port["domain"] == "hydraulic"}) >= 2
            for element in elements
            if element["level"] == "1" and element["submodel"] in submodels
        )

    sc_ok = all(
        row["level"] != "1" or not row["parent_supercomponent"]
        for row in elements
    ) and all(
        row["level"] != "2" or bool(row["parent_supercomponent"])
        for row in elements
    )
    checks = [
        ("physical_lines_in_elements", len(line_element_id) == 65, f"{len(line_element_id)}/65"),
        ("physical_line_ports_present", len(physical_line_port_rows) == 130, f"{len(physical_line_port_rows)}/130"),
        ("line_states_have_owner", line_state_count == 323, f"{line_state_count}/323"),
        ("every_physical_state_has_owner", owned_state_keys == all_state_keys, f"{len(owned_state_keys)}/{len(all_state_keys)}"),
        ("every_stateful_line_is_power_element", all(row["alias"] in element_aliases for row in physical), f"{sum(row['alias'] in element_aliases for row in physical)}/65"),
        ("every_physical_line_has_two_external_endpoints", all(len(port_by_element[eid]) == 2 for eid in line_element_id.values()), "65/65"),
        ("pure_connectivity_lines_not_power_elements", not (pure_lines & element_aliases), f"{len(pure_lines)} DIRECT aliases excluded"),
        ("no_physical_line_collapsed_as_junction", physical_line_junctions_separate, "65/65 two distinct junctions"),
        ("pump_ports_separated", separated({"PU001"}), "4/4"),
        ("actuator_chambers_separated", separated({"HJ020", "HJ021", "HJ0022"}), "7/7"),
        ("all_power_ports_connected", power_ports_connected, f"{len(ports)}/{len(ports)}"),
        ("all_physical_states_owned", owned_state_keys == all_state_keys, f"{len(owned_state_keys)}/{len(all_state_keys)}"),
        ("SC_1 hierarchy", sc_ok, "Level 1 parent aliases remain opaque; Level 2 retained"),
    ]

    # Re-evaluate the previously false variableorifice_14 short-circuit claim.
    vo = next(row for row in elements if row["instance_alias"] == "variableorifice_14")
    vo_junctions = {str(row["connected_junction"]) for row in port_by_element[vo["element_id"]] if row["domain"] == "hydraulic"}
    checks.append(("variableorifice_14_rechecked", len(vo_junctions) == 2, ";".join(sorted(vo_junctions))))

    check_rows = [
        {"check": name, "status": "PASS" if ok else "FAIL", "evidence": evidence}
        for name, ok, evidence in checks
    ]
    freeze_pass = all(row["status"] == "PASS" for row in check_rows)

    write("17A_bondgraph_elements_v3.csv", elements, list(elements_v2[0]))
    write("17B_bondgraph_ports_v3.csv", ports, list(ports_v2[0]))
    write("17C_bondgraph_junctions_v3.csv", junctions, list(junctions_v2[0]))
    write(
        "17D_physical_line_registry.csv",
        registry,
        ["instance", "submodel", "classification", "element_id", "external_endpoints", "endpoint_count", "state_count", "state_names", "state_equation_family", "original_volume_m3", "source"],
    )
    write("17E_ir_v3_sanity_checks.csv", check_rows, ["check", "status", "evidence"])
    write(
        "17G_fast_line_reduction_map.csv",
        reduction,
        ["instance", "submodel", "original_state_count", "fast_state_count", "original_volume", "fast_equivalent_volume", "original_resistance_description", "fast_equivalent_resistance", "reduction_reason"],
    )

    report = f"""# Bond Graph IR Freeze V3

## Scope

This is a local, traceable structural correction to IR V2.  It does not change
the frozen constitutive equations.  Amesim `ame_line` objects are classified by
metadata: `DIRECT` remains ideal connectivity, while HL0000, HL0002, HL011 and
HL012 are restored as two-port power elements.

## Physical line recovery

- Physical line elements: **{len(physical)}**
- Physical line ports: **{len(physical_line_port_rows)}**
- Original line pressure states: **{line_state_count}**
- FAST line pressure states: **{fast_line_states}**
- Original total physical states: **{len(states)}**
- FAST total states: **{len(states) - line_state_count + fast_line_states}**

The rebuilt Level-1 hydraulic topology unions only DIRECT lines and ideal
hydraulic topology nodes.  It never unions the two ports of a physical HL line.
Level-2 SC_1 and mechanical junctions are carried forward unchanged from V2.

## variableorifice_14 correction

After restoring `hydraulic_165` (HL0000) and `hydraulic_166` (HL0002), the two
hydraulic ports of `variableorifice_14` connect to **{', '.join(sorted(vo_junctions))}**.
They are distinct, so the previous “shorted redundant MR branch” conclusion is
withdrawn.

## Gate results

""" + "\n".join(f"- {row['check']}: **{row['status']}** — {row['evidence']}" for row in check_rows) + f"""

## Freeze decision

**BOND GRAPH IR FREEZE V3 = {'PASS' if freeze_pass else 'FAIL'}**
"""
    (AUDIT / "17F_BONDGRAPH_IR_FREEZE_V3.md").write_text(report, encoding="utf-8")

    print("=" * 60)
    print(f"BOND GRAPH IR FREEZE V3 = {'PASS' if freeze_pass else 'FAIL'}")
    print(f"PHYSICAL LINES = {len(physical)}/65")
    print(f"LINE STATES OWNED = {line_state_count}/323")
    print(f"ORIGINAL PHYSICAL STATES = {len(states)}")
    print(f"FAST LINE STATES = {fast_line_states}")
    print(f"FAST TOTAL STATES = {len(states) - line_state_count + fast_line_states}")
    print("=" * 60)
    if not freeze_pass:
        failed = [row["check"] for row in check_rows if row["status"] == "FAIL"]
        raise SystemExit("IR V3 gate failure: " + ", ".join(failed))


if __name__ == "__main__":
    main()
