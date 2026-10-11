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
        return SystemInputs([0.001*math.sin(2*math.pi*t),0,0,0], speeds, [0]*4)
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
    u=SystemInputs([0,0,0,0],[c.pump.nominal_speed for c in model.channels],[0]*4)
    _,out=model.evaluate(0,model.initial_state(),u)
    assert out[0]["group_pump_flow"] == pytest.approx(out[0]["relief_flow"], rel=1e-9)
    assert out[1]["group_pump_flow"] == pytest.approx(out[1]["relief_flow"], rel=1e-9)


def test_valve_direction_and_sign(model):
    speeds=[c.pump.nominal_speed for c in model.channels]
    _,pos=model.evaluate(0,model.initial_state(),SystemInputs([.01,0,0,0],speeds,[0]*4))
    _,neg=model.evaluate(0,model.initial_state(),SystemInputs([-.01,0,0,0],speeds,[0]*4))
    # IR V3 shows dirvalve_6 local work ports 3/4 connected to the
    # actuator002 B/A chambers.  The physical chamber sign is therefore the
    # reverse of a generic, unswapped four-way valve.
    assert pos[0]["QA"]<=0 and pos[0]["QB"]>0
    assert neg[0]["QA"]>0 and neg[0]["QB"]<=0


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
