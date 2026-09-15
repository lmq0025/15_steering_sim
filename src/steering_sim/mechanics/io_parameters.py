"""Traceable baseline and calibration parameters for mechanical I/O."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from enum import Enum
import json
from pathlib import Path
from types import MappingProxyType
from typing import Mapping


class CalibrationSource(str, Enum):
    CUSTOMER = "CUSTOMER"
    CALIBRATED = "CALIBRATED"
    LITERATURE_BASELINE = "LITERATURE_BASELINE"
    ASSUMED_BASELINE = "ASSUMED_BASELINE"


class PositionDefinition(str, Enum):
    ABSOLUTE_LENGTH_M = "absolute_length_m"
    STROKE_FROM_REFERENCE_M = "stroke_from_reference_m"


@dataclass(frozen=True, slots=True)
class CalibrationValue:
    name: str
    value: float
    unit: str
    source: CalibrationSource
    confidence: float
    reference: str
    notes: str
    calibratable: bool
    lower_bound: float | None
    upper_bound: float | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", CalibrationSource(self.source))
        if not self.name or not self.unit or not self.reference or not self.notes:
            raise ValueError(f"{self.name or 'parameter'} requires unit/reference/notes")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"{self.name}: confidence must be in [0,1]")
        if self.calibratable:
            if self.lower_bound is None or self.upper_bound is None:
                raise ValueError(f"{self.name}: calibratable value requires bounds")
            if not self.lower_bound <= self.value <= self.upper_bound:
                raise ValueError(f"{self.name}: baseline value is outside bounds")

    def with_value(self, value: float, source: CalibrationSource = CalibrationSource.CALIBRATED):
        if self.lower_bound is not None and value < self.lower_bound:
            raise ValueError(f"{self.name}: value below lower bound")
        if self.upper_bound is not None and value > self.upper_bound:
            raise ValueError(f"{self.name}: value above upper bound")
        return replace(self, value=float(value), source=source)


@dataclass(frozen=True, slots=True)
class ActuatorPositionCalibration:
    actuator_id: str
    reference_length: CalibrationValue
    stroke_sign: CalibrationValue
    zero_offset: CalibrationValue
    scale: CalibrationValue

    def __post_init__(self) -> None:
        if self.stroke_sign.value not in (-1.0, 1.0):
            raise ValueError(f"{self.actuator_id}: stroke_sign must be -1 or +1")
        if self.scale.value == 0.0:
            raise ValueError(f"{self.actuator_id}: scale must not be zero")

    def to_absolute_length(self, value_m: float, definition: PositionDefinition) -> float:
        definition = PositionDefinition(definition)
        calibrated = self.scale.value * (float(value_m) - self.zero_offset.value)
        if definition is PositionDefinition.ABSOLUTE_LENGTH_M:
            return calibrated
        return self.reference_length.value + self.stroke_sign.value * calibrated

    def from_absolute_length(self, length_m: float, definition: PositionDefinition) -> float:
        definition = PositionDefinition(definition)
        calibrated = float(length_m)
        if definition is PositionDefinition.STROKE_FROM_REFERENCE_M:
            calibrated = (calibrated - self.reference_length.value) / self.stroke_sign.value
        return calibrated / self.scale.value + self.zero_offset.value


class FrontActuatorMapping(ABC):
    @abstractmethod
    def position_to_q_front(self, position_m: float) -> float:
        pass

    @abstractmethod
    def q_front_to_position(self, q_front: float) -> float:
        pass


@dataclass(frozen=True, slots=True)
class LinearFrontActuatorMapping(FrontActuatorMapping):
    k_front: CalibrationValue
    position_zero: CalibrationValue

    def __post_init__(self) -> None:
        if self.k_front.value == 0.0:
            raise ValueError("front.k_front must not be zero")

    def position_to_q_front(self, position_m: float) -> float:
        return self.k_front.value * (float(position_m) - self.position_zero.value)

    def q_front_to_position(self, q_front: float) -> float:
        return float(q_front) / self.k_front.value + self.position_zero.value


@dataclass(frozen=True, slots=True)
class HardpointCorrection:
    enabled: bool = False
    corrections_m: Mapping[str, tuple[float, float]] | None = None
    lower_bounds_m: Mapping[str, tuple[float, float]] | None = None
    upper_bounds_m: Mapping[str, tuple[float, float]] | None = None

    def __post_init__(self) -> None:
        corrections = {} if self.corrections_m is None else dict(self.corrections_m)
        lower = {} if self.lower_bounds_m is None else dict(self.lower_bounds_m)
        upper = {} if self.upper_bounds_m is None else dict(self.upper_bounds_m)
        if self.enabled:
            if not corrections or corrections.keys() != lower.keys() or corrections.keys() != upper.keys():
                raise ValueError("enabled hardpoint correction requires matching tolerance bounds")
            for point_id, correction in corrections.items():
                if any(not low <= value <= high for value, low, high in zip(correction, lower[point_id], upper[point_id])):
                    raise ValueError(f"{point_id}: hardpoint correction outside tolerance bounds")
        object.__setattr__(self, "corrections_m", MappingProxyType(corrections))
        object.__setattr__(self, "lower_bounds_m", MappingProxyType(lower))
        object.__setattr__(self, "upper_bounds_m", MappingProxyType(upper))


@dataclass(frozen=True, slots=True)
class CalibrationParameterSet:
    front_mapping: LinearFrontActuatorMapping
    actuators: Mapping[str, ActuatorPositionCalibration]
    wheel_zero_offsets: Mapping[str, CalibrationValue]
    inverse_lower_q_rad: CalibrationValue
    inverse_upper_q_rad: CalibrationValue
    paired_weight_a: CalibrationValue
    paired_weight_b: CalibrationValue
    hardpoint_correction: HardpointCorrection = HardpointCorrection()

    def __post_init__(self) -> None:
        object.__setattr__(self, "actuators", MappingProxyType(dict(self.actuators)))
        object.__setattr__(self, "wheel_zero_offsets", MappingProxyType(dict(self.wheel_zero_offsets)))
        if self.inverse_lower_q_rad.value >= self.inverse_upper_q_rad.value:
            raise ValueError("inverse search lower bound must be below upper bound")
        if self.hardpoint_correction.enabled:
            raise ValueError("R02-D baseline keeps CUSTOMER hardpoints frozen")

    def named_values(self, *, continuous_only: bool = False) -> Mapping[str, CalibrationValue]:
        values = {
            "front.k_front": self.front_mapping.k_front,
            "front.position_zero": self.front_mapping.position_zero,
        }
        for actuator_id, calibration in self.actuators.items():
            values[f"actuators.{actuator_id}.zero_offset"] = calibration.zero_offset
            values[f"actuators.{actuator_id}.scale"] = calibration.scale
            if not continuous_only:
                values[f"actuators.{actuator_id}.stroke_sign"] = calibration.stroke_sign
        for wheel_id, value in self.wheel_zero_offsets.items():
            values[f"wheel_offsets.{wheel_id}"] = value
        return MappingProxyType(values)

    def with_updates(self, updates: Mapping[str, float]) -> "CalibrationParameterSet":
        front = self.front_mapping
        actuators = dict(self.actuators)
        wheels = dict(self.wheel_zero_offsets)
        for name, value in updates.items():
            if name == "front.k_front":
                front = replace(front, k_front=front.k_front.with_value(value))
            elif name == "front.position_zero":
                front = replace(front, position_zero=front.position_zero.with_value(value))
            elif name.startswith("actuators."):
                _, actuator_id, field = name.split(".")
                item = actuators[actuator_id]
                if field == "stroke_sign" and value not in (-1.0, 1.0):
                    raise ValueError("stroke_sign calibration is discrete: -1 or +1")
                actuators[actuator_id] = replace(item, **{field: getattr(item, field).with_value(value)})
            elif name.startswith("wheel_offsets."):
                wheel_id = name.split(".", 1)[1]
                wheels[wheel_id] = wheels[wheel_id].with_value(value)
            else:
                raise KeyError(f"unknown calibration parameter: {name}")
        return replace(self, front_mapping=front, actuators=actuators, wheel_zero_offsets=wheels)


def _value(name: str, raw: Mapping, *, derived: float | None = None) -> CalibrationValue:
    required = {
        "value", "unit", "source", "confidence", "reference", "notes",
        "calibratable", "lower_bound", "upper_bound",
    }
    missing = required - raw.keys()
    if missing:
        raise ValueError(f"{name}: missing metadata {sorted(missing)}")
    value = derived if raw["value"] == "FROM_REFERENCE_GEOMETRY" else float(raw["value"])
    if value is None:
        raise ValueError(f"{name}: derived reference value unavailable")
    return CalibrationValue(
        name, value, raw["unit"], CalibrationSource(raw["source"]),
        float(raw["confidence"]), raw["reference"], raw["notes"],
        bool(raw["calibratable"]),
        None if raw["lower_bound"] is None else float(raw["lower_bound"]),
        None if raw["upper_bound"] is None else float(raw["upper_bound"]),
    )


def load_calibration_parameter_set(path: str | Path, reference) -> CalibrationParameterSet:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if raw.get("schema_version") != "1.0" or raw.get("purpose") != "R02D_BASELINE_ONLY":
        raise ValueError("unsupported mechanical I/O baseline schema")
    if raw.get("hardpoint_correction", {}).get("enabled", False):
        raise ValueError("R02-D baseline must not enable hardpoint correction")
    front_raw = raw["front_mapping"]
    front = LinearFrontActuatorMapping(
        _value("front.k_front", front_raw["k_front"]),
        _value("front.position_zero", front_raw["position_zero"]),
    )
    actuators = {}
    for actuator_id, item in raw["actuators"].items():
        derived = reference.actuators[actuator_id].reference_length
        actuators[actuator_id] = ActuatorPositionCalibration(
            actuator_id,
            _value(f"{actuator_id}.reference_length", item["reference_length"], derived=derived),
            _value(f"{actuator_id}.stroke_sign", item["stroke_sign"]),
            _value(f"{actuator_id}.zero_offset", item["zero_offset"]),
            _value(f"{actuator_id}.scale", item["scale"]),
        )
    wheels = {
        wheel_id: _value(f"wheel_offsets.{wheel_id}", item)
        for wheel_id, item in raw["wheel_zero_offsets"].items()
    }
    search = raw["numerical_inverse_search"]
    weights = raw["paired_cylinder_weights"]
    return CalibrationParameterSet(
        front, actuators, wheels,
        _value("inverse.lower_q", search["lower_q_rad"]),
        _value("inverse.upper_q", search["upper_q_rad"]),
        _value("paired.weight_a", weights["weight_a"]),
        _value("paired.weight_b", weights["weight_b"]),
        HardpointCorrection(False),
    )
