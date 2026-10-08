from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class HydraulicZeroJunction:
    junction_id: str

    @staticmethod
    def common_pressure_residuals(pressures_pa: Iterable[float]) -> tuple[float, ...]:
        values = tuple(float(x) for x in pressures_pa)
        return tuple(x - values[0] for x in values[1:]) if values else ()

    @staticmethod
    def flow_balance_m3_s(flows_into_junction_m3_s: Iterable[float]) -> float:
        return sum(float(x) for x in flows_into_junction_m3_s)


@dataclass(frozen=True, slots=True)
class MechanicalOneJunction:
    junction_id: str
    domain: str

    def __post_init__(self) -> None:
        if self.domain not in {"translation", "rotation"}:
            raise ValueError("mechanical 1-junction domain must be translation or rotation")

    @staticmethod
    def common_flow_residuals(flows: Iterable[float]) -> tuple[float, ...]:
        values = tuple(float(x) for x in flows)
        return tuple(x - values[0] for x in values[1:]) if values else ()

    @staticmethod
    def effort_balance(efforts_into_junction: Iterable[float]) -> float:
        return sum(float(x) for x in efforts_into_junction)
