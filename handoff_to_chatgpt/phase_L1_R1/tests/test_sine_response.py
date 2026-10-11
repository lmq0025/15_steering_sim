import math
import numpy as np
from steering_sim.hydraulics_lumped import SystemInputs
from steering_sim.hydraulics_lumped.simulation import simulate_rk4


def test_sine_response_1hz(model):
    speeds = [c.pump.nominal_speed for c in model.channels]
    fn = lambda t: SystemInputs([0,0,0,.005*math.sin(2*math.pi*t)], speeds, [0]*4)
    _, x = simulate_rk4(model, .25, 5e-4, fn)
    assert np.isfinite(x).all()
    assert np.ptp(x[:, 14]) > 0
