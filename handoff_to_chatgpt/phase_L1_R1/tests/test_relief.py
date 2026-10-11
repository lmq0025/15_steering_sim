import pytest
from steering_sim.hydraulics_lumped.supply import relief_flow, solve_supply


def test_relief_is_flow_law_not_pressure_clamp(model):
    c = model.channels[0]
    assert relief_flow(c.supply.relief_cracking_pressure-1, c.supply.relief_cracking_pressure, c.supply.relief_conductance) == 0
    assert relief_flow(c.supply.relief_cracking_pressure+1e5, c.supply.relief_cracking_pressure, c.supply.relief_conductance) > 0
    s = solve_supply(c.pump.displacement*c.pump.nominal_speed, 0.0, 0.0, 0.0, c)
    assert s.pressure > c.supply.relief_cracking_pressure
    assert s.relief_flow == pytest.approx(c.pump.displacement*c.pump.nominal_speed)
