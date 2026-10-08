from pathlib import Path

from steering_sim.hydraulics.solver import FastHydraulicModel
from steering_sim.hydraulics.solver.jacobian_sparsity import build_jacobian_sparsity


ROOT = Path(__file__).resolve().parents[3]


def test_jacobian_sparsity_is_local_and_colorable():
    analysis = build_jacobian_sparsity(FastHydraulicModel.from_ir(ROOT / "hydraulic_audit"))
    assert analysis.matrix.shape == (109, 109)
    assert analysis.matrix.nnz == 987
    assert analysis.matrix.nnz < 0.1 * 109 * 109
    assert max(analysis.colors) + 1 == 27

