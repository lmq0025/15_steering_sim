from pathlib import Path

import numpy as np

from steering_sim.hydraulics.solver import FastHydraulicModel

ROOT = Path(__file__).resolve().parents[3]


def test_fast_initialization_is_finite_and_balanced():
    model = FastHydraulicModel.from_ir(ROOT / "hydraulic_audit")
    state, algebraic = model.initialize({"pump_speed_rad_s": 0.0})
    assert state.shape == (109,)
    assert np.isfinite(state).all()
    assert algebraic.success
    assert algebraic.max_hydraulic_residual_m3_s < 1e-6
