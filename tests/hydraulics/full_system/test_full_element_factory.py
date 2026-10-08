from pathlib import Path

from steering_sim.hydraulics.assembly import HydraulicSystem


ROOT = Path(__file__).resolve().parents[3]


def test_all_active_elements_have_fast_strategy():
    system = HydraulicSystem.from_ir(ROOT / "hydraulic_audit")
    active = [element for element in system.elements if element.active_power]
    assert active
    assert all(element.strategy for element in active)


def test_all_65_physical_lines_are_elements():
    system = HydraulicSystem.from_ir(ROOT / "hydraulic_audit")
    lines = [element for element in system.elements if element.submodel in {"HL0000", "HL0002", "HL011", "HL012"}]
    assert len(lines) == 65
    assert all(element.port_count == 2 for element in lines)
