import pytest
from steering_sim.hydraulics_lumped.actuator import actuator_rates


def test_actuator_transformer_force(model):
    c = model.channels[0]
    r = actuator_rates(2e6, 1e6, 0.0, 0.0, 0.0, 0.0, 0.0, c.actuator, c.fluid)
    assert r.hydraulic_force == pytest.approx(c.actuator.area_a*2e6-c.actuator.area_b*1e6)
