from steering_sim.hydraulics.graph import HydraulicZeroJunction


def test_zero_junction_common_pressure_and_flow_balance():
    assert HydraulicZeroJunction.common_pressure_residuals([2e6, 2e6, 2e6]) == (0.0, 0.0)
    assert abs(HydraulicZeroJunction.flow_balance_m3_s([1e-4, -4e-5, -6e-5])) < 1e-15
