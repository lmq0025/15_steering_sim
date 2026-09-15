from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from steering_sim.mechanics import (
    ActuatorPosition, InvalidActuatorPositionError, MechanicalActuatorInput,
    MechanicalCalibrationProblem, MechanicalSteeringIOModel, PositionDefinition,
    SixAxleSteeringKinematics, SteeringPlausibilityEvaluator, WHEEL_OUTPUT_ORDER,
    load_calibration_parameter_set, reference_geometry_from_file,
)


ROOT = Path(__file__).parents[2]
SPEC = ROOT / "mechanical_model_input_spec_v1.0.yaml"
BASELINE = ROOT / "configs/mechanics/mechanical_io_baseline.yaml"


@pytest.fixture(scope="module")
def reference():
    if not SPEC.exists():
        pytest.skip("frozen CUSTOMER geometry is supplied outside Git")
    return reference_geometry_from_file(SPEC)


@pytest.fixture(scope="module")
def parameters(reference):
    return load_calibration_parameter_set(BASELINE, reference)


@pytest.fixture(scope="module")
def model(reference, parameters):
    return MechanicalSteeringIOModel(SixAxleSteeringKinematics(reference), parameters)


def _q_from_output(output):
    return np.array(list(output.generalized_coordinates.values()))


def test_round_trip_inverse_kinematics(model):
    maximum = 0.0
    model.reset()
    for value in np.linspace(-0.05, 0.05, 7):
        q = np.array([0.4 * value, value, -0.8 * value, 0.6 * value, -0.5 * value])
        output = model.solve_from_actuators(model.inputs_from_generalized_coordinates(q))
        maximum = max(maximum, float(np.max(np.abs(_q_from_output(output) - q))))
        assert output.valid
    assert maximum < 1e-10


def test_paired_cylinder_consistency_is_reported(model):
    q = np.array([0.01, 0.025, -0.02, 0.015, -0.01])
    inputs = model.inputs_from_generalized_coordinates(q)
    perturbed = replace(
        inputs,
        axle3_A=replace(inputs.axle3_A, value_m=inputs.axle3_A.value_m + 2e-5),
    )
    output = model.solve_from_actuators(perturbed)
    assert output.actuator_residuals["AXLE_3_PAIRED_RMS"] > 0.0
    assert "ACTUATOR_3_A" in output.actuator_residuals
    assert "ACTUATOR_3_B" in output.actuator_residuals


def test_single_sensor_fallback_predicts_other_cylinder(model):
    q = np.array([0.01, -0.025, 0.02, -0.015, 0.01])
    inputs = model.inputs_from_generalized_coordinates(q)
    output = model.solve_from_actuators(replace(inputs, axle4_B=None))
    assert output.generalized_coordinates["q4"] == pytest.approx(q[2], abs=1e-10)
    assert output.diagnostics["inverse"]["axle4"]["sensors_used"] == 1
    assert "ACTUATOR_4_B" in output.diagnostics["predicted_actuator_lengths_m"]


def test_zero_offset_scale_and_stroke_conversion(reference, parameters):
    updated = parameters.with_updates({
        "actuators.ACTUATOR_3_A.zero_offset": 0.004,
        "actuators.ACTUATOR_3_A.scale": 1.1,
    })
    model = MechanicalSteeringIOModel(SixAxleSteeringKinematics(reference), updated)
    q = np.array([0.01, 0.025, -0.02, 0.015, -0.01])
    inputs = model.inputs_from_generalized_coordinates(
        q, PositionDefinition.STROKE_FROM_REFERENCE_M
    )
    output = model.solve_from_actuators(inputs)
    assert np.max(np.abs(_q_from_output(output) - q)) < 1e-10


