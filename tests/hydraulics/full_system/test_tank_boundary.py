from pathlib import Path

from steering_sim.hydraulics.solver import FastHydraulicModel

ROOT = Path(__file__).resolve().parents[3]


def test_tank_boundary_is_zero_gauge_pressure():
    model = FastHydraulicModel.from_ir(ROOT / "hydraulic_audit")
    x = model.initial_state.copy()
    z = model.solve_algebraic(0.0, x, {"pump_speed_rad_s": 0.0})
    assert model.tank_nodes
    assert all(abs(z.junction_pressure_pa[index]) < 1.0e-6 for index in model.tank_nodes)

