import pytest
from steering_sim.hydraulics_lumped.parameters import FluidParameters, ValveParameters
from steering_sim.hydraulics_lumped.valve import four_way_flows, opening


def test_opening_saturates():
    p = ValveParameters()
    assert opening(10.0, p) == pytest.approx(p.maximum_area)
    assert opening(0.0, p) == 0.0


def test_valve_direction_reverses():
    p, f = ValveParameters(), FluidParameters()
    pos = four_way_flows(0.5, 10e6, 0.0, 1e6, 1e6, p, f)
    neg = four_way_flows(-0.5, 10e6, 0.0, 1e6, 1e6, p, f)
    assert pos.q_a > 0 and pos.q_b < 0
    assert neg.q_a < 0 and neg.q_b > 0
