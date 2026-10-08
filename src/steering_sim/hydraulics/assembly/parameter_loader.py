from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ParameterValue:
    title: str
    raw_value: str
    resolved_value: str
    source_unit: str
    si_value: float | str
    si_unit: str


_UNIT_SCALE = {
    "bar": (1.0e5, "Pa"),
    "bara": (1.0e5, "Pa"),
    "l/min": (1.0 / 60000.0, "m^3/s"),
    "cm**3": (1.0e-6, "m^3"),
    "cc": (1.0e-6, "m^3"),
    "mm": (1.0e-3, "m"),
    "mm**2": (1.0e-6, "m^2"),
    "rev/min": (2.0 * 3.141592653589793 / 60.0, "rad/s"),
}


def _read(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _convert(value: str, unit: str) -> tuple[float | str, str]:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return value, unit
    scale, si_unit = _UNIT_SCALE.get(unit.strip().lower(), (1.0, unit or "1"))
    return numeric * scale, si_unit


@dataclass(frozen=True, slots=True)
class ParameterDatabase:
    by_alias: dict[str, tuple[ParameterValue, ...]]
    globals: dict[str, float | str]

    @classmethod
    def load(cls, parameter_csv: Path, global_csv: Path) -> "ParameterDatabase":
        global_values: dict[str, float | str] = {}
        for row in _read(global_csv):
            try:
                global_values[row["name"]] = float(row["raw_value"])
            except ValueError:
                global_values[row["name"]] = row["raw_value"]
        grouped: dict[str, list[ParameterValue]] = {}
        for row in _read(parameter_csv):
            value, unit = _convert(row["resolved_value"], row["unit"])
            grouped.setdefault(row["alias"], []).append(
                ParameterValue(row["title"], row["raw_value"], row["resolved_value"], row["unit"], value, unit)
            )
        return cls({key: tuple(values) for key, values in grouped.items()}, global_values)

    def for_alias(self, alias: str) -> tuple[ParameterValue, ...]:
        return self.by_alias.get(alias, ())
