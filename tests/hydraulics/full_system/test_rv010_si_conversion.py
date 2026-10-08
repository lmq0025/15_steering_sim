import math
from pathlib import Path

from steering_sim.hydraulics.solver import FastHydraulicModel

ROOT = Path(__file__).resolve().parents[3]


def test_rv010_uses_source_cracking_pressure_and_gradient():
    model = FastHydraulicModel.from_ir(ROOT / "hydraulic_audit")
    branch = next(item for item in model.branches if item.alias == "presscontrol01")
    gradient = 500.0 * 1.66666666666667e-10
    closed, _ = model._flow_and_derivative(branch, -15.9e6, {})
    opened, derivative = model._flow_and_derivative(branch, -16.1e6, {})
    assert closed == 0.0
    assert math.isclose(opened, -gradient * 0.1e6, rel_tol=1.0e-12)
    assert math.isclose(derivative, gradient, rel_tol=1.0e-12)

