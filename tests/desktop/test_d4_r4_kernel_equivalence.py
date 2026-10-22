"""Independent R3/R4 equation checks; no closed-loop integrations.

The reference modules are loaded from the protected local pre-R4 snapshot
using their original qualified names while executing their source. Module
bindings are restored immediately afterward; the independent class/function
objects remain available for direct old/new comparisons.
"""
from dataclasses import asdict
import importlib
import importlib.util
import json
import math
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / "outputs/desktop/r4/baseline_r3/src/steering_sim"
MODULE_NAMES = (
    "steering_sim.hydraulics_engineering.parameters",
    "steering_sim.hydraulics_engineering.model",
    "steering_sim.j0_coupling.geometry",
    "steering_sim.j0_coupling.road_load",
)


@pytest.fixture(scope="module")
def modules():
    current = {name: importlib.import_module(name) for name in MODULE_NAMES}
    reference = {}
    try:
        for name in MODULE_NAMES:
            relative = Path(*name.split(".")[1:]).with_suffix(".py")
            path = SNAPSHOT / relative
            assert path.is_file(), f"Required pre-R4 reference source absent: {path}"
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            reference[name] = module
    finally:
        sys.modules.update(current)
    return SimpleNamespace(
        parameters=current[MODULE_NAMES[0]], model=current[MODULE_NAMES[1]],
        geometry=current[MODULE_NAMES[2]], road=current[MODULE_NAMES[3]],
        old_parameters=reference[MODULE_NAMES[0]], old_model=reference[MODULE_NAMES[1]],
        old_geometry=reference[MODULE_NAMES[2]], old_road=reference[MODULE_NAMES[3]])


def _raw_parameters(degraded=False):
    raw = json.loads((ROOT / "configs/j1r2/engineering_hydraulics.json").read_text(encoding="utf-8"))
    if degraded:
        raw["degradation"] = {
            "pump_volumetric_efficiency": .94, "pump_internal_leakage_m3_s_per_pa": 1e-13,
            "valve_flow_coefficient_scale": .9, "valve_lag_scale": 1.4,
            "cylinder_internal_leakage_m3_s_per_pa": 2e-13, "cylinder_friction_scale": 1.2,
            "supply_pressure_scale": .95,
            "pumps": {"front": {"volumetric_efficiency": .8, "internal_leakage_m3_s_per_pa": 2e-12,
                                  "mechanical_efficiency": .7, "rated_drive_power_w": 15000.}},
            "valves": {"channel_front": {"internal_leakage_m3_s_per_pa": 8e-12,
                                          "lag_scale": 7., "flow_coefficient_scale": .8}},
            "cylinders": {"channel_rear_2": {"internal_leakage_m3_s_per_pa": 3e-12,
                                              "friction_scale": 3.}},
        }
    return raw


@pytest.mark.parametrize("degraded", [False, True])
def test_complete_22_state_rhs_and_outputs_match_r3_for_random_physical_states(modules, degraded):
    old_parameters = modules.old_parameters.parameters_from_dict(_raw_parameters(degraded))
    parameters = modules.parameters.parameters_from_dict(_raw_parameters(degraded))
    old = modules.old_model.EngineeringHydraulicSystem(old_parameters)
    new = modules.model.EngineeringHydraulicSystem(parameters)
    rng = np.random.default_rng(73421)
    np.testing.assert_array_equal(old.neutral_state(), new.neutral_state())
    for _ in range(96):
        state = new.neutral_state()
        state[-2:] = rng.uniform(-8e4, 3.5e7, 2)
        for index, channel in enumerate(parameters.channels):
            cylinder = channel.cylinder; base = 5*index
            # Includes reverse flow, over-supply chamber pressures, commands
            # outside their limit, negative spool and active end-stop forces.
            state[base:base+2] = rng.uniform(-8e4, 4e7, 2)
            state[base+2] = cylinder.stroke_offset_m + cylinder.half_stroke_m*rng.uniform(-1.005, 1.005)
            state[base+3] = rng.uniform(-.15, .15)
            state[base+4] = rng.uniform(-1.5, 1.5)
        inputs = SimpleNamespace(valve_commands=tuple(rng.uniform(-2., 2., 4)),
                                 external_load_forces_n=tuple(rng.uniform(-4e4, 4e4, 4)))
        a, oa = old.evaluate(.7, state, inputs)
        b, ob = new.evaluate(.7, state, inputs)
        derivative_only, discarded = new.evaluate(.7, state, inputs, include_output=False)
        # This first optimization only reuses identical expressions; in this
        # isolated hydraulic kernel every float must remain bitwise equal.
        np.testing.assert_array_equal(a, b)
        np.testing.assert_array_equal(b, derivative_only)
        assert discarded is None
        assert asdict(oa) == asdict(ob)


