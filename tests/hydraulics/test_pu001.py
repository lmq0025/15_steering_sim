import math

from steering_sim.hydraulics.elements import PU001
from steering_sim.hydraulics.units import cc_per_rev_to_m3_per_rad, m3ps_to_lpm, rpm_to_rad_s


def test_pu001_nominal_flow_is_13_5_lpm():
    pump = PU001(cc_per_rev_to_m3_per_rad(10.0))
    q = pump.flow_m3_s(rpm_to_rad_s(1350.0))
    assert math.isclose(m3ps_to_lpm(q), 13.5, rel_tol=1e-12)


def test_pu001_torque_pressure_direction():
    pump = PU001(cc_per_rev_to_m3_per_rad(10.0))
    assert pump.torque_nm(1e5, 101e5) > 0.0
