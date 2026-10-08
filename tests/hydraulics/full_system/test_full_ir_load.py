from pathlib import Path

from steering_sim.hydraulics.assembly import HydraulicSystem


ROOT = Path(__file__).resolve().parents[3]


def test_v3_ir_loads_in_both_fidelities():
    full = HydraulicSystem.from_ir(ROOT / "hydraulic_audit", "full")
    fast = HydraulicSystem.from_ir(ROOT / "hydraulic_audit", "fast")
    assert len(full.states) == 365
    assert len(fast.states) < len(full.states)
    assert len(full.elements) == len(fast.elements) == 350


def test_all_ports_reference_loaded_objects():
    system = HydraulicSystem.from_ir(ROOT / "hydraulic_audit")
    element_ids = {element.element_id for element in system.elements}
    junction_ids = {junction.junction_id for junction in system.junctions}
    assert all(port["element_id"] in element_ids for port in system.ports)
    assert all(port["connected_junction"] in junction_ids for port in system.ports)