def test_reversal_leakage_and_drive_power_are_not_conflated(modules):
    old = modules.old_model.EngineeringHydraulicSystem(
        modules.old_parameters.parameters_from_dict(_raw_parameters(True)))
    new = modules.model.EngineeringHydraulicSystem(
        modules.parameters.parameters_from_dict(_raw_parameters(True)))
    for sign in (-1., 0., 1.):
        state = new.neutral_state(); state[-2:] = (2e7, 2.3e7)
        state[0:2] = (3.5e7, -5e4); state[4] = sign
        inputs = SimpleNamespace(valve_commands=(sign, -sign, sign, -sign),
                                 external_load_forces_n=(0.,)*4)
        a, oa = old.evaluate(0., state, inputs); b, ob = new.evaluate(0., state, inputs)
        np.testing.assert_array_equal(a, b); assert asdict(oa) == asdict(ob)
        if sign > 0:
            assert ob.channels[0].supply_flow_m3_s < 0., "chamber-to-supply reverse flow must remain signed"
        assert ob.channels[0].valve_leakage_flow_m3_s > 0.
        assert new.available_pump_flow("front", 2e7) == old.available_pump_flow("front", 2e7)


@pytest.mark.parametrize("failure", ["negative_volume", "nan_velocity", "nan_command"])
def test_invalid_physical_or_numeric_inputs_still_fail_explicitly(modules, failure):
    for params_module, model_module in ((modules.old_parameters, modules.old_model),
                                       (modules.parameters, modules.model)):
        system = model_module.EngineeringHydraulicSystem(params_module.parameters_from_dict(_raw_parameters()))
        state = system.neutral_state(); commands = [0.]*4
        if failure == "negative_volume": state[2] = 100.
        if failure == "nan_velocity": state[3] = np.nan
        if failure == "nan_command": commands[0] = np.nan
        with pytest.raises(model_module.EngineeringHydraulicError):
            system.evaluate(0., state, SimpleNamespace(valve_commands=commands, external_load_forces_n=(0.,)*4))
        if model_module is modules.model:
            with pytest.raises(model_module.EngineeringHydraulicError):
                system.evaluate(0., state, SimpleNamespace(valve_commands=commands,
                    external_load_forces_n=(0.,)*4), include_output=False)


def test_effective_wear_cache_observes_local_mapping_replacement_and_globals(modules):
    def exercise(module):
        pumps, valves, cylinders = {}, {}, {}
        wear = module.DegradationParameters(pumps=pumps, valves=valves, cylinders=cylinders,
            pump_volumetric_efficiency=.9, pump_internal_leakage_m3_s_per_pa=1e-13,
            valve_flow_coefficient_scale=.8, valve_lag_scale=2.,
            cylinder_internal_leakage_m3_s_per_pa=2e-13, cylinder_friction_scale=1.2)
        snapshots = []
        def record():
            snapshots.append([asdict(wear.pump("front")), asdict(wear.pump("rear")),
                              asdict(wear.valve("channel_front")), asdict(wear.valve("channel_rear_1")),
                              asdict(wear.cylinder("channel_rear_2")), asdict(wear.cylinder("channel_rear_3"))])
        record(); record()
        pumps["front"] = module.PumpDegradationParameters(.7, 1e-12, .6, 10000.)
        valves["channel_front"] = module.ValveDegradationParameters(2e-12, .9, 3.)
        cylinders["channel_rear_2"] = module.CylinderDegradationParameters(3e-12, 4.)
        record()
        del pumps["front"]; del valves["channel_front"]; del cylinders["channel_rear_2"]
        record()
        return snapshots
    a, b = exercise(modules.old_parameters), exercise(modules.parameters)
    assert a == b
    assert b[0] == b[1] == b[3]
    assert b[2][0] != b[0][0] and b[2][1] == b[0][1]
    assert b[2][2] != b[0][2] and b[2][3] == b[0][3]
    assert b[2][4] != b[0][4] and b[2][5] == b[0][5]
    # Different global factors with equal local values must not share a result.
    low = modules.parameters.DegradationParameters(valve_lag_scale=1.)
    high = modules.parameters.DegradationParameters(valve_lag_scale=9.)
    assert high.valve("channel_front").lag_scale == 9*low.valve("channel_front").lag_scale


