from pathlib import Path

from steering_sim.hydraulics.solver import FastHydraulicModel
from steering_sim.hydraulics.solver.jacobian_sparsity import build_jacobian_sparsity


ROOT = Path(__file__).resolve().parents[3]


def test_every_state_has_a_structural_self_dependency():
    analysis = build_jacobian_sparsity(FastHydraulicModel.from_ir(ROOT / "hydraulic_audit"))
    assert analysis.matrix.diagonal().all()
    assert len(analysis.state_groups) == 109


def test_group_cache_dependencies_are_local():
    model = FastHydraulicModel.from_ir(ROOT / "hydraulic_audit")
    dependencies = [len(group.dependent_state_indices) for group in model.groups if group.solver]
    assert dependencies
    assert max(dependencies) < 109
    assert sum(dependencies) < 49 * 109

