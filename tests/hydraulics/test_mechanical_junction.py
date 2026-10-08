from steering_sim.hydraulics.graph import MechanicalOneJunction


def test_translation_one_junction_common_velocity_force_balance():
    j = MechanicalOneJunction("TMJ_001", "translation")
    assert j.common_flow_residuals([0.2, 0.2, 0.2]) == (0.0, 0.0)
    assert j.effort_balance([100.0, -60.0, -40.0]) == 0.0


def test_rotation_one_junction_common_speed_torque_balance():
    j = MechanicalOneJunction("RMJ_001", "rotation")
    assert j.common_flow_residuals([10.0, 10.0]) == (0.0,)
    assert j.effort_balance([5.0, -5.0]) == 0.0
