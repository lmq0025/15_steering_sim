from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from ..assembly.state_mapper import StateIndex


PRESSURE_SUBMODELS = {"HA001", "HJ0022", "HJ020", "HJ021", "HL0000", "HL0002", "HL011", "HL012"}


@dataclass(frozen=True, slots=True)
class InitialCondition:
    state_index: int
    instance: str
    state: str
    initial_value_si: float
    source: str
    confidence: str


def build_initial_conditions(states: tuple[StateIndex, ...]) -> tuple[NDArray[np.float64], tuple[InitialCondition, ...]]:
    values = np.zeros(len(states), dtype=float)
    records: list[InitialCondition] = []
    for state in states:
        if state.submodel in PRESSURE_SUBMODELS:
            value = 1.0e5
            source = "engineering default: ambient/reference pressure; refined by steady_init"
            confidence = "LEVEL C"
        elif state.state_name.lower().startswith("x"):
            value = 0.0
            source = "Amesim parameter/metadata initial displacement or normalized spool position"
            confidence = "LEVEL B"
        elif state.state_name.lower().startswith("v"):
            value = 0.0
            source = "source-defined zero initial velocity"
            confidence = "LEVEL B"
        else:
            value = 0.0
            source = "documented engineering default"
            confidence = "LEVEL C"
        values[state.index] = value
        records.append(InitialCondition(state.index, state.instance, state.state_name, value, source, confidence))
    return values, tuple(records)


def build_state_scaling(states: tuple[StateIndex, ...]) -> tuple[NDArray[np.float64], NDArray[np.float64], list[dict[str, object]]]:
    scales = np.empty(len(states), dtype=float)
    atol = np.empty(len(states), dtype=float)
    rows: list[dict[str, object]] = []
    for state in states:
        if state.unit == "Pa":
            typical, absolute = 1.0e7, 100.0
        elif state.unit == "m":
            typical, absolute = 0.1, 1.0e-7
        elif state.unit == "m/s":
            typical, absolute = 1.0, 1.0e-6
        elif state.unit in {"1/s", "s^-1"}:
            typical, absolute = 10.0, 1.0e-6
        else:
            typical, absolute = 1.0, 1.0e-7
        scales[state.index], atol[state.index] = typical, absolute
        rows.append({"state_index": state.index, "state": f"{state.instance}.{state.state_name}", "unit": state.unit, "typical_scale": typical, "absolute_tolerance": absolute})
    return scales, atol, rows
