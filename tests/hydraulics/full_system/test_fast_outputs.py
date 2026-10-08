from pathlib import Path

from steering_sim.hydraulics.solver import FastHydraulicModel

ROOT = Path(__file__).resolve().parents[3]


def test_key_outputs_include_pump_and_actuator_si_values():
    model = FastHydraulicModel.from_ir(ROOT / "hydraulic_audit")
    state, algebraic = model.initialize({"pump_speed_rad_s": 0.0})
    output = model.outputs(0.0, state, algebraic, {"pump_speed_rad_s": 0.0})
    assert {"pump01.flow_m3_s", "pump01.pin_pa", "actuator001.p1_pa", "actuator001.force_n"} <= output.keys()
