from pathlib import Path

from steering_sim.hydraulics.solver import FastHydraulicModel

ROOT = Path(__file__).resolve().parents[3]


def test_49_groups_are_classified_and_warm_started():
    model = FastHydraulicModel.from_ir(ROOT / "hydraulic_audit")
    assert len(model.groups) == 49
    assert {group.category for group in model.groups} <= {"EXPLICIT", "LINEAR", "SMALL_NONLINEAR", "SWITCHING"}
    state, _ = model.initialize({"pump_speed_rad_s": 0.0})
    model.solve_algebraic(0.0, state, {"pump_speed_rad_s": 0.0})
    diagnostics = model.aggregate_algebraic_diagnostics()
    assert diagnostics.failures == 0
    assert diagnostics.warm_start_hits > 0
