from pathlib import Path

import numpy as np

from steering_sim.hydraulics.solver import FastHydraulicModel


ROOT = Path(__file__).resolve().parents[3]
INPUTS = {"pump_speed_rad_s": 100.0, "valve_command": 0.23}


def test_exact_signature_cache_preserves_rhs():
    cached = FastHydraulicModel.from_ir(ROOT / "hydraulic_audit")
    uncached = FastHydraulicModel.from_ir(ROOT / "hydraulic_audit")
    uncached._use_algebraic_cache = False
    state = cached.initial_state.copy()
    reference = uncached.rhs(0.0, state, INPUTS)
    assert np.array_equal(cached.rhs(0.0, state, INPUTS), reference)
    assert np.array_equal(cached.rhs(0.0, state, INPUTS), reference)
    assert sum(group.cache_hits for group in cached.groups) > 0


def test_state_perturbation_invalidates_affected_group():
    model = FastHydraulicModel.from_ir(ROOT / "hydraulic_audit")
    state = model.initial_state.copy()
    model.rhs(0.0, state, INPUTS)
    before = sum(group.solver.diagnostics.calls for group in model.groups if group.solver)
    state[0] += 100.0
    model.rhs(0.0, state, INPUTS)
    after = sum(group.solver.diagnostics.calls for group in model.groups if group.solver)
    assert after > before
    assert after - before < sum(group.solver is not None for group in model.groups)

