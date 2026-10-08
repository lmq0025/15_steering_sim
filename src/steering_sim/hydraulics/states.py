"""State and algebraic-vector descriptors for hydraulic prototypes."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StateVariable:
    name: str
    unit: str
    initial_value: float
    domain: str


@dataclass(frozen=True, slots=True)
class AlgebraicVariable:
    name: str
    unit: str
    domain: str
