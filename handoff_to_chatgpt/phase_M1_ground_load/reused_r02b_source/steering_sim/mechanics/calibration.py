"""Calibration interface for actuator-position to wheel-angle observations."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Mapping, Sequence

import numpy as np
import pandas as pd
from scipy.optimize import least_squares

from .io_model import ActuatorPosition, MechanicalActuatorInput, MechanicalSteeringIOModel
from .io_parameters import CalibrationParameterSet, PositionDefinition
from .kinematics import SixAxleSteeringKinematics


ACTUATOR_DATA_COLUMNS = tuple(
    f"axle{axle}_{side}_position" for axle in range(3, 7) for side in ("A", "B")
)
WHEEL_OBSERVATION_COLUMNS = tuple(
    f"axle{axle}_{side}_angle" for axle in range(1, 7) for side in ("POS_Y", "NEG_Y")
)
NORMALIZATION_FLOOR_RAD = 1.0e-3


@dataclass(frozen=True, slots=True)
class CalibrationMetrics:
    mae_rad: float
    rmse_rad: float
    max_abs_error_rad: float
    normalized_rmse: float
    sample_count: int


@dataclass(frozen=True, slots=True)
class MechanicalCalibrationResult:
    parameters: CalibrationParameterSet
    parameter_names: tuple[str, ...]
    parameter_values: np.ndarray
    residual_norm: float
    success: bool
    message: str


class MechanicalCalibrationProblem:
    """Bounded least-squares calibration with mandatory held-out validation API."""

    def __init__(
        self,
        reference,
        baseline: CalibrationParameterSet,
        parameter_names: Sequence[str],
        *,
        observation_weights: Mapping[str, float] | None = None,
        regularization_weight: float = 0.0,
        position_definition: PositionDefinition = PositionDefinition.ABSOLUTE_LENGTH_M,
    ) -> None:
        self.reference = reference
        self.baseline = baseline
        self.parameter_names = tuple(parameter_names)
        available = baseline.named_values(continuous_only=True)
        for name in self.parameter_names:
            if name not in available:
                raise ValueError(f"{name}: not a continuous first-level calibration parameter")
            if not available[name].calibratable:
                raise ValueError(f"{name}: parameter is not calibratable")
        self.observation_weights = dict(observation_weights or {})
        if any(weight <= 0.0 for weight in self.observation_weights.values()):
            raise ValueError("observation weights must be positive")
        self.regularization_weight = float(regularization_weight)
        if self.regularization_weight < 0.0:
            raise ValueError("regularization_weight must not be negative")
        self.position_definition = PositionDefinition(position_definition)
        self._calibration_fingerprint: str | None = None

    @staticmethod
    def _fingerprint(frame: pd.DataFrame) -> str:
        canonical = frame.sort_values("time").reset_index(drop=True)
        payload = pd.util.hash_pandas_object(canonical, index=False).values.tobytes()
        return hashlib.sha256(payload + repr(tuple(canonical.columns)).encode()).hexdigest()

    def _input_from_row(self, row: pd.Series) -> MechanicalActuatorInput:
        def position(name: str):
            if name not in row or pd.isna(row[name]):
                return None
            return ActuatorPosition(float(row[name]), self.position_definition)

        return MechanicalActuatorInput(
            front_position=float(row["front_position"]),
            axle3_A=position("axle3_A_position"), axle3_B=position("axle3_B_position"),
            axle4_A=position("axle4_A_position"), axle4_B=position("axle4_B_position"),
            axle5_A=position("axle5_A_position"), axle5_B=position("axle5_B_position"),
            axle6_A=position("axle6_A_position"), axle6_B=position("axle6_B_position"),
        )

    def _residuals(
        self, values: np.ndarray, frame: pd.DataFrame, *, include_regularization: bool
    ) -> np.ndarray:
        updates = dict(zip(self.parameter_names, map(float, values)))
        parameters = self.baseline.with_updates(updates)
        model = MechanicalSteeringIOModel(SixAxleSteeringKinematics(self.reference), parameters)
        residuals = []
        for _, row in frame.sort_values("time").iterrows():
            output = model.solve_from_actuators(self._input_from_row(row))
            for column in WHEEL_OBSERVATION_COLUMNS:
                if column in row and not pd.isna(row[column]):
                    wheel_name = column.removesuffix("_angle")
                    weight = float(self.observation_weights.get(column, 1.0))
                    residuals.append(np.sqrt(weight) * (output.wheel_angles_rad[wheel_name] - float(row[column])))
        if not residuals:
            raise ValueError("dataset contains no wheel-angle observations")
        if include_regularization and self.regularization_weight > 0.0:
            available = self.baseline.named_values(continuous_only=True)
            for name, value in zip(self.parameter_names, values):
                parameter = available[name]
                span = parameter.upper_bound - parameter.lower_bound
                residuals.append(
                    np.sqrt(self.regularization_weight) * (value - parameter.value) / span
                )
        return np.asarray(residuals)

    def fit(self, calibration_set: pd.DataFrame) -> MechanicalCalibrationResult:
        required = {"time", "front_position"}
        if not required.issubset(calibration_set.columns):
            raise ValueError(f"calibration_set requires columns {sorted(required)}")
        available = self.baseline.named_values(continuous_only=True)
        initial = np.array([available[name].value for name in self.parameter_names])
        lower = np.array([available[name].lower_bound for name in self.parameter_names])
        upper = np.array([available[name].upper_bound for name in self.parameter_names])
        result = least_squares(
            lambda values: self._residuals(values, calibration_set, include_regularization=True),
            initial, bounds=(lower, upper),
        )
        self._calibration_fingerprint = self._fingerprint(calibration_set)
        parameters = self.baseline.with_updates(dict(zip(self.parameter_names, result.x)))
        return MechanicalCalibrationResult(
            parameters, self.parameter_names, result.x.copy(), float(np.linalg.norm(result.fun)),
            bool(result.success), str(result.message),
        )

    def evaluate_validation(
        self, validation_set: pd.DataFrame, calibrated: CalibrationParameterSet
    ) -> CalibrationMetrics:
        if self._calibration_fingerprint is None:
            raise RuntimeError("fit must be called before held-out validation")
        if self._fingerprint(validation_set) == self._calibration_fingerprint:
            raise ValueError("validation_set must be separate from calibration_set")
        model = MechanicalSteeringIOModel(SixAxleSteeringKinematics(self.reference), calibrated)
        raw_errors = []
        for _, row in validation_set.sort_values("time").iterrows():
            output = model.solve_from_actuators(self._input_from_row(row))
            for column in WHEEL_OBSERVATION_COLUMNS:
                if column in row and not pd.isna(row[column]):
                    wheel_name = column.removesuffix("_angle")
                    raw_errors.append(output.wheel_angles_rad[wheel_name] - float(row[column]))
        if not raw_errors:
            raise ValueError("validation_set contains no wheel-angle observations")
        errors = np.asarray(raw_errors)
        absolute = np.abs(errors)
        measured = []
        for column in WHEEL_OBSERVATION_COLUMNS:
            if column in validation_set:
                measured.extend(validation_set[column].dropna().astype(float).tolist())
        scale = max(float(np.ptp(measured)) if measured else 0.0, NORMALIZATION_FLOOR_RAD)
        rmse = float(np.sqrt(np.mean(errors**2)))
        return CalibrationMetrics(
            float(np.mean(absolute)), rmse, float(np.max(absolute)), rmse / scale, len(errors)
        )
