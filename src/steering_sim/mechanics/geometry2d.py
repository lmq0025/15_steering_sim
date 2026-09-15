"""Minimal planar geometry primitives."""
from __future__ import annotations
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping
import numpy as np

Vector2 = tuple[float, float]

def vector(value: Vector2) -> np.ndarray:
    return np.asarray(value, dtype=float)

def rotation(angle: float) -> np.ndarray:
    c, s = np.cos(angle), np.sin(angle)
    return np.array([[c, -s], [s, c]], dtype=float)

def rotation_derivative(angle: float) -> np.ndarray:
    c, s = np.cos(angle), np.sin(angle)
    return np.array([[-s, -c], [c, -s]], dtype=float)

@dataclass(frozen=True, slots=True)
class RigidBody2D:
    name: str
    pivot: Vector2
    local_hardpoints: Mapping[str, Vector2]

    def __post_init__(self) -> None:
        object.__setattr__(self, "local_hardpoints", MappingProxyType(dict(self.local_hardpoints)))

    def world_point(self, point_id: str, angle: float) -> np.ndarray:
        return vector(self.pivot) + rotation(angle) @ vector(self.local_hardpoints[point_id])

    def point_angle_derivative(self, point_id: str, angle: float) -> np.ndarray:
        return rotation_derivative(angle) @ vector(self.local_hardpoints[point_id])

@dataclass(frozen=True, slots=True)
class SteeringWheelBody(RigidBody2D):
    """The pose angle is the actual wheel steering angle from q=0."""

@dataclass(frozen=True, slots=True)
class RevoluteJoint2D:
    name: str
    body_name: str
    frame_point: Vector2
    axis: str = "+Z"

    def __post_init__(self) -> None:
        if self.axis != "+Z":
            raise ValueError("only revolute joints about +Z are supported")

@dataclass(frozen=True, slots=True)
class RigidLink2D:
    name: str
    endpoint_a: tuple[str, str]
    endpoint_b: tuple[str, str]
    reference_length: float

@dataclass(frozen=True, slots=True)
class ClosedChainConstraint:
    link: RigidLink2D

    def residual(self, point_a: np.ndarray, point_b: np.ndarray) -> float:
        return float(np.linalg.norm(point_b - point_a) - self.link.reference_length)

@dataclass(frozen=True, slots=True)
class HydraulicActuatorGeometry:
    name: str
    frame_point_id: str
    moving_body: str
    moving_point_id: str
    reference_length: float

    @staticmethod
    def length(frame_point: np.ndarray, moving_point: np.ndarray) -> float:
        return float(np.linalg.norm(moving_point - frame_point))

    @staticmethod
    def derivative_wrt_body_angle(frame_point, moving_point, point_derivative) -> float:
        delta = moving_point - frame_point
        length = float(np.linalg.norm(delta))
        if length <= 0.0:
            raise ValueError("actuator attachment points must not coincide")
        return float(delta @ point_derivative / length)

@dataclass(frozen=True, slots=True)
class HardPointReference:
    point_id: str
    axle: int
    position: Vector2
    provenance: str

@dataclass(frozen=True, slots=True)
class ReferenceGeometry:
    source_sha256: str
    points: Mapping[str, HardPointReference]
    point_owners: Mapping[str, str]
    bodies: Mapping[str, RigidBody2D]
    joints: tuple[RevoluteJoint2D, ...]
    links: Mapping[str, RigidLink2D]
    actuators: Mapping[str, HydraulicActuatorGeometry]

    def __post_init__(self) -> None:
        for name in ("points", "point_owners", "bodies", "links", "actuators"):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))
