from pathlib import Path

from steering_sim.hydraulics.solver import FastHydraulicModel

ROOT = Path(__file__).resolve().parents[3]


def test_fast_runtime_uses_amesim_gauge_pressure_reference():
    model = FastHydraulicModel.from_ir(ROOT / "hydraulic_audit")
    assert model._pressure_reference_pa == 0.0
    assert len(model.system.states) == 109

