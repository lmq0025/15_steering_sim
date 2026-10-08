import math

from steering_sim.hydraulics.elements import FixedOrifice, VariableOrifice


def test_regularized_orifice_is_odd_finite_and_zero_at_zero():
    o = FixedOrifice(area_m2=1e-6, density_kg_m3=850.0)
    assert o.flow_m3_s(1e5, 1e5) == 0.0
    qp = o.flow_m3_s(2e5, 1e5)
    qn = o.flow_m3_s(1e5, 2e5)
    assert math.isfinite(qp) and math.isclose(qp, -qn, rel_tol=1e-12)


def test_variable_orifice_modulates_area():
    o = VariableOrifice(area_m2=2e-6, density_kg_m3=850.0)
    full = o.flow_m3_s(2e5, 1e5, 1.0)
    assert math.isclose(o.flow_m3_s(2e5, 1e5, 0.5), 0.5 * full)
    assert o.flow_m3_s(2e5, 1e5, -1.0) == 0.0
