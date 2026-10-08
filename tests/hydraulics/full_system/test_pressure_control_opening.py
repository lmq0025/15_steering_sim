from pathlib import Path

from steering_sim.hydraulics.solver import FastHydraulicModel

ROOT = Path(__file__).resolve().parents[3]


def test_rv010_deterministically_opens_only_above_threshold():
    model = FastHydraulicModel.from_ir(ROOT / "hydraulic_audit")
    branch = next(item for item in model.branches if item.alias == "presscontrol01_3")
    below, _ = model._flow_and_derivative(branch, -14999999.0, {})
    above, _ = model._flow_and_derivative(branch, -15000001.0, {})
    assert below == 0.0
    assert above < 0.0

