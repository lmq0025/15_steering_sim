from pathlib import Path

from steering_sim.hydraulics.assembly import HydraulicSystem


ROOT = Path(__file__).resolve().parents[3]


def test_state_indices_are_dense_and_unique():
    system = HydraulicSystem.from_ir(ROOT / "hydraulic_audit")
    assert [state.index for state in system.states] == list(range(len(system.states)))


def test_fast_preserves_every_non_line_state():
    full = HydraulicSystem.from_ir(ROOT / "hydraulic_audit", "full")
    fast = HydraulicSystem.from_ir(ROOT / "hydraulic_audit", "fast")
    line_submodels = {"HL0000", "HL0002", "HL011", "HL012"}
    full_non_line = {(s.instance, s.state_name) for s in full.states if s.submodel not in line_submodels}
    fast_non_line = {(s.instance, s.state_name) for s in fast.states if s.submodel not in line_submodels}
    assert full_non_line == fast_non_line
