from pathlib import Path

from steering_sim.hydraulics.assembly import HydraulicSystem


ROOT = Path(__file__).resolve().parents[3]


def test_signal_links_load_and_cycles_are_explicit_sc1_static_groups():
    system = HydraulicSystem.from_ir(ROOT / "hydraulic_audit")
    assert len(system.signal_graph.links) == 192
    assert not system.signal_graph.cyclic_nodes or system.signal_graph.cycles_are_explicit_static_sc1()


def test_every_internal_sc1_orifice_has_modulation_link():
    system = HydraulicSystem.from_ir(ROOT / "hydraulic_audit")
    targets = system.signal_graph.modulation_targets()
    orifices = {e.instance_alias for e in system.elements if e.level == 2 and e.submodel == "HYDVORF0"}
    assert len(orifices) == 28
    assert orifices <= targets
