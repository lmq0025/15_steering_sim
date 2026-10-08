from __future__ import annotations

import csv
import hashlib
from collections import defaultdict
from pathlib import Path

ROOT = Path(r"E:\15_project")
AUDIT = ROOT / "hydraulic_audit"


def read_csv(name: str) -> list[dict[str, str]]:
    with (AUDIT / name).open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def signature(rows: list[dict[str, str]], columns: tuple[str, ...]) -> str:
    values = sorted("|".join(r.get(c, "") for c in columns) for r in rows)
    digest = hashlib.sha256("\n".join(values).encode("utf-8")).hexdigest()[:10]
    return f"{len(rows)}:{digest}"


def main() -> None:
    components = read_csv("01_components.csv")
    params = read_csv("04_parameters.csv")
    variables = read_csv("05_variables.csv")
    candidates = read_csv("06A_bondgraph_component_candidates_v2.csv")
    edges = read_csv("08B_system_hydraulic_edges.csv")

    comp_by_alias = {r["alias"]: r for r in components}
    cand_by_alias = {r["alias"]: r for r in candidates}
    params_by_alias: dict[str, list[dict[str, str]]] = defaultdict(list)
    vars_by_alias: dict[str, list[dict[str, str]]] = defaultdict(list)
    for r in params:
        params_by_alias[r["alias"]].append(r)
    for r in variables:
        vars_by_alias[r["alias"]].append(r)

    system_edge_aliases = {r["component_alias"] for r in edges}
    by_submodel: dict[str, list[dict[str, str]]] = defaultdict(list)
    for r in components:
        if r.get("submodel"):
            by_submodel[r["submodel"]].append(r)

    rows: list[dict[str, object]] = []
    for submodel, group in sorted(by_submodel.items()):
        aliases = sorted(r["alias"] for r in group)
        cands = [cand_by_alias[a] for a in aliases if a in cand_by_alias]
        top = [a for a in aliases if cand_by_alias.get(a, {}).get("is_internal") != "yes"]
        internal = [a for a in aliases if cand_by_alias.get(a, {}).get("is_internal") == "yes"]
        domains = sorted({r.get("domain_combo", "") for r in cands if r.get("domain_combo")})
        bg = sorted({r.get("candidate_bg_type", "") for r in cands if r.get("candidate_bg_type")})
        psigs = sorted({signature(params_by_alias[a], ("parameter_type", "title", "unit")) for a in aliases})
        vsigs = sorted({signature(vars_by_alias[a], ("basic_type", "title", "unit", "io_type")) for a in aliases})
        ssigs = sorted({str(sum(v.get("basic_type") == "ame_state_variable" for v in vars_by_alias[a])) for a in aliases})
        is_nonpower = submodel in {"FP04", "TFFD04", "GRAV0"}
        is_topology = submodel.startswith(("H2NODE", "H3NODE", "H4NODE", "HN")) or submodel == "DIRECT"
        is_signal = all((r.get("library") == "sig" or r.get("domain_combo") == "signal") for r in cands) and bool(cands)
        if submodel in {"HJ020", "HJ021", "HJ0022", "HYDVORF0", "SC_1", "PU001"}:
            priority = "P0"
        elif any(a in system_edge_aliases for a in aliases):
            priority = "P1"
        elif internal:
            priority = "P2"
        else:
            priority = "P3"
        if is_nonpower:
            status = "NON_POWER_OBJECT"
        elif is_topology:
            status = "TOPOLOGY_OR_CONNECTION"
        elif is_signal:
            status = "SIGNAL_PENDING"
        else:
            status = "PENDING_SOURCE_AUDIT"
        rows.append({
            "submodel": submodel,
            "base_alias": ";".join(sorted({r.get("base_alias", "") for r in group})),
            "library": ";".join(sorted({r.get("library", "") for r in group if r.get("library")})),
            "instance_count": len(aliases),
            "instance_aliases": ";".join(aliases),
            "domain_combo": ";".join(domains) or "unresolved",
            "candidate_bg_type": ";".join(bg) or "unresolved",
            "parameter_count_pattern": ";".join(psigs),
            "variable_count_pattern": ";".join(vsigs),
            "state_variable_count_pattern": ";".join(ssigs),
            "top_level_used": "yes" if top else "no",
            "internal_used": "yes" if internal else "no",
            "system_hydraulic_edge_used": "yes" if any(a in system_edge_aliases for a in aliases) else "no",
            "audit_priority": priority,
            "audit_status": status,
        })

    fields = list(rows[0])
    write_csv(AUDIT / "10A_submodel_inventory.csv", rows, fields)
    system = [r for r in rows if r["top_level_used"] == "yes"]
    internal = [r for r in rows if r["internal_used"] == "yes"]
    with_states = [r for r in rows if r["state_variable_count_pattern"] != "0"]
    unresolved = [r for r in rows if str(r["audit_status"]).startswith("PENDING")]
    md = [
        "# Actual Submodel Audit Inventory",
        "",
        "Generated from frozen model metadata and V4 Level-1 topology. Counts include signal, topology, and non-power objects so exclusions remain traceable.",
        "",
        f"- TOTAL UNIQUE SUBMODELS: {len(rows)}",
        f"- SYSTEM-LEVEL SUBMODELS: {len(system)}",
        f"- SUPERCOMPONENT INTERNAL SUBMODELS: {len(internal)}",
        f"- SUBMODELS WITH AMESIM-DECLARED STATES: {len(with_states)}",
        f"- SUBMODELS WITHOUT AMESIM-DECLARED STATES: {len(rows) - len(with_states)}",
        f"- UNRESOLVED SUBMODELS BEFORE SOURCE AUDIT: {len(unresolved)}",
        "",
        "## Important interpretation",
        "",
        "`ame_state_variable` includes physical integration states and Amesim activity/energy accounting states. The latter are retained as metadata evidence but excluded from the physical ODE/DAE registry unless source equations show physical storage.",
        "",
        "## Families",
        "",
        "| Submodel | Instances | Library | Level-1 | Internal | Candidate | Priority | Initial status |",
        "|---|---:|---|---|---|---|---|---|",
    ]
    for r in rows:
        md.append(f"| {r['submodel']} | {r['instance_count']} | {r['library'] or '-'} | {r['top_level_used']} | {r['internal_used']} | {r['candidate_bg_type']} | {r['audit_priority']} | {r['audit_status']} |")
    (AUDIT / "10B_submodel_inventory_summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(f"TOTAL UNIQUE SUBMODELS = {len(rows)}")
    print(f"SYSTEM-LEVEL SUBMODELS = {len(system)}")
    print(f"SUPERCOMPONENT INTERNAL SUBMODELS = {len(internal)}")
    print(f"SUBMODELS WITH STATES = {len(with_states)}")
    print(f"SUBMODELS WITHOUT STATES = {len(rows) - len(with_states)}")
    print(f"UNRESOLVED SUBMODELS = {len(unresolved)}")


if __name__ == "__main__":
    main()
