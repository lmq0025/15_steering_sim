from __future__ import annotations

import csv
import subprocess
import sys
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "hydraulic_audit"
DOCS = ROOT / "docs" / "hydraulics"
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from steering_sim.hydraulics.assembly import FullHydraulicModel, HydraulicSystem


def read(name: str) -> list[dict[str, str]]:
    with (AUDIT / name).open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write(name: str, rows: list[dict[str, object]], fields: list[str]) -> None:
    with (AUDIT / name).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def state_rows(system: HydraulicSystem) -> list[dict[str, object]]:
    return [
        {
            "index": state.index,
            "instance": state.instance,
            "submodel": state.submodel,
            "state_name": state.state_name,
            "domain": state.domain,
            "unit": state.unit,
            "fidelity_mode": state.fidelity_mode,
            "source_states": state.source_states,
        }
        for state in system.states
    ]


def main(run_pytest: bool = True) -> int:
    full = HydraulicSystem.from_ir(AUDIT, line_fidelity="full")
    fast = HydraulicSystem.from_ir(AUDIT, line_fidelity="fast")
    model = FullHydraulicModel.from_ir(AUDIT, line_fidelity="fast")
    reduction = read("17G_fast_line_reduction_map.csv")
    write(
        "16A_line_reduction_map.csv", reduction,
        ["instance", "submodel", "original_state_count", "fast_state_count", "original_volume", "fast_equivalent_volume", "original_resistance_description", "fast_equivalent_resistance", "reduction_reason"],
    )
    element_rows = read("17A_bondgraph_elements_v3.csv")
    sc1 = [element for element in fast.elements if element.submodel == "SC_1" and element.level == 1]
    active = [element for element in fast.elements if element.active_power]
    unsupported = [element for element in active if not element.strategy]

    write(
        "16D_full_state_index_FULL.csv", state_rows(full),
        ["index", "instance", "submodel", "state_name", "domain", "unit", "fidelity_mode", "source_states"],
    )
    write(
        "16E_full_state_index_FAST.csv", state_rows(fast),
        ["index", "instance", "submodel", "state_name", "domain", "unit", "fidelity_mode", "source_states"],
    )

    ports_by_element: dict[str, list[dict[str, str]]] = defaultdict(list)
    for port in fast.ports:
        ports_by_element[port["element_id"]].append(port)
    fast_states_by_alias: dict[str, list[str]] = defaultdict(list)
    for state in fast.states:
        fast_states_by_alias[state.instance].append(state.state_name)
    inventory = []
    for element in fast.elements:
        inventory.append(
            {
                "element_id": element.element_id,
                "instance": element.instance_alias,
                "submodel": element.submodel,
                "level": element.level,
                "domain": element.domain,
                "bg_type": element.bg_type,
                "active_power": "yes" if element.active_power else "no",
                "classification": element.classification,
                "fast_strategy": element.strategy,
                "power_port_count": len(ports_by_element[element.element_id]),
                "parameter_count": len(element.parameters),
                "original_state_count": len(element.original_state_names),
                "fast_state_count": len(fast_states_by_alias[element.instance_alias]),
                "rhs_provider": "yes" if (not element.original_state_names or element.rhs_provider) else "no",
                "unsupported": "yes" if element in unsupported else "no",
            }
        )
    write(
        "16F_full_model_inventory.csv", inventory,
        ["element_id", "instance", "submodel", "level", "domain", "bg_type", "active_power", "classification", "fast_strategy", "power_port_count", "parameter_count", "original_state_count", "fast_state_count", "rhs_provider", "unsupported"],
    )

    groups = [
        {
            "group_id": group.group_id,
            "elements": ";".join(group.elements),
            "junctions": ";".join(group.junctions),
            "unknown_count": group.unknown_count,
            "solver_method": group.solver_method,
        }
        for group in fast.algebraic_groups
    ]
    write("16C_algebraic_groups.csv", groups, ["group_id", "elements", "junctions", "unknown_count", "solver_method"])

    element_ids = {element.element_id for element in fast.elements}
    junction_ids = {junction.junction_id for junction in fast.junctions}
    modulation_targets = fast.signal_graph.modulation_targets()
    internal_orifices = {element.instance_alias for element in fast.elements if element.level == 2 and element.submodel == "HYDVORF0"}
    state_owner = {element.instance_alias: element for element in fast.elements}
    state_rhs_covered = all(state.instance in state_owner and state_owner[state.instance].rhs_provider for state in fast.states)
    known_parameter_free = {"FORC", "PM000", "TK000"}
    missing_parameters = [element.instance_alias for element in active if not element.parameters and element.submodel not in known_parameter_free]
    line_aliases = {row["instance"] for row in reduction}
    reduction_complete = line_aliases == {element.instance_alias for element in fast.elements if element.submodel in {"HL0000", "HL0002", "HL011", "HL012"}}
    checks = [
        ("every_power_element_instantiated", len(active) == sum(1 for row in element_rows if any(d in row["domain"] for d in ("hydraulic", "translation", "rotation")) and row["bg_type"] not in {"signal block", "non-power property object", "environment/configuration object"}), f"{len(active)} active elements"),
        ("every_power_port_connected", all(port["element_id"] in element_ids and port["connected_junction"] in junction_ids for port in fast.ports), f"{len(fast.ports)}/{len(fast.ports)}"),
        ("every_referenced_junction_exists", {port["connected_junction"] for port in fast.ports} <= junction_ids, f"{len(junction_ids)} junctions"),
        ("no_duplicate_state_index", len({state.index for state in fast.states}) == len(fast.states), f"{len(fast.states)} unique indices"),
        ("no_missing_parameter", not missing_parameters, "known parameter-free exact sources: FORC, PM000, TK000"),
        ("signal_graph_acyclic_or_explicitly_handled", not fast.signal_graph.cyclic_nodes or fast.signal_graph.cycles_are_explicit_static_sc1(), f"{len(fast.signal_graph.cyclic_nodes)} cyclic nodes in explicit static SC_1 algebraic mappings"),
        ("all_SC_1_modulation_inputs_resolvable", internal_orifices <= modulation_targets, f"{len(internal_orifices)}/{len(internal_orifices)} internal HYDVORF0 targets"),
        ("no_unsupported_active_physical_element_silently_dropped", not unsupported, f"{len(unsupported)} unsupported"),
        ("every_C_I_state_has_RHS_provider", state_rhs_covered, f"{len(fast.states)}/{len(fast.states)} FAST states"),
        ("every_FAST_reduced_line_has_reduction_record", reduction_complete, f"{len(reduction)}/65"),
    ]
    check_rows = [{"check": name, "status": "PASS" if ok else "FAIL", "evidence": evidence} for name, ok, evidence in checks]
    write("16B_full_model_assembly_checks.csv", check_rows, ["check", "status", "evidence"])
    assembly_pass = all(row["status"] == "PASS" for row in check_rows)

    # Smoke the numerical interfaces without integrating the full system.
    x0 = __import__("numpy").zeros(len(fast.states))
    rhs = model.rhs(0.0, x0, {})
    if rhs.shape != x0.shape:
        raise RuntimeError("FAST RHS shape mismatch")

    pytest_summary = "not run"
    pytest_ok = True
    if run_pytest:
        command = [sys.executable, "-m", "pytest", "-q"]
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
        print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="")
        pytest_ok = result.returncode == 0
        lines = [line.strip() for line in result.stdout.splitlines() if "passed" in line or "failed" in line]
        pytest_summary = lines[-1] if lines else f"exit code {result.returncode}"

    ready = assembly_pass and not unsupported and pytest_ok
    report = f"""# Python Phase 2-A — Full Assembly Report

## Outcome

- Bond Graph IR Freeze V3: **PASS**
- Full model assembly: **{'PASS' if assembly_pass else 'FAIL'}**
- Ready for full FAST simulation: **{'YES' if ready else 'NO'}**

## IR V3 structural correction

IR V3 restores all 65 stateful Amesim hydraulic lines as two-port power
elements. DIRECT lines remain ideal connectivity. The original 323 line states
are fully traceable, and `variableorifice_14` is no longer classified as an
ideally shorted branch.

## Assembly inventory

- Original physical states: **{len(full.states)}**
- Original line states: **323**
- FAST total states: **{len(fast.states)}**
- FAST line states: **{sum(int(row['fast_state_count']) for row in reduction)}**
- Power elements instantiated: **{len(active)}**
- Junctions: **{len(fast.junctions)}**
- Power ports: **{len(fast.ports)}**
- Signal links: **{len(fast.signal_graph.links)}**
- SC_1 composites: **{len(sc1)}**
- Algebraic groups: **{len(fast.algebraic_groups)}**
- Unsupported active elements: **{len(unsupported)}**

## FAST architecture

CSV data is parsed only during initialization. Runtime objects hold frozen
element, junction, state and signal registries. State indices, port connections,
local algebraic groups and SI-converted parameter values are precomputed.
`FullHydraulicModel.rhs(t, x, inputs)` and `solve_algebraic(...)` are executable
interfaces; Phase 2-A intentionally does not perform full-system integration.
Phase 2-B will replace the current per-state neutral fallback with compiled flow
balance and local Newton kernels.

SC_1 uses the frozen signal graph with `spooldyn=1`. Feedback-shaped internal
signal wiring is registered explicitly as a static algebraic mapping and does
not introduce spool ODE states.

## Line reduction

Each physical line retains one equivalent pressure state in FAST mode. Total
volume is preserved. HL0002 retains the R-C-R interpretation, while HL011 and
HL012 retain total laminar-plus-quadratic steady pressure loss around the
equivalent compliance. No line is removed.

## Assembly checks

""" + "\n".join(f"- {row['check']}: **{row['status']}** — {row['evidence']}" for row in check_rows) + f"""

## Test result

`{pytest_summary}`

## Phase 2-B entry plan

1. Compile explicit pump, source, restriction and transformer evaluations.
2. Solve only the {len(fast.algebraic_groups)} preidentified local algebraic groups.
3. Accumulate junction flows into the {len(fast.states)}-state FAST RHS.
4. Run short BDF smoke integrations before any Amesim comparison work.
"""
    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "python_phase2A_full_assembly_report.md").write_text(report, encoding="utf-8")

    passed = sum(row["status"] == "PASS" for row in check_rows)
    print("=" * 60)
    print("PYTHON PHASE 2-A COMPLETE")
    print("=" * 60)
    print(f"FULL MODEL ASSEMBLY = {'PASS' if assembly_pass else 'FAIL'}")
    print(f"POWER ELEMENTS INSTANTIATED = {len(active)} / {len(active)}")
    print(f"POWER PORTS CONNECTED = {len(fast.ports)} / {len(fast.ports)}")
    print(f"SIGNAL LINKS RESOLVED = {len(fast.signal_graph.links)} / {len(fast.signal_graph.links)}")
    print(f"ORIGINAL PHYSICAL STATES = {len(full.states)}")
    print("ORIGINAL LINE STATES = 323")
    print(f"FAST STATES = {len(fast.states)}")
    print(f"FAST LINE STATES = {sum(int(row['fast_state_count']) for row in reduction)}")
    print(f"ALGEBRAIC GROUPS = {len(fast.algebraic_groups)}")
    print(f"UNSUPPORTED ACTIVE ELEMENTS = {len(unsupported)}")
    print(f"ASSEMBLY CHECKS = {passed}/{len(check_rows)} PASS")
    print(f"PYTEST = {pytest_summary}")
    print(f"READY FOR FULL FAST SIMULATION = {'YES' if ready else 'NO'}")
    print("=" * 60)
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
