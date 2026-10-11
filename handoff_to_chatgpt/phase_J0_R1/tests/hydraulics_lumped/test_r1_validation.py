import csv
import json
import math
from pathlib import Path

import numpy as np

from steering_sim.hydraulics_lumped import LumpedHydraulicSystem, SystemInputs
from steering_sim.hydraulics_lumped.simulation import simulate_rk4

AUDIT = Path("hydraulic_audit_lumped")


def test_time_varying_inputs_are_evaluated_at_rk_stages(model):
    calls = []
    speeds = [c.pump.nominal_speed for c in model.channels]
    def inputs(t):
        calls.append(t)
        motion={c.actuator_alias:(0.0,0.0,0.0) for c in model.channels}
        return SystemInputs([1.0+0.001*math.sin(2*math.pi*t),1,1,1], speeds, [0]*4,
                            prescribed_motion_by_alias=motion)
    simulate_rk4(model, .002, .001, inputs)
    assert len(set(calls)) >= 5
    assert min(calls) == 0 and max(calls) == .002


def test_hydraulic_channel_binding_uses_two_shared_supplies(model):
    assert [c.actuator_alias for c in model.channels] == ["actuator002","actuator001","actuator001_1","actuator001_2"]
    assert model.channels[0].pump_aliases == ("pump01","pump01_1")
    assert {c.supply_group for c in model.channels} == {"supply_front","supply_rear"}
    assert sum(c.supply_group == "supply_rear" for c in model.channels) == 3


def test_pressure_sensor_location_is_documented():
    text=(AUDIT/"31H_supply_pressure_identifiability.md").read_text(encoding="utf-8")
    assert "pump-outlet" in text and "not valve-manifold pressure" in text


def test_supply_flow_balance(model):
    motion={c.actuator_alias:(0.0,0.0,0.0) for c in model.channels}
    u=SystemInputs([1,1,1,1],[c.pump.nominal_speed for c in model.channels],[0]*4,
                   prescribed_motion_by_alias=motion)
    _,out=model.evaluate(0,model.initial_state(),u)
    assert all(abs(item["supply_balance_residual"]) <= 1e-9 for item in out)
    assert all(abs(item["return_absorbed_flow"]) <= 1e-9 for item in out)
    assert out[1]["group_pump_flow"] > out[1]["relief_flow"]  # pprv + auxiliary paths


def test_valve_direction_and_sign(model):
    speeds=[c.pump.nominal_speed for c in model.channels]
    motion={c.actuator_alias:(0.0,0.0,0.0) for c in model.channels}
    _,full=model.evaluate(0,model.initial_state(),SystemInputs([1,1,1,1],speeds,[0]*4,
        prescribed_motion_by_alias=motion))
    _,partial=model.evaluate(0,model.initial_state(),SystemInputs([.9,1,1,1],speeds,[0]*4,
        prescribed_motion_by_alias=motion))
    # J0-R1 F2：前阀工作口换位后，SC_1 local A 不再被隔离，前缸两腔都有真实阀口
    # 流量。原断言 "full[0]['QA'] == partial[0]['QA'] == 0.0" 记录的是 A 腔被硬置零
    # 的旧拓扑，属于需要按新拓扑更新的旧预期，而不是可以保留的行为。
    assert full[0]["QA"] != pytest.approx(0.0)
    assert full[0]["QA"] != pytest.approx(partial[0]["QA"])
    assert full[0]["QB"] != pytest.approx(partial[0]["QB"])


def test_sine_plot_data_consistency():
    rows=list(csv.DictReader((AUDIT/"31F_paired_python_timeseries.csv").open(encoding="utf-8-sig")))
    sine=[r for r in rows if r["scenario"]=="S2"]
    commands=np.array([float(r["command"]) for r in sine])
    assert commands.max() == pytest.approx(.1,rel=1e-6)
    assert commands.min() == pytest.approx(-.1,rel=1e-6)
    assert np.ptp([float(r["position"]) for r in sine])>0


def test_time_step_convergence_gate():
    rows=list(csv.DictReader((AUDIT/"31I_time_step_convergence.csv").open(encoding="utf-8-sig")))
    passed=[float(r["dt_s"]) for r in rows if r["status"]=="PASS"]
    assert max(passed)==pytest.approx(.0005)
    assert all(r["status"].startswith("NUMERICAL_FAILURE") for r in rows if float(r["dt_s"])>=.001)


def test_linearization_gain_is_computed_not_placeholder():
    rows=list(csv.DictReader((AUDIT/"31K_linearization_validation.csv").open(encoding="utf-8-sig")))
    dynamic=[r for r in rows if r["operating_point"]!="neutral"]
    assert all(float(r["equilibrium_residual_inf"])<1e-4 for r in dynamic)
    assert all(r["gain_source"]=="-C pinv(A) B + D" for r in dynamic)
    assert all(float(r["dc_gain_m_per_command"])!=1.0 for r in dynamic)


def test_paired_scenario_validation_is_honest():
    result=json.loads((AUDIT/"31L_phase_L1_R1_results.json").read_text())
    assert result["amesim_scenarios_successful"]==1
    assert result["amesim_scenarios_requested"]==3
    assert result["ready_for_mechanical_integration"] is False


import pytest
