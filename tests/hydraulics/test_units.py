import math

from steering_sim.hydraulics.units import (
    bar_to_pa, cc_per_rev_to_m3_per_rad, cm3_to_m3, lpm_to_m3ps,
    m3ps_to_lpm, mm_to_m, rpm_to_rad_s,
)


def test_amesim_io_units_convert_to_si():
    assert bar_to_pa(1) == 100_000.0
    assert lpm_to_m3ps(60) == 1e-3
    assert m3ps_to_lpm(1e-3) == 60.0
    assert mm_to_m(25) == 0.025
    assert math.isclose(cm3_to_m3(50), 50e-6)
    assert math.isclose(rpm_to_rad_s(60), 2 * math.pi)
    assert math.isclose(cc_per_rev_to_m3_per_rad(10), 10e-6 / (2 * math.pi))
