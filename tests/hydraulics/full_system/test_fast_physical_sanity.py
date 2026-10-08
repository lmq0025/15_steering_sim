from pathlib import Path

import numpy as np

from steering_sim.hydraulics.solver import FastHydraulicModel

ROOT = Path(__file__).resolve().parents[3]


def test_short_run_has_no_nan_inf_or_impossible_pressure():
    model = FastHydraulicModel.from_ir(ROOT / "hydraulic_audit")
    result = model.simulate(0.01, {"pump_speed_rad_s": 0.0}, output_points=3)
    pressures = result.state[[state.index for state in model.system.states if state.unit == "Pa"]]
    assert np.isfinite(result.state).all()
    assert pressures.min() >= -9e4
