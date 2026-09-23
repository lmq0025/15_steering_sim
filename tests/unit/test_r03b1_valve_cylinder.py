from pathlib import Path

import numpy as np
import pytest

from steering_sim.hydraulics.r03b1_config import load_json_config
from steering_sim.hydraulics.r03b1_errors import UnresolvedAmesimUtilityError
from steering_sim.hydraulics.r03b1_factory import build_r03b1_rig
from steering_sim.hydraulics.valve_dynamics import StaticValveDynamics
from steering_sim.hydraulics.orifice import HYDVORF0Observation

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs" / "hydraulics" / "r03b1"


def test_static_valve_dynamics_has_no_state_and_ignores_saved_dynamic_parameters():
    model = StaticValveDynamics(-1.0, 1.0, mode=1)
    assert model.state_size == 0
    assert model.evaluate(0.25).spool == 0.25
    low = model.evaluate(-2.0)
    high = model.evaluate(2.0)
    assert (low.spool, low.clipped, low.active_endstop) == (-1.0, True, "minimum")
    assert (high.spool, high.clipped, high.active_endstop) == (1.0, True, "maximum")


def test_generated_configs_have_provenance_and_no_class_magic_values():
    for name in ("fluid_fp04.json", "actuator001_hj020.json", "dirvalve_6_sc1.json"):
        payload = load_json_config(CONFIG / name)
        assert payload["provenance"]["audit_file"].endswith("r03a25_resolved_key_parameters.csv")


def test_dirvalve6_openings_come_from_configuration():
    valve = build_r03b1_rig(CONFIG).valve
    assert valve.openings(-1.0).openings == {"P-B": 0.0, "P-A": 100.0, "T-B": 100.0, "T-A": 0.0}
    assert valve.openings(1.0).openings == {"P-B": 100.0, "P-A": 0.0, "T-B": 0.0, "T-A": 100.0}


def test_hj020_geometry_and_volumes_follow_official_source():
    cylinder = build_r03b1_rig(CONFIG).cylinder
    dp, dr = 0.0797884560802865, 0.0406842894512822
    assert cylinder.piston_area_m2 == pytest.approx(np.pi * dp**2 / 4)
    assert cylinder.rod_area_m2 == pytest.approx(np.pi * dr**2 / 4)
    assert cylinder.annular_area_m2 == pytest.approx(cylinder.piston_area_m2 - cylinder.rod_area_m2)
    for x in (0.0, cylinder.config.stroke_m / 2, cylinder.config.stroke_m):
        assert all(volume > 0 for volume in cylinder.chamber_volumes(x))


def test_hj020_force_sign_and_zero_leakage():
    cylinder = build_r03b1_rig(CONFIG).cylinder
    observation = cylinder.observe(np.array([2e6, 1e6]), 0.05, 0.01)
    expected = 2e6 * cylinder.piston_area_m2 - 1e6 * cylinder.annular_area_m2
    assert observation.force_n == pytest.approx(expected)
    assert observation.leakage_m3_s == 0.0


def test_hydvorf0_private_utility_is_explicit_blocker():
    valve = build_r03b1_rig(CONFIG).valve
    with pytest.raises(UnresolvedAmesimUtilityError, match="eqarea/orif3f"):
        valve.evaluate(0.5, 10e6, 0.0, 1e6, 1e6)


def test_hj020_private_pressure_utility_is_explicit_blocker():
    cylinder = build_r03b1_rig(CONFIG).cylinder
    with pytest.raises(UnresolvedAmesimUtilityError, match="pcdyn2_/q0top_"):
        cylinder.rhs(np.array([1e6, 1e6]), 0.0, 0.0, 0.05, 0.0)


def test_out_of_stroke_motion_is_not_silently_clipped():
    cylinder = build_r03b1_rig(CONFIG).cylinder
    with pytest.raises(ValueError, match="outside"):
        cylinder.chamber_volumes(-1e-3)


def test_sc1_port_bookkeeping_conserves_flow_for_any_path_law():
    rig = build_r03b1_rig(CONFIG)

    class TraceableStub:
        def flow(self, pressure_1_pa, pressure_2_pa, opening_signal):
            flow = opening_signal * 1e-9 + (pressure_1_pa - pressure_2_pa) * 1e-13
            return HYDVORF0Observation(opening_signal, opening_signal / 100.0, pressure_1_pa - pressure_2_pa, flow, False)

    rig.valve.orifices = {name: TraceableStub() for name in rig.valve.orifices}
    observation = rig.valve.evaluate(0.4, 10e6, 0.1e6, 2e6, 3e6)
    assert observation.flow_residual_m3_s == pytest.approx(0.0, abs=1e-18)
