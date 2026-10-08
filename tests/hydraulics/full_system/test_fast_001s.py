from pathlib import Path

from steering_sim.hydraulics.solver import FastHydraulicModel

ROOT = Path(__file__).resolve().parents[3]


def test_fast_001_second_run():
    result = FastHydraulicModel.from_ir(ROOT / "hydraulic_audit").simulate(0.01, {"pump_speed_rad_s": 0.0}, output_points=3)
    assert result.success and result.time_s[-1] == 0.01
