from pathlib import Path

from steering_sim.hydraulics.assembly import HydraulicSystem


ROOT = Path(__file__).resolve().parents[3]


def test_no_active_element_is_unsupported_or_silently_dropped():
    system = HydraulicSystem.from_ir(ROOT / "hydraulic_audit")
    active = [element for element in system.elements if element.active_power]
    assert len(active) == 194
    assert all(element.strategy and element.classification in {"READY_EXACT", "READY_APPROX"} for element in active)


def test_algebraic_groups_are_precomputed():
    system = HydraulicSystem.from_ir(ROOT / "hydraulic_audit")
    assert system.algebraic_groups
    assert all(group.elements and group.junctions and group.unknown_count > 0 for group in system.algebraic_groups)
