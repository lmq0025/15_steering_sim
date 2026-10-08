from pathlib import Path

from steering_sim.hydraulics.assembly import HydraulicSystem


ROOT = Path(__file__).resolve().parents[3]


def test_junction_domains_have_bond_graph_types():
    system = HydraulicSystem.from_ir(ROOT / "hydraulic_audit")
    assert all(j.bg_type == ("0-junction" if j.domain == "hydraulic" else "1-junction") for j in system.junctions)


def test_physical_line_ends_are_not_collapsed():
    system = HydraulicSystem.from_ir(ROOT / "hydraulic_audit")
    ids = {e.element_id for e in system.elements if e.submodel in {"HL0000", "HL0002", "HL011", "HL012"}}
    for element_id in ids:
        junctions = {p["connected_junction"] for p in system.ports if p["element_id"] == element_id}
        assert len(junctions) == 2
