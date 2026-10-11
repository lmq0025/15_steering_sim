from steering_sim.hydraulics_lumped.actuator import actuator_rates


def test_chamber_continuity_signs(model):
    c = model.channels[0]
    r = actuator_rates(1e6, 1e6, 0.0, 0.0, 1e-5, -1e-5, 0.0, c.actuator, c.fluid)
    assert r.dp_a > 0
    assert r.dp_b < 0
    assert r.volume_a > 0 and r.volume_b > 0
