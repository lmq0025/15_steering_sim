"""Shared, data-only helpers for R03-B1.5 experiment analysis.

These helpers do not implement hydraulic constitutive equations.  They validate
exported AMESim data, keep identification and validation sets separate, and
compute descriptive statistics.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


BASELINE_SHA256 = "7613615723973D66A7122C74956C5161F720A64B243139FE9736CB270303B767"
BAR_TO_PA = 100_000.0
LPM_TO_M3PS = 1.0e-3 / 60.0


class ExperimentDataError(ValueError):
    """Raised when an AMESim export is incomplete or internally inconsistent."""


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def require_columns(frame: pd.DataFrame, required: Iterable[str], *, label: str) -> None:
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise ExperimentDataError(f"{label} missing required columns: {missing}")


def assert_unique(frame: pd.DataFrame, column: str, *, label: str) -> None:
    duplicated = frame.loc[frame[column].duplicated(), column].astype(str).tolist()
    if duplicated:
        raise ExperimentDataError(f"{label} has duplicate {column}: {duplicated[:5]}")


def assert_split_integrity(frame: pd.DataFrame) -> None:
    require_columns(frame, ["test_id", "set_role"], label="experiment matrix")
    roles = set(frame["set_role"].dropna().astype(str))
    if not roles.issubset({"identification", "validation"}):
        raise ExperimentDataError(f"unsupported set_role values: {sorted(roles)}")
    grouped = frame.groupby("test_id", dropna=False)["set_role"].nunique()
    leaking = grouped[grouped > 1]
    if not leaking.empty:
        raise ExperimentDataError(
            f"identification/validation leakage for test_id: {leaking.index.tolist()[:5]}"
        )


def estimate_linear_slope(
    time_s: Iterable[float], values: Iterable[float], *, start_s: float, end_s: float
) -> float:
    """Estimate a local derivative by least-squares, never one-step differencing."""

    t = np.asarray(list(time_s), dtype=float)
    y = np.asarray(list(values), dtype=float)
    mask = np.isfinite(t) & np.isfinite(y) & (t >= start_s) & (t <= end_s)
    if np.count_nonzero(mask) < 3 or np.unique(t[mask]).size < 3:
        raise ExperimentDataError(
            f"at least three finite, distinct samples required in [{start_s}, {end_s}] s"
        )
    slope, _ = np.polyfit(t[mask], y[mask], 1)
    return float(slope)


def error_metrics(actual: Iterable[float], predicted: Iterable[float], *, relative_floor: float) -> dict:
    a = np.asarray(list(actual), dtype=float)
    p = np.asarray(list(predicted), dtype=float)
    if a.shape != p.shape or a.size == 0:
        raise ExperimentDataError("actual and predicted arrays must be non-empty and aligned")
    residual = p - a
    relative_mask = np.abs(a) >= float(relative_floor)
    max_relative = (
        float(np.max(np.abs(residual[relative_mask] / a[relative_mask])))
        if np.any(relative_mask)
        else float("nan")
    )
    return {
        "mae": float(np.mean(np.abs(residual))),
        "rmse": float(np.sqrt(np.mean(residual**2))),
        "max_abs_error": float(np.max(np.abs(residual))),
        "max_relative_error": max_relative,
        "relative_floor": float(relative_floor),
    }


def ensure_within(value: float, lower: float, upper: float, *, name: str) -> None:
    if not np.isfinite(value) or value < lower or value > upper:
        raise ExperimentDataError(f"{name}={value!r} outside frozen range [{lower}, {upper}]")

