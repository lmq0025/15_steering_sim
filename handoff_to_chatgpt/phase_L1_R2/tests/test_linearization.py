import numpy as np
from steering_sim.hydraulics_lumped.linearize import linearize


def test_linearization_shapes_and_finite(model, neutral):
    a, b = linearize(model, model.initial_state(5e6), neutral)
    assert a.shape == (16,16)
    assert b.shape == (16,12)
    assert np.isfinite(a).all() and np.isfinite(b).all()
