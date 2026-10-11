import numpy as np
from steering_sim.hydraulics_lumped.simulation import simulate_rk4


def test_neutral_has_no_unexplained_high_pressure(model, neutral):
    fn = lambda t: neutral
    t, x = simulate_rk4(model, 0.1, 0.0005, fn)
    assert np.isfinite(x).all()
    _, out = model.evaluate(t[-1], x[-1], neutral)
    assert max(o["supply_pressure"] for o in out) < 100e6
    assert all(o["supply_pressure"] >= 0 for o in out)
