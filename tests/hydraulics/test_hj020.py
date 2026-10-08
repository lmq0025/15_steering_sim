import math

from steering_sim.hydraulics.elements import HJ020


def make_cylinder():
    return HJ020(
        piston_diameter_m=0.025,
        rod_diameter_2_m=0.012,
        stroke_m=0.3,
        dead_volume_1_m3=50e-6,
        dead_volume_2_m3=50e-6,
        bulk_modulus_pa=1.7e9,
        leakage_m3_s_pa=0.5 * (1e-3 / 60) / 1e5,
    )


def test_hj020_geometry_force_and_leakage_sign():
    c = make_cylinder()
    assert math.isclose(c.area_1_m2, math.pi * 0.025**2 / 4)
    assert math.isclose(c.area_2_m2, math.pi * (0.025**2 - 0.012**2) / 4)
    assert c.force_n(10e6, 1e6, 0.0, 0.1) > 0.0
    assert c.leakage_flow_m3_s(10e6, 1e6) > 0.0
    assert c.leakage_flow_m3_s(1e6, 10e6) < 0.0


def test_hj020_volumes_and_pressure_rhs_signs():
    c = make_cylinder()
    v1, v2 = c.chamber_volumes_m3(0.1)
    assert v1 > 0.0 and v2 > 0.0
    dp1, dp2 = c.pressure_rhs_pa_s(1e6, 1e6, 1e-5, 0.0, 0.1, 0.0)
    assert dp1 > 0.0 and dp2 == 0.0
    # Positive extension consumes chamber-1 flow and injects chamber-2 volume.
    dp1, dp2 = c.pressure_rhs_pa_s(1e6, 1e6, 0.0, 0.0, 0.1, 0.01)
    assert dp1 < 0.0 and dp2 > 0.0