def centers():
    return {f"axle{a}_{side}": (x, y) for a, x in enumerate((0., -1.6, -4., -5.2, -6.7, -8.4), 1)
            for side, y in (("left", 1.9), ("right", -1.9))}


def test_curvature_matches_near_straight_cutoff_and_large_angles(modules):
    wheel_centers = centers(); rng = np.random.default_rng(819)
    threshold = math.degrees(math.atan(.01))  # tan(theta)^2 = the 1e-4 SVD ratio
    sequences = [{wheel: 0. for wheel in wheel_centers}]
    for scale in (1-1e-8, 1-1e-12, 1., 1+1e-12, 1+1e-8, 4.):
        sequences.append({wheel: (-1 if i%2 else 1)*threshold*scale
                          for i, wheel in enumerate(wheel_centers)})
    sequences.extend({wheel: float(angle) for wheel, angle in zip(wheel_centers, rng.uniform(-35, 35, 12))}
                     for _ in range(40))
    for angles in sequences:
        a = modules.old_road.actual_curvature_1pm(angles, wheel_centers)
        b = modules.road.actual_curvature_1pm(angles, wheel_centers)
        assert [value is None for value in a] == [value is None for value in b]
        np.testing.assert_allclose([v for v in a if v is not None], [v for v in b if v is not None],
                                   atol=2e-10, rtol=2e-13)
    assert modules.road.actual_curvature_1pm({}, {}) == (0., None, None, 0.)


def test_lateral_distribution_cache_responds_to_axle_mass_and_geometry_changes(modules):
    adapter = SimpleNamespace(model=SimpleNamespace(centers=centers()))
    for masses in (np.array([11500.]*6), np.array([2000., 5000., 0., 30000., 1000., 9000.]), np.zeros(6)):
        for force in (0., 1e-16, -30000., 1e6):
            np.testing.assert_array_equal(
                modules.old_road._allocate_lateral_force(adapter, force, masses),
                modules.road._allocate_lateral_force(adapter, force, masses))
    masses = np.array([2000., 5000., 0., 30000., 1000., 9000.])
    before = modules.road._allocate_lateral_force(adapter, 1e5, masses)
    # Change cached key inputs in place; no stale operator is permissible.
    masses[0] = 18000.
    changed = modules.road._allocate_lateral_force(adapter, 1e5, masses)
    assert not np.array_equal(before, changed)
    np.testing.assert_array_equal(changed, modules.old_road._allocate_lateral_force(adapter, 1e5, masses))
    adapter.model.centers["axle6_left"] = (-12., 1.9)
    actual = modules.road._allocate_lateral_force(adapter, 1e5, masses)
    np.testing.assert_array_equal(actual, modules.old_road._allocate_lateral_force(adapter, 1e5, masses))
    # Geometry change may leave the force fractions unchanged because the CG
    # follows the same masses, but it must produce a distinct keyed operator.
    assert modules.road._lateral_operator.cache_info().currsize >= 3


class RoadFixture:
    """Cheap explicit algebraic input fixture, never used as a production model."""
    def __init__(self):
        self.model = SimpleNamespace(centers=centers(), config={"ground_load": {
            "gravity_mps2": 9.80665, "cornering_stiffness_per_wheel_N_per_rad": 180000.,
            "effective_trail_m": .15, "pivot_effective_radius_m": .11,
            "pivot_transition_speed_kmh": 8., "pivot_engagement_angle_deg": 2.,
            "linear_slip_limit_deg": 5.}})
        self.singular = False

    def wheel_angles_deg(self, q):
        angles = {wheel: 0. for wheel in centers()}
        for dof, wheels in (("q_front", ("axle1_left", "axle1_right", "axle2_left", "axle2_right")),
                           ("q4", ("axle4_left", "axle4_right")), ("q5", ("axle5_left", "axle5_right")),
                           ("q6", ("axle6_left", "axle6_right"))):
            for i, wheel in enumerate(wheels): angles[wheel] = math.degrees(q[dof])*(1+.02*i)
        return angles

    def wheel_angle_jacobian(self, q):
        from steering_sim.j0_coupling.geometry import DOF_WHEELS
        return {dof: {wheel: 1+.02*i for i, wheel in enumerate(wheels)} for dof, wheels in DOF_WHEELS.items()}

    def stroke_jacobian(self, dof, q):
        return 0. if self.singular and dof == "q5" else {"q_front": .25, "q4": .2, "q5": -.2, "q6": -.25}[dof]


