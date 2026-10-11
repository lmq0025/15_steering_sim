import pytest
from steering_sim.hydraulics_lumped.actuator import actuator_rates


def test_actuator_transformer_force(model):
    """J0-R1 F1：力的方向必须与 chamber_volumes 的容积约定自洽。

    ``V_a = V_a0 - A_a*x``、``V_b = V_b0 + A_b*x`` ⟹ x 增大压缩 A 腔、扩张 B 腔
    ⟹ A 腔压力把活塞推向 -x、B 腔压力推向 +x：

        F_hyd = A_b*p_b - A_a*p_a

    本用例原写作 ``A_a*p_a - A_b*p_b``，是把力与容积约定写反的旧预期。
    """
    c = model.channels[0]
    r = actuator_rates(2e6, 1e6, 0.0, 0.0, 0.0, 0.0, 0.0, c.actuator, c.fluid)
    assert r.hydraulic_force == pytest.approx(c.actuator.area_b*1e6 - c.actuator.area_a*2e6)
    assert r.hydraulic_force < 0.0


def test_pressurised_chamber_pushes_to_expand_itself(model):
    """同一约定的两个直接推论：A 腔受压向 -x，B 腔受压向 +x。"""
    c = model.channels[0]
    p0 = 1.0e6
    a_only = actuator_rates(p0 + 2e6, p0, 0.0, 0.0, 0.0, 0.0, 0.0, c.actuator, c.fluid)
    b_only = actuator_rates(p0, p0 + 2e6, 0.0, 0.0, 0.0, 0.0, 0.0, c.actuator, c.fluid)
    assert a_only.dv < 0.0
    assert b_only.dv > 0.0
