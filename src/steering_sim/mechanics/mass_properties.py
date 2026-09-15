"""Traceable mass properties for reduced mechanical dynamics."""
from __future__ import annotations

import csv
from dataclasses import dataclass
import math
from pathlib import Path
from typing import Iterable, Mapping

from steering_sim.core.parameters import ParameterMeta, ParameterSource

from .geometry2d import ReferenceGeometry


SYNTHETIC_TEST_NOTE = (
    "synthetic numerical verification only; not customer engineering data"
)
MASS_PROPERTY_COLUMNS = (
    "body_id", "body_type", "axle", "mass_kg", "com_local_x_m",
    "com_local_y_m", "izz_kg_m2", "source", "confidence", "notes",
    "required_for_engineering_run", "include_in_inertia",
)


class MissingMechanicalParameterError(ValueError):
    """Raised when a formal dynamics run lacks required mass properties."""


@dataclass(frozen=True, slots=True)
class RigidBodyMassProperties:
    body_id: str
    mass_kg: float
    com_local_x_m: float
    com_local_y_m: float
    izz_kg_m2: float
    source: ParameterSource
    confidence: float
    notes: str = ""
    include_in_inertia: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", ParameterSource(self.source))
        if not self.body_id.strip():
            raise ValueError("body_id must not be empty")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")
        values = (self.mass_kg, self.com_local_x_m, self.com_local_y_m, self.izz_kg_m2)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("mass properties must be finite")
        if self.mass_kg < 0.0 or self.izz_kg_m2 < 0.0:
            raise ValueError("mass and Izz must not be negative")
        if self.include_in_inertia:
            if self.mass_kg <= 0.0 or self.izz_kg_m2 <= 0.0:
                raise ValueError("included bodies require positive mass and Izz")
        elif not self.notes.strip():
            raise ValueError("an explicitly ignored body requires explanatory notes")

    @property
    def parameter_metadata(self) -> tuple[ParameterMeta, ...]:
        prefix = self.body_id
        return (
            ParameterMeta(f"{prefix}.mass", self.mass_kg, "kg", self.source, self.confidence, self.notes),
            ParameterMeta(f"{prefix}.com_local_x", self.com_local_x_m, "m", self.source, self.confidence, self.notes),
            ParameterMeta(f"{prefix}.com_local_y", self.com_local_y_m, "m", self.source, self.confidence, self.notes),
            ParameterMeta(f"{prefix}.izz", self.izz_kg_m2, "kg*m^2", self.source, self.confidence, self.notes),
        )


class MassPropertySet:
    def __init__(self, properties: Iterable[RigidBodyMassProperties]):
        self._items = {}
        for item in properties:
            if item.body_id in self._items:
                raise ValueError(f"duplicate mass properties for {item.body_id}")
            self._items[item.body_id] = item

    def __getitem__(self, body_id: str) -> RigidBodyMassProperties:
        return self._items[body_id]

    def __iter__(self):
        return iter(self._items.values())

    def validate_complete(self, expected_body_ids: Iterable[str]) -> None:
        expected = set(expected_body_ids)
        missing = sorted(expected - self._items.keys())
        if missing:
            raise MissingMechanicalParameterError(
                "missing mechanical mass properties for: " + ", ".join(missing)
            )

    @property
    def contains_synthetic_test_only(self) -> bool:
        return any(SYNTHETIC_TEST_NOTE in item.notes for item in self._items.values())


def _axle_from_name(body_id: str) -> str:
    if body_id.endswith("_12") or "_12_" in body_id:
        return "1-2"
    parts = body_id.split("_")
    return next((part for part in parts if part.isdigit()), "")


def inertial_body_inventory(reference: ReferenceGeometry) -> tuple[dict[str, str], ...]:
    inventory = []
    for body_id in reference.bodies:
        body_type = "swing_arm" if body_id.startswith("SWING_") else "steering_wheel_knuckle"
        inventory.append({"body_id": body_id, "body_type": body_type, "axle": _axle_from_name(body_id)})
    for body_id in reference.links:
        if body_id.startswith("SIDE_"):
            body_type = "side_tie_rod"
        elif body_id.startswith("CROSS_"):
            body_type = "cross_tie_rod"
        else:
            body_type = "longitudinal_tie_rod"
        inventory.append({"body_id": body_id, "body_type": body_type, "axle": _axle_from_name(body_id)})
    return tuple(inventory)


