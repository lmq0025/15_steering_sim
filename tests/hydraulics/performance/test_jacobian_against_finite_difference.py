from pathlib import Path

from steering_sim.hydraulics.solver import FastHydraulicModel
from steering_sim.hydraulics.solver.jacobian_sparsity import build_jacobian_sparsity, structural_violations


ROOT = Path(__file__).resolve().parents[3]


def test_structural_pattern_contains_sampled_finite_differences():
    model = FastHydraulicModel.from_ir(ROOT / "hydraulic_audit")
    model._use_algebraic_cache = False
    inputs = {"pump_speed_rad_s": 0.0, "valve_command": 0.2}
    state, _ = model.initialize(inputs)
    assert structural_violations(model, state, inputs, build_jacobian_sparsity(model)) == []

