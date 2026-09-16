from pathlib import Path

import numpy as np
import pytest

from steering_sim.mechanics import (
    GENERALIZED_COORDINATES, MechanicalSteeringIOModel,
    MultiAxleSteeringCoordinator, SteeringMode, axle_mean_angles,
    ideal_wheel_angles_from_icr, load_calibration_parameter_set,
    load_steering_coordinator_config, reference_geometry_from_file,
    SixAxleSteeringKinematics, wheel_axis_centers,
)


ROOT = Path(__file__).parents[2]
GEOMETRY = ROOT / "mechanical_model_input_spec_v1.0.yaml"
IO_BASELINE = ROOT / "configs/mechanics/mechanical_io_baseline.yaml"
COORDINATOR_BASELINE = ROOT / "configs/mechanics/multi_axle_steering_baseline.yaml"


@pytest.fixture
def coordinator():
    if not GEOMETRY.exists():
        pytest.skip("frozen CUSTOMER geometry is supplied outside Git")
    reference = reference_geometry_from_file(GEOMETRY)
    parameters = load_calibration_parameter_set(IO_BASELINE, reference)
    io_model = MechanicalSteeringIOModel(
        SixAxleSteeringKinematics(reference), parameters
    )
    config = load_steering_coordinator_config(COORDINATOR_BASELINE)
    return MultiAxleSteeringCoordinator(io_model, config)


def _sign(value):
    return int(np.sign(value))


def test_icr_sign_pattern_public(coordinator):
    result = coordinator.coordinate(2.0, "public")
    means = axle_mean_angles(result.ideal_wheel_angles_rad)
    assert [_sign(means[i]) for i in range(1, 7)] == [1, 1, 1, -1, -1, -1]
    assert coordinator.axle_x_m(3) > result.x_icr_m > coordinator.axle_x_m(4)
    distances = {
        axle: abs(coordinator.axle_x_m(axle) - result.x_icr_m)
        for axle in range(1, 7)
    }
    for first in range(1, 7):
        for second in range(1, 7):
            if distances[first] > distances[second] + 1e-12:
                assert abs(means[first]) > abs(means[second])


def test_icr_sign_pattern_customer_hint(coordinator):
    result = coordinator.coordinate(2.0, "customer-hint")
    means = axle_mean_angles(result.ideal_wheel_angles_rad)
    assert [_sign(means[i]) for i in range(1, 7)] == [1, 1, -1, -1, -1, -1]
    assert coordinator.axle_x_m(2) > result.x_icr_m > coordinator.axle_x_m(3)


def test_ackermann_inner_outer_geometry(coordinator):
    positive = coordinator.coordinate(1.0, "public")
    negative = coordinator.coordinate(-1.0, "public")
    for axle in range(1, 7):
        assert abs(positive.ideal_wheel_angles_rad[f"axle{axle}_POS_Y"]) > abs(
            positive.ideal_wheel_angles_rad[f"axle{axle}_NEG_Y"]
        )
        assert abs(negative.ideal_wheel_angles_rad[f"axle{axle}_NEG_Y"]) > abs(
            negative.ideal_wheel_angles_rad[f"axle{axle}_POS_Y"]
        )


def test_left_right_turn_symmetry(coordinator):
    centers = wheel_axis_centers(coordinator.reference)
    x_icr = coordinator.resolve_x_icr(coordinator.config.preset("public"))
    plus = ideal_wheel_angles_from_icr(centers, x_icr, 200.0)
    minus = ideal_wheel_angles_from_icr(centers, x_icr, -200.0)
    for axle in range(1, 7):
        assert plus[f"axle{axle}_POS_Y"] == pytest.approx(
            -minus[f"axle{axle}_NEG_Y"], abs=1e-14
        )
        assert plus[f"axle{axle}_NEG_Y"] == pytest.approx(
            -minus[f"axle{axle}_POS_Y"], abs=1e-14
        )


def test_coordinator_to_actuator_roundtrip(coordinator):
    result = coordinator.coordinate(1.0, "public")
    recovered = result.mechanical_output.generalized_coordinates
    assert max(
        abs(result.q_target_rad[name] - recovered[name])
        for name in GENERALIZED_COORDINATES
    ) < 1e-10


def test_mechanical_io_end_to_end_uses_frozen_geometry(coordinator):
    result = coordinator.coordinate(1.0, "customer-hint")
    q = np.array([result.q_target_rad[name] for name in GENERALIZED_COORDINATES])
    direct = SixAxleSteeringKinematics(coordinator.reference).solve(q)
    for axle in range(1, 7):
        for side in ("POS_Y", "NEG_Y"):
            public = f"axle{axle}_{side}"
            internal = f"WHEEL_{axle}_{side}"
            expected = (
                direct.wheel_angles[internal]
                + coordinator.io_model.parameters.wheel_zero_offsets[internal].value
            )
            assert result.mechanical_output.wheel_angles_rad[public] == pytest.approx(
                expected, abs=1e-10
            )


def test_crab_mode_sign(coordinator):
    result = coordinator.coordinate(1.0, "public", SteeringMode.CRAB)
    assert all(value > 0.0 for value in axle_mean_angles(result.ideal_wheel_angles_rad).values())


def test_front_only_mode(coordinator):
    result = coordinator.coordinate(1.0, "public", SteeringMode.FRONT_GROUP_ONLY)
    ideal_means = axle_mean_angles(result.ideal_wheel_angles_rad)
    assert ideal_means[1] > 0.0 and ideal_means[2] > 0.0
    assert all(ideal_means[axle] == 0.0 for axle in range(3, 7))
    assert all(
        abs(result.q_target_rad[name]) < 1e-8 for name in ("q3", "q4", "q5", "q6")
    )


def test_axle5_axle6_diagnostics_are_explicit(coordinator):
    result = coordinator.coordinate(2.0, "public")
    for axle in (5, 6):
        diagnostic = result.axles[axle]
        assert diagnostic.monotonic_branch_used
        assert isinstance(diagnostic.branch_continuity, bool)
        assert diagnostic.actuator_a_stroke_m is not None
        assert diagnostic.actuator_b_stroke_m is not None
        assert diagnostic.status in {
            "matched_within_display_tolerance", "baseline_mismatch", "geometry_limited"
        }
        assert diagnostic.geometry_residual_rad >= 0.0


def test_infeasible_request_reports_scaled_equivalent(coordinator):
    result = coordinator.coordinate(30.0, "public")
    assert not result.feasible
    assert 0.0 <= result.largest_feasible_scale < 1.0
