import numpy as np

from steering_sim.hydraulics.elements import ComplianceLine, FixedOrifice, HJ020, PU001
from steering_sim.hydraulics.solver import ActuatorLoop, MinimalHydraulicLoop
from steering_sim.hydraulics.units import cc_per_rev_to_m3_per_rad, rpm_to_rad_s


def test_minimal_hydraulic_loop_bdf_reaches_finite_pressure():
    loop = MinimalHydraulicLoop(
        pump=PU001(cc_per_rev_to_m3_per_rad(10.0)),
        angular_speed_rad_s=rpm_to_rad_s(1350.0),
        line=ComplianceLine(2e-3, 1.7e9),
        return_restriction=FixedOrifice(2e-6, 850.0),
        tank_pressure_pa=1e5,
    )
    result = loop.simulate(0.05, 1e5)
    assert result.success and np.all(np.isfinite(result.state))
    assert result.state[0, -1] > 1e5


def test_actuator_loop_bdf_updates_pressure_and_motion():
    cylinder = HJ020(piston_diameter_m=0.025, rod_diameter_2_m=0.012, stroke_m=0.3,
                     dead_volume_1_m3=50e-6, dead_volume_2_m3=50e-6,
                     bulk_modulus_pa=1.7e9, leakage_m3_s_pa=2e-12,
                     viscous_friction_n_s_m=300.0)
    loop = ActuatorLoop(cylinder, FixedOrifice(2e-7, 850.0), FixedOrifice(2e-7, 850.0),
                        supply_pressure_pa=5e6, tank_pressure_pa=1e5, mass_kg=50.0, load_force_n=500.0)
    result = loop.simulate(0.02, np.array([1e5, 1e5, 0.15, 0.0]))
    assert result.success and np.all(np.isfinite(result.state))
    assert result.state[0, -1] > result.state[0, 0]
    assert result.state[2, -1] != result.state[2, 0]
