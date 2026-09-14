import numpy as np

from steering_sim.solvers import ExplicitFixedStepSolver, ScipyIVPSolver


def test_explicit_solver_uses_unified_rhs() -> None:
    result = ExplicitFixedStepSolver(0.01).solve(
        lambda _t, y: -y, (0.0, 0.1), np.array([1.0])
    )
    assert result.success
    assert result.state.shape[0] == 1
    assert result.state[0, -1] < 1.0


def test_stiff_scipy_methods_are_reserved() -> None:
    assert {"BDF", "Radau"}.issubset(ScipyIVPSolver.SUPPORTED_METHODS)