def generate_mass_properties_template(reference: ReferenceGeometry, path: str | Path) -> Path:
    """Generate blank engineering-input rows from the frozen kinematic inventory."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=MASS_PROPERTY_COLUMNS)
        writer.writeheader()
        for item in inertial_body_inventory(reference):
            writer.writerow({
                **item,
                "mass_kg": "", "com_local_x_m": "", "com_local_y_m": "",
                "izz_kg_m2": "", "source": "", "confidence": "", "notes": "",
                "required_for_engineering_run": "true", "include_in_inertia": "true",
            })
    return target


def generate_synthetic_test_mass_properties(reference: ReferenceGeometry, path: str | Path) -> Path:
    """Generate deterministic test-only values; never use for engineering runs."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=MASS_PROPERTY_COLUMNS)
        writer.writeheader()
        for item in inertial_body_inventory(reference):
            body_id = item["body_id"]
            if body_id in reference.links:
                mass = 0.75
                length = reference.links[body_id].reference_length
                izz = mass * length**2 / 12.0
            elif body_id.startswith("SWING_"):
                mass, izz = 1.5, 0.035
            else:
                mass, izz = 3.0, 0.080
            writer.writerow({
                **item,
                "mass_kg": f"{mass:.12g}",
                "com_local_x_m": "0.0",
                "com_local_y_m": "0.0",
                "izz_kg_m2": f"{izz:.12g}",
                "source": ParameterSource.ASSUMED.value,
                "confidence": "0.0",
                "notes": SYNTHETIC_TEST_NOTE,
                "required_for_engineering_run": "false",
                "include_in_inertia": "true",
            })
    return target


def _as_bool(value: str, field_name: str) -> bool:
    normalized = value.strip().lower()
    if normalized in ("true", "1", "yes"):
        return True
    if normalized in ("false", "0", "no"):
        return False
    raise ValueError(f"{field_name} must be true or false")


def load_mass_properties_csv(
    path: str | Path,
    expected_body_ids: Iterable[str],
) -> MassPropertySet:
    missing_fields = []
    properties = []
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            body_id = row["body_id"].strip()
            required = _as_bool(row.get("required_for_engineering_run", "true"), "required_for_engineering_run")
            include = _as_bool(row.get("include_in_inertia", "true"), "include_in_inertia")
            value_fields = ("mass_kg", "com_local_x_m", "com_local_y_m", "izz_kg_m2", "source", "confidence")
            absent = [field for field in value_fields if not row.get(field, "").strip()]
            if absent and required:
                missing_fields.extend(f"{body_id}.{field}" for field in absent)
                continue
            if absent:
                continue
            properties.append(RigidBodyMassProperties(
                body_id=body_id,
                mass_kg=float(row["mass_kg"]),
                com_local_x_m=float(row["com_local_x_m"]),
                com_local_y_m=float(row["com_local_y_m"]),
                izz_kg_m2=float(row["izz_kg_m2"]),
                source=ParameterSource(row["source"].strip()),
                confidence=float(row["confidence"]),
                notes=row.get("notes", "").strip(),
                include_in_inertia=include,
            ))
    if missing_fields:
        preview = ", ".join(missing_fields[:8])
        suffix = " ..." if len(missing_fields) > 8 else ""
        raise MissingMechanicalParameterError(f"missing required values: {preview}{suffix}")
    result = MassPropertySet(properties)
    result.validate_complete(expected_body_ids)
    return result


def uniform_slender_rod_estimate(
    body_id: str,
    length_m: float,
    mass_kg: float,
    *,
    confidence: float = 0.1,
) -> RigidBodyMassProperties:
    """Return an explicitly ASSUMED estimate; never writes engineering config."""
    if length_m <= 0.0 or mass_kg <= 0.0:
        raise ValueError("rod length and mass must be positive")
    return RigidBodyMassProperties(
        body_id=body_id,
        mass_kg=mass_kg,
        com_local_x_m=0.0,
        com_local_y_m=0.0,
        izz_kg_m2=mass_kg * length_m**2 / 12.0,
        source=ParameterSource.ASSUMED,
        confidence=confidence,
        notes="uniform slender rod estimate; " + SYNTHETIC_TEST_NOTE,
    )