@pytest.mark.parametrize("speed,mu,masses,singular", [
    (0., .8, (11.5,)*6, False), (5., .8, (11.5,)*6, False),
    (80., .05, (11.5,)*6, False), (80., 0., (11.5,)*6, False),
    (0., .8, (0.,)*6, False), (30., .75, (5., 10., 20., 0., 8., 16.), True),
])
def test_road_load_flags_and_forces_match_across_physical_boundaries(modules, speed, mu, masses, singular):
    adapter = RoadFixture(); adapter.singular = singular
    q = {"q_front": .3, "q4": -.1, "q5": -.2, "q6": -.4}
    kwargs = dict(speed_kmh=speed, friction_coefficient=mu, axle_mass_t=masses,
                  curvature_1pm=.07, singular_threshold_m_per_rad=1e-6)
    a = modules.old_road.road_load(adapter, q, **kwargs)
    b = modules.road.road_load(adapter, q, **kwargs)
    assert a.flags == b.flags
    assert a.curvature_source == b.curvature_source
    for key, value in asdict(a).items():
        other = asdict(b)[key]
        if isinstance(value, dict):
            assert value.keys() == other.keys()
            np.testing.assert_allclose(list(value.values()), list(other.values()), atol=1e-8, rtol=2e-13, equal_nan=True)
        elif isinstance(value, (int, float)):
            np.testing.assert_allclose(value, other, atol=1e-8, rtol=2e-13, equal_nan=True)
        else: assert value == other
    if speed == 80.:
        assert "ADHESION_INFEASIBLE" in b.flags
    if singular:
        assert "q5:LOAD_CONVERSION_SINGULAR" in b.flags and math.isnan(b.hydraulic_load_force_n["q5"])


def _table(module, descending):
    q = np.linspace(-.5, .5, 1001)
    stroke = (.25*q + .03*q**3)*(-1 if descending else 1)
    return module._DofTable("q5", q, {"axle5_left": np.sin(q), "axle5_right": .98*np.sin(q)},
                            stroke, stroke.copy(), -.95*stroke, np.zeros_like(q), np.ones_like(q))


@pytest.mark.parametrize("descending", [False, True])
def test_table_interpolation_and_envelope_statuses_are_unchanged(modules, descending, monkeypatch):
    old_table = _table(modules.old_geometry, descending); table = _table(modules.geometry, descending)
    for q in np.r_[np.linspace(-.51, .51, 101), -.5, 0., .5]:
        for method, args in (("angle", ("axle5_left", q)), ("angle_jacobian", ("axle5_right", q)),
                             ("stroke", (q,)), ("stroke_jacobian", (q,))):
            assert getattr(old_table, method)(*args) == getattr(table, method)(*args)
    old = object.__new__(modules.old_geometry.J0GeometryAdapter)
    new = object.__new__(modules.geometry.J0GeometryAdapter)
    for adapter, tab in ((old, old_table), (new, table)):
        adapter.tables = {"q5": tab}; adapter._envelope_tolerance_m = .002
        adapter.config = SimpleNamespace(mapping={"singular_jacobian_threshold_m_per_rad": 1e-6})
    low, high = sorted((table.stroke_repr[0], table.stroke_repr[-1]))
    for x in np.r_[np.linspace(low, high, 100), low-.003, low-.001, low, high, high+.001, high+.003]:
        a, status_a = old.q_from_stroke("q5", x); b, status_b = new.q_from_stroke("q5", x)
        assert a == b and asdict(status_a) == asdict(status_b)
    # Optional NumPy internal entry is an acceleration only: public fallback
    # must retain identical behavior for supported real float64 tables.
    monkeypatch.setattr(modules.geometry, "_real_interp", np.interp)
    for x in np.linspace(low, high, 30):
        assert table.q_from_stroke(x) == old_table.q_from_stroke(x)
