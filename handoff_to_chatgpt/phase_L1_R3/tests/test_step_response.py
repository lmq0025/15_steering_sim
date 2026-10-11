import numpy as np
from steering_sim.hydraulics_lumped import SystemInputs
from steering_sim.hydraulics_lumped.simulation import simulate_rk4


def test_small_step_response(model):
    speeds = [c.pump.nominal_speed for c in model.channels]
    motion={c.actuator_alias:(0.0,0.0,0.0) for c in model.channels}
    fn = lambda t: SystemInputs([1.0 if t < .01 else .9]*4, speeds, [0]*4,
                                prescribed_motion_by_alias=motion)
    t, x = simulate_rk4(model, .05, 1e-4, fn)
    assert np.isfinite(x).all()
    assert np.max(np.abs(x[:, 2::4])) < max(c.actuator.stroke for c in model.channels)
