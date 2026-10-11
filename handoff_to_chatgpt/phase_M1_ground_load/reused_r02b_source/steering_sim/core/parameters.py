"""Traceable model-parameter metadata and controlled parameter storage."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Iterable, Iterator


class ParameterSource(str, Enum):
    CUSTOMER = "CUSTOMER"
    AMESIM = "AMESIM"
    DATASHEET = "DATASHEET"
    LITERATURE = "LITERATURE"
    CALIBRATED = "CALIBRATED"
    ASSUMED = "ASSUMED"


@dataclass(frozen=True, slots=True)
class ParameterMeta:
    """A value together with provenance needed for review and validation."""

    name: str
    value: float
    unit: str
    source: ParameterSource
    confidence: float
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("parameter name must not be empty")
        if not self.unit.strip():
            raise ValueError("parameter unit must not be empty")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")

    def with_value(self, value: float, *, notes: str | None = None) -> "ParameterMeta":
        """Return a provenance-preserving runtime update (e.g. degradation)."""
        return replace(self, value=float(value), notes=self.notes if notes is None else notes)


class ParameterSet:
    """Named parameter registry; concrete models receive this instead of literals."""

    def __init__(self, parameters: Iterable[ParameterMeta] = ()) -> None:
        self._items = {item.name: item for item in parameters}

    def __getitem__(self, name: str) -> ParameterMeta:
        return self._items[name]

    def __iter__(self) -> Iterator[ParameterMeta]:
        return iter(self._items.values())

    def update(self, parameter: ParameterMeta) -> None:
        """Replace a parameter explicitly, retaining the new provenance record."""
        if parameter.name not in self._items:
            raise KeyError(f"unknown parameter: {parameter.name}")
        self._items[parameter.name] = parameter

    def add(self, parameter: ParameterMeta) -> None:
        if parameter.name in self._items:
            raise KeyError(f"duplicate parameter: {parameter.name}")
        self._items[parameter.name] = parameter

    def values_dict(self) -> dict[str, float]:
        return {name: item.value for name, item in self._items.items()}

