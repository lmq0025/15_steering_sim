from pathlib import Path

from steering_sim.hydraulics.solver import FastHydraulicModel

ROOT = Path(__file__).resolve().parents[3]


def test_initial_algebraic_groups_have_no_failures():
    model = FastHydraulicModel.from_ir(ROOT / "hydraulic_audit")
    model.initialize({"pump_speed_rad_s": 0.0})
    assert model.aggregate_algebraic_diagnostics().failures == 0