def test_front_mapping_round_trip_and_axle2_has_no_input(parameters):
    mapping = parameters.front_mapping
    assert mapping.k_front.source.value == "ASSUMED_BASELINE"
    assert "NOT CUSTOMER CALIBRATED" in mapping.k_front.notes
    for q_front in (-0.05, 0.0, 0.05):
        assert mapping.position_to_q_front(mapping.q_front_to_position(q_front)) == pytest.approx(q_front)
    assert not any(name.startswith("axle2_") for name in MechanicalActuatorInput.__dataclass_fields__)
    sign_candidate = parameters.with_updates({"actuators.ACTUATOR_3_A.stroke_sign": -1.0})
    assert sign_candidate.actuators["ACTUATOR_3_A"].stroke_sign.value == -1.0
    assert not parameters.hardpoint_correction.enabled


def test_wheel_output_order(model):
    output = model.solve_from_actuators(model.inputs_from_generalized_coordinates(np.zeros(5)))
    assert tuple(output.wheel_angles_rad) == WHEEL_OUTPUT_ORDER
    assert len(output.wheel_angles_rad) == 12


def test_invalid_actuator_position(model):
    with pytest.raises(InvalidActuatorPositionError, match="finite"):
        ActuatorPosition(np.nan)
    inputs = model.inputs_from_generalized_coordinates(np.zeros(5))
    output = model.solve_from_actuators(replace(inputs, axle6_A=ActuatorPosition(100.0)))
    assert output.out_of_range and not output.valid


def test_branch_continuity_inverse_and_plausibility(model, reference):
    outputs = []
    recovered = []
    model.reset()
    for value in np.linspace(-0.04, 0.04, 17):
        q = np.array([value, value, value, value, value])
        output = model.solve_from_actuators(model.inputs_from_generalized_coordinates(q))
        outputs.append(output)
        recovered.append(_q_from_output(output))
    assert np.max(np.abs(np.diff(np.asarray(recovered), axis=0))) < 0.01
    track = abs(reference.bodies["WHEEL_3_POS_Y"].pivot[1] - reference.bodies["WHEEL_3_NEG_Y"].pivot[1])
    report = SteeringPlausibilityEvaluator.evaluate(outputs, ackermann_geometry_m={3: (5.0, track)})
    assert report.maximum_ackermann_reference_error_deg is not None
    assert report.all_reachable and not report.any_out_of_range
    assert set(report.monotonic_by_wheel) == set(WHEEL_OUTPUT_ORDER)
    assert not report.monotonic_by_wheel["axle5_POS_Y"]
    assert not report.monotonic_by_wheel["axle5_NEG_Y"]


def _calibration_frame(model, q_values, observation_name):
    rows = []
    for index, q3 in enumerate(q_values):
        q = np.array([0.0, q3, 0.0, 0.0, 0.0])
        inputs = model.inputs_from_generalized_coordinates(q)
        output = model.solve_from_actuators(inputs)
        row = {"time": float(index), "front_position": inputs.front_position}
        for axle in range(3, 7):
            for side in ("A", "B"):
                row[f"axle{axle}_{side}_position"] = getattr(inputs, f"axle{axle}_{side}").value_m
        row[observation_name] = output.wheel_angles_rad[observation_name.removesuffix("_angle")]
        rows.append(row)
    return pd.DataFrame(rows)


def test_synthetic_calibration_and_held_out_validation(reference, parameters):
    parameter_name = "wheel_offsets.WHEEL_3_POS_Y"
    truth = parameters.with_updates({parameter_name: 0.012})
    truth_model = MechanicalSteeringIOModel(SixAxleSteeringKinematics(reference), truth)
    calibration_set = _calibration_frame(truth_model, [-0.04, -0.02, 0.0], "axle3_POS_Y_angle")
    validation_set = _calibration_frame(truth_model, [0.01, 0.03], "axle3_POS_Y_angle")
    problem = MechanicalCalibrationProblem(reference, parameters, [parameter_name])
    result = problem.fit(calibration_set)
    assert result.success
    assert result.parameter_values[0] == pytest.approx(0.012, abs=1e-10)
    metrics = problem.evaluate_validation(validation_set, result.parameters)
    assert metrics.max_abs_error_rad < 1e-10
    with pytest.raises(ValueError, match="separate"):
        problem.evaluate_validation(calibration_set, result.parameters)
    with pytest.raises(ValueError, match="separate"):
        problem.evaluate_validation(calibration_set.iloc[::-1], result.parameters)
