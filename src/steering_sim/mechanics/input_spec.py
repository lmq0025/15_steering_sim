"""Read frozen R02-A geometry without modifying source coordinates."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from typing import Any
import numpy as np
from .geometry2d import (
    HardPointReference, HydraulicActuatorGeometry, ReferenceGeometry,
    RevoluteJoint2D, RigidBody2D, RigidLink2D, SteeringWheelBody,
)

class InputSpecificationError(ValueError):
    pass

def load_frozen_input(path: str | Path) -> tuple[dict[str, Any], str]:
    """Load v1.0 YAML, frozen in UTF-8 JSON-compatible YAML syntax."""
    raw = Path(path).read_bytes()
    try:
        spec = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InputSpecificationError("v1.0 YAML must remain UTF-8 JSON-compatible YAML") from exc
    if spec.get("schema_version") != "1.0":
        raise InputSpecificationError("unsupported mechanical input schema")
    if spec.get("status") != "R02A_FROZEN_FOR_KINEMATICS":
        raise InputSpecificationError("mechanical input is not frozen for R02-B")
    coordinates = spec.get("coordinate_system", {})
    expected = {
        "plane": "XOY", "x_positive": "vehicle forward direction",
        "axle_1_to_6_direction": "front_to_rear = -X",
        "side_names": "NEG_Y/POS_Y only; no left/right mapping",
        "source_length_unit": "mm", "solver_length_unit": "m",
    }
    for key, value in expected.items():
        if coordinates.get(key) != value:
            raise InputSpecificationError(f"coordinate-system mismatch for {key}")
    if spec.get("total_kinematic_dof") != 5:
        raise InputSpecificationError("R02-B requires exactly five generalized coordinates")
    return spec, hashlib.sha256(raw).hexdigest()

def _moving_body(body_a: str, body_b: str) -> str | None:
    return next((b for b in (body_a, body_b) if b.startswith(("SWING_", "WHEEL_"))), None)

def build_reference_geometry(spec: dict[str, Any], digest: str) -> ReferenceGeometry:
    """Convert source mm to solver m once and freeze q=0 geometry."""
    points, records = {}, {}
    for record in spec["points_and_joints"]:
        point_id = record["point_id"]
        if point_id in points:
            raise InputSpecificationError(f"duplicate point id: {point_id}")
        position = (float(record["x_mm"]) * 1e-3, float(record["y_mm"]) * 1e-3)
        points[point_id] = HardPointReference(
            point_id, int(record["axle"]), position, str(record["provenance"])
        )
        records[point_id] = record

    pivots = {}
    for point_id, record in records.items():
        pair = (record["body_a"], record["body_b"])
        moving = _moving_body(*pair)
        if "FRAME" in pair and moving is not None:
            pivots[moving] = points[point_id].position

    local_points = {body: {} for body in pivots}
    owners = {}
    for point_id, record in records.items():
        moving = _moving_body(record["body_a"], record["body_b"])
        owners[point_id] = moving or "FRAME"
        if moving:
            local = np.asarray(points[point_id].position) - np.asarray(pivots[moving])
            local_points[moving][point_id] = tuple(map(float, local))

    bodies, joints = {}, []
    for body_name, pivot in pivots.items():
        body_type = SteeringWheelBody if body_name.startswith("WHEEL_") else RigidBody2D
        bodies[body_name] = body_type(body_name, pivot, local_points[body_name])
        joints.append(RevoluteJoint2D(f"JOINT_{body_name}", body_name, pivot))

    member_points: dict[str, list[str]] = {}
    for point_id, record in records.items():
        for member in (record["body_a"], record["body_b"]):
            if "TIE_ROD" in member or member.startswith("ACTUATOR_"):
                member_points.setdefault(member, []).append(point_id)

    links, actuators = {}, {}
    for member, endpoint_ids in member_points.items():
        unique = list(dict.fromkeys(endpoint_ids))
        if len(unique) != 2:
            raise InputSpecificationError(f"{member} must have exactly two attachment points")
        a, b = unique
        length = float(np.linalg.norm(np.asarray(points[b].position) - np.asarray(points[a].position)))
        if member.startswith("ACTUATOR_"):
            frame_id = a if owners[a] == "FRAME" else b
            moving_id = b if frame_id == a else a
            if owners[frame_id] != "FRAME" or owners[moving_id] == "FRAME":
                raise InputSpecificationError(f"{member} must connect FRAME to one moving body")
            actuators[member] = HydraulicActuatorGeometry(
                member, frame_id, owners[moving_id], moving_id, length
            )
        else:
            if "FRAME" in (owners[a], owners[b]):
                raise InputSpecificationError(f"rigid link {member} unexpectedly terminates on FRAME")
            links[member] = RigidLink2D(member, (owners[a], a), (owners[b], b), length)

    return ReferenceGeometry(digest, points, owners, bodies, tuple(joints), links, actuators)

def reference_geometry_from_file(path: str | Path) -> ReferenceGeometry:
    spec, digest = load_frozen_input(path)
    return build_reference_geometry(spec, digest)

def verify_json_crosscheck(primary_yaml: str | Path, secondary_json: str | Path) -> tuple[str, str]:
    """Require the optional JSON representation to match the primary YAML exactly."""
    primary_spec, primary_digest = load_frozen_input(primary_yaml)
    raw = Path(secondary_json).read_bytes()
    secondary_digest = hashlib.sha256(raw).hexdigest()
    try:
        secondary_spec = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InputSpecificationError("JSON cross-check file is invalid") from exc
    if secondary_spec != primary_spec:
        raise InputSpecificationError("JSON cross-check differs from primary YAML")
    return primary_digest, secondary_digest
