from pathlib import Path

import numpy as np
import pytest
from scipy.integrate import solve_ivp

from steering_sim.core import ParameterSource
from steering_sim.mechanics import (
    ACTUATOR_ORDER, MissingMechanicalParameterError, ReducedMechanicalDynamics,
    SixAxleSteeringKinematics, SyntheticParameterUseError,
    inertial_body_inventory, load_mass_properties_csv, reference_geometry_from_file,
    uniform_slender_rod_estimate,
)


ROOT = Path(__file__).parents[2]
SPEC = ROOT / "mechanical_model_input_spec_v1.0.yaml"
TEMPLATE = ROOT / "configs/mechanics/mechanical_mass_properties_template.csv"
SYNTHETIC = ROOT / "data/example/mechanical_mass_properties_SYNTHETIC_TEST_ONLY.csv"


@pytest.fixture(scope="module")
def reference():
    if not SPEC.exists():
        pytest.skip("frozen CUSTOMER geometry is supplied outside Git")
    return reference_geometry_from_file(SPEC)


@pytest.fixture(scope="module")
def dynamics(reference):
    body_ids = tuple(reference.bodies) + tuple(reference.links)
    properties = load_mass_properties_csv(SYNTHETIC, body_ids)
    return ReducedMechanicalDynamics(
        SixAxleSteeringKinematics(reference), properties,
        allow_synthetic_test_only=True,
    )


def test_environment_documentation_uses_only_steering_sim():
    environment = (ROOT / "docs/ENVIRONMENT.md").read_text(encoding="utf-8")
    assert r"E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe" in environment
    formal_docs = [ROOT / "README.md", *ROOT.glob("docs/**/*.md")]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in formal_docs)
    assert "ProgramData\\anaconda3" not in combined
    assert "把 E:\\ProgramData\\anaconda3 放到 PATH" not in combined


def test_mass_parameter_completeness_and_synthetic_guard(reference):
    body_ids = tuple(reference.bodies) + tuple(reference.links)
    assert len(inertial_body_inventory(reference)) == len(body_ids)
    with pytest.raises(MissingMechanicalParameterError, match="missing required values"):
        load_mass_properties_csv(TEMPLATE, body_ids)
    synthetic = load_mass_properties_csv(SYNTHETIC, body_ids)
    assert all(item.source is ParameterSource.ASSUMED for item in synthetic)
    estimate = uniform_slender_rod_estimate("TEST_ROD", 1.2, 0.5)
    assert estimate.source is ParameterSource.ASSUMED
    assert "not customer engineering data" in estimate.notes
    with pytest.raises(SyntheticParameterUseError, match="synthetic numerical verification only"):
        ReducedMechanicalDynamics(SixAxleSteeringKinematics(reference), synthetic)


def test_mass_matrix_is_symmetric(dynamics):
    matrix = dynamics.mass_matrix(np.array([0.01, -0.015, 0.012, -0.008, 0.006]))
    assert matrix.shape == (5, 5)
    assert np.linalg.norm(matrix - matrix.T, ord=np.inf) < 1e-13


def test_mass_matrix_is_positive_definite(dynamics):
    for q in (np.zeros(5), np.array([0.02, -0.01, 0.015, -0.012, 0.008])):
        matrix = dynamics.mass_matrix(q)
        np.linalg.cholesky(matrix)
        assert np.linalg.eigvalsh(matrix)[0] > 0.0


def test_zero_velocity_bias_and_horizontal_gravity(dynamics):
    q = np.array([0.01, -0.015, 0.012, -0.008, 0.006])
    assert np.array_equal(dynamics.coriolis_centrifugal_bias(q, np.zeros(5)), np.zeros(5))
    assert np.array_equal(dynamics.gravity_generalized_force(q), np.zeros(5))


def test_kinetic_energy_matches_body_sum(dynamics):
    q = np.array([0.01, -0.015, 0.012, -0.008, 0.006])
    q_dot = np.array([0.03, -0.02, 0.025, -0.015, 0.01])
    matrix_energy = dynamics.kinetic_energy(q, q_dot)
    body_energy = dynamics.kinetic_energy_by_bodies(q, q_dot)
    assert matrix_energy == pytest.approx(body_energy, rel=1e-13, abs=1e-15)


def test_actuator_power_identity(dynamics):
    q = np.array([0.01, -0.015, 0.012, -0.008, 0.006])
    q_dot = np.array([0.03, -0.02, 0.025, -0.015, 0.01])
    forces = np.linspace(-1800.0, 2200.0, len(ACTUATOR_ORDER))
    generalized = dynamics.actuator_generalized_force(q, forces)
    length_velocity = dynamics.actuator_length_velocity(q, q_dot)
    assert q_dot @ generalized == pytest.approx(forces @ length_velocity, abs=1e-12)


def test_point_force_power_identity(dynamics):
    q = np.array([0.01, -0.015, 0.012, -0.008, 0.006])
    q_dot = np.array([0.03, -0.02, 0.025, -0.015, 0.01])
    point = np.array([0.12, -0.04])
    force = np.array([420.0, -175.0])
    jacobian = dynamics.body_point_jacobian(q, "WHEEL_3_NEG_Y", point)
    generalized = dynamics.point_force_generalized_force(q, "WHEEL_3_NEG_Y", point, force)
    assert q_dot @ generalized == pytest.approx(force @ (jacobian @ q_dot), abs=1e-12)
    torque = 85.0
    angular_jacobian = dynamics.body_angular_jacobian(q, "WHEEL_3_NEG_Y")
    torque_generalized = dynamics.torque_generalized_force(q, "WHEEL_3_NEG_Y", torque)
    assert q_dot @ torque_generalized == pytest.approx(
        torque * (angular_jacobian @ q_dot), abs=1e-12
    )


def test_free_motion_energy_is_conserved(dynamics):
    initial = np.r_[np.zeros(5), np.array([0.02, -0.015, 0.012, -0.01, 0.008])]
    result = solve_ivp(
        lambda t, y: dynamics.mechanical_rhs(t, y, np.zeros(5)),
        (0.0, 0.02), initial, t_eval=np.linspace(0.0, 0.02, 3),
        rtol=2e-6, atol=1e-9, max_step=0.01,
    )
    assert result.success
    energy = np.array([
        dynamics.kinetic_energy(result.y[:5, index], result.y[5:, index])
        for index in range(result.y.shape[1])
    ])
    assert np.max(np.abs(energy - energy[0])) / energy[0] < 1e-7


def test_finite_difference_convergence(dynamics):
    q = np.array([0.012, -0.011, 0.009, -0.007, 0.005])
    q_dot = np.array([0.03, -0.02, 0.025, -0.015, 0.01])
    body_id = "SIDE_TIE_ROD_3_NEG_Y"

    jacobians = [dynamics.body_com_jacobian(q, body_id, step_rad=step)
                 for step in (8e-5, 4e-5, 2e-5, 1e-5)]
    matrices = [dynamics.mass_matrix(q, jacobian_step_rad=step)
                for step in (8e-5, 4e-5, 2e-5, 1e-5)]
    biases = [dynamics.coriolis_centrifugal_bias(q, q_dot, mass_derivative_step_rad=step)
              for step in (8e-4, 4e-4, 2e-4, 1e-4)]

    for sequence in (jacobians, matrices, biases):
        errors = [np.linalg.norm(value - sequence[-1]) for value in sequence[:-1]]
        assert errors[1] < errors[0]
        assert errors[2] < errors[1]
