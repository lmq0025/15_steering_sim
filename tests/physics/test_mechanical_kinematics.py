from pathlib import Path
import numpy as np
import pytest
from steering_sim.mechanics import (
    ACTUATOR_ORDER, GENERALIZED_COORDINATES, SixAxleSteeringKinematics,
    UnreachableGeometryError, reference_geometry_from_file, verify_json_crosscheck,
)

SPEC = Path(__file__).parents[2] / "mechanical_model_input_spec_v1.0.yaml"
JSON_SPEC = SPEC.with_suffix(".json")

@pytest.fixture
def reference():
    if not SPEC.exists():
        pytest.skip("frozen CUSTOMER geometry is supplied outside Git")
    return reference_geometry_from_file(SPEC)

@pytest.fixture
def model(reference):
    return SixAxleSteeringKinematics(reference)

def test_zero_configuration_reconstructs_customer_points(model, reference):
    solution = model.solve(np.zeros(5))
    errors = [np.linalg.norm(solution.hardpoints[name] - point.position)
              for name, point in reference.points.items()]
    assert max(errors) < 1e-12

def test_json_crosscheck_matches_primary_yaml():
    if not SPEC.exists() or not JSON_SPEC.exists():
        pytest.skip("frozen CUSTOMER geometry is supplied outside Git")
    primary_hash, json_hash = verify_json_crosscheck(SPEC, JSON_SPEC)
    assert primary_hash == json_hash

def test_rigid_link_invariance_during_allowed_scan(model, reference):
    maximum = 0.0
    for direction in (-1.0, 1.0):
        model.reset()
        for magnitude in np.linspace(0.0, 0.08, 17):
            solution = model.solve(np.full(5, direction * magnitude))
            for name, length in solution.rigid_link_lengths.items():
                maximum = max(maximum, abs(length - reference.links[name].reference_length))
    assert maximum < 1e-9

def test_mirror_symmetry_is_equivariant(reference):
    plus = SixAxleSteeringKinematics(reference).solve(np.full(5, 0.05))
    minus = SixAxleSteeringKinematics(reference).solve(np.full(5, -0.05))
    reflection = np.array([1.0, -1.0])
    for point_id in reference.points:
        if point_id.endswith("_SRC"):
            mirror_id = point_id.replace("_SRC", "_MIRROR")
            assert np.allclose(plus.hardpoints[point_id] * reflection,
                               minus.hardpoints[mirror_id], atol=1e-10)

def test_front_group_has_one_independent_dof(model):
    assert model.group_dofs["AXLE_1_2"] == 1
    assert GENERALIZED_COORDINATES[0] == "q_front"
    baseline = model.solve(np.zeros(5))
    moved = model.solve(np.array([0.02, 0, 0, 0, 0]))
    changed = [name for name in moved.body_angles
               if abs(moved.body_angles[name] - baseline.body_angles[name]) > 1e-8]
    assert changed and all(name.startswith(("SWING_1_", "SWING_2_", "WHEEL_1_", "WHEEL_2_")) for name in changed)

def test_each_rear_axle_has_one_independent_dof(model):
    assert model.dof == 5
    for axle, q_index in zip(range(3, 7), range(1, 5)):
        assert model.group_dofs[f"AXLE_{axle}"] == 1
        q = np.zeros(5); q[q_index] = 0.02
        solution = model.solve(q)
        mean_swing = 0.5 * (solution.swing_angles[f"SWING_{axle}_NEG_Y"]
                            + solution.swing_angles[f"SWING_{axle}_POS_Y"])
        assert mean_swing == pytest.approx(0.02)

def test_actuator_lengths_vary_continuously(model):
    previous = None
    for value in np.linspace(-0.08, 0.08, 65):
        lengths = np.array(list(model.actuator_length(np.array([0, value, value, value, value])).values()))
        assert np.all(np.isfinite(lengths)) and np.all(lengths > 0)
        if previous is not None:
            assert np.max(np.abs(lengths - previous)) < 2e-3
        previous = lengths

def test_actuator_velocity_matches_finite_difference(model):
    q = np.array([0.01, -0.02, 0.015, -0.01, 0.02])
    q_dot = np.array([0.2, -0.1, 0.15, 0.08, -0.12])
    h = 1e-6
    plus = np.array(list(model.actuator_length(q + h * q_dot).values()))
    minus = np.array(list(model.actuator_length(q - h * q_dot).values()))
    finite_difference = (plus - minus) / (2 * h)
    velocity = np.array(list(model.actuator_velocity(q, q_dot).values()))
    assert np.max(np.abs(finite_difference - velocity)) < 1e-8

def test_all_constraint_residuals_below_declared_tolerance(model):
    maximum = 0.0
    for direction in (-1.0, 1.0):
        model.reset()
        for magnitude in np.linspace(0.0, 0.08, 17):
            residuals = model.solve(np.full(5, direction * magnitude)).constraint_residuals.values()
            maximum = max(maximum, max(map(abs, residuals)))
    assert maximum < 1e-10

def test_small_step_scan_stays_on_continuous_branch(model):
    for direction in (-1.0, 1.0):
        model.reset(); previous = None
        for magnitude in np.linspace(0.0, 0.08, 65):
            angles = np.array(list(model.solve(np.full(5, direction * magnitude)).body_angles.values()))
            if previous is not None:
                assert np.max(np.abs(angles - previous)) < 0.02
            previous = angles

def test_unreachable_geometry_raises_clear_error(model):
    with pytest.raises(UnreachableGeometryError, match="unreachable"):
        model.solve(np.full(5, 0.20))

def test_actuator_jacobian_has_two_outputs_per_rear_dof(model):
    jacobian = model.actuator_jacobian(np.zeros(5))
    assert jacobian.shape == (8, 5)
    assert len(ACTUATOR_ORDER) == 8
    assert np.allclose(jacobian[:, 0], 0.0)
    for column in range(1, 5):
        assert np.count_nonzero(np.abs(jacobian[:, column]) > 1e-12) == 2
