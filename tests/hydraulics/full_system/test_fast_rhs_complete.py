from pathlib import Path

import numpy as np

from steering_sim.hydraulics.solver import FastHydraulicModel

ROOT = Path(__file__).resolve().parents[3]


def test_fast_rhs_supplies_all_109_entries():
    model = FastHydraulicModel.from_ir(ROOT / "hydraulic_audit")
    state, _ = model.initialize({"pump_speed_rad_s": 0.0})
    derivative = model.rhs(0.0, state, {"pump_speed_rad_s": 0.0})
    assert derivative.shape == (109,)
    assert np.isfinite(derivative).all()
    assert model._rhs_entries_supplied.all()
