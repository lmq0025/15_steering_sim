import math
import numpy as np
from steering_sim.hydraulics_lumped import SystemInputs
from steering_sim.hydraulics_lumped.simulation import simulate_rk4


def test_sine_response_1hz(model):
    speeds = [c.pump.nominal_speed for c in model.channels]
    def fn(t):
        x = 1e-4*math.sin(2*math.pi*t)
        v = 2*math.pi*1e-4*math.cos(2*math.pi*t)
        motion = {c.actuator_alias:(x,v,-(2*math.pi)**2*x) for c in model.channels}
        return SystemInputs([1,1,1,1+.005*math.sin(2*math.pi*t)], speeds, [0]*4,
                            prescribed_motion_by_alias=motion)
    _, x = simulate_rk4(model, .25, 5e-4, fn)
    assert np.isfinite(x).all()
    assert np.ptp(x[:, 12]) > 0
