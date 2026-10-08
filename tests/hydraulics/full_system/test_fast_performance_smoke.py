from pathlib import Path

from steering_sim.hydraulics.solver import FastHydraulicModel

ROOT = Path(__file__).resolve().parents[3]


def test_performance_smoke_records_solver_counters_without_wall_time_assertion():
    result = FastHydraulicModel.from_ir(ROOT / "hydraulic_audit").simulate(0.001, {"pump_speed_rad_s": 0.0}, output_points=2)
    assert result.success
    assert result.wall_time_s > 0.0
    assert result.nfev > 0
