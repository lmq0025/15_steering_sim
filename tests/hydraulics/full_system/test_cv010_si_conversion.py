import math
from pathlib import Path

from steering_sim.hydraulics.solver import FastHydraulicModel

ROOT = Path(__file__).resolve().parents[3]


def test_cv010_uses_metadata_gradient_in_si():
    model = FastHydraulicModel.from_ir(ROOT / "hydraulic_audit")
    branch = next(item for item in model.branches if item.alias == "presscontrol02")
    flow, derivative = model._flow_and_derivative(branch, -1000.0, {})
    expected_gradient = 500.0 * 1.66666666666667e-10
    assert math.isclose(flow, -expected_gradient * 1000.0, rel_tol=1.0e-12)
    assert math.isclose(derivative, expected_gradient, rel_tol=1.0e-12)

