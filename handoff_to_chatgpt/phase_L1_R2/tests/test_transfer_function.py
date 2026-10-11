import numpy as np
from steering_sim.hydraulics_lumped.transfer_function import dominant_second_order


def test_dominant_second_order_is_derived():
    a = np.array([[0,1],[-100,-4]], dtype=float)
    tf = dominant_second_order(a, dc_gain=2.0)
    assert tf is not None
    assert tf.natural_frequency == pytest.approx(10.0)
    assert tf.damping_ratio == pytest.approx(.2)


import pytest
