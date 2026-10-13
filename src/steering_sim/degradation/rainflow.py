"""Dependency-free ASTM-style four-point rainflow counting for D3."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Sequence


@dataclass(frozen=True, slots=True)
class RainflowCycle:
    range_value: float
    mean_value: float
    count: float
    start_index: int
    end_index: int

    @property
    def amplitude(self) -> float:
        return 0.5 * self.range_value


def turning_points(values: Sequence[float]) -> list[tuple[int, float]]:
    """Return endpoints and strict reversals while removing flat duplicates."""
    clean: list[tuple[int, float]] = []
    for index, raw in enumerate(values):
        value = float(raw)
        if not math.isfinite(value):
            raise ValueError("rainflow input contains NaN/Inf")
        if not clean or value != clean[-1][1]:
            clean.append((index, value))
        else:
            clean[-1] = (index, value)
    if len(clean) <= 2:
        return clean
    result = [clean[0]]
    for previous, current, following in zip(clean, clean[1:], clean[2:]):
        if ((current[1] - previous[1]) * (following[1] - current[1])) < 0.0:
            result.append(current)
    result.append(clean[-1])
    return result


def count_rainflow(values: Sequence[float]) -> tuple[RainflowCycle, ...]:
    """Count closed cycles and residual half cycles without segment resets."""
    stack: list[tuple[int, float]] = []
    cycles: list[RainflowCycle] = []
    for point in turning_points(values):
        stack.append(point)
        while len(stack) >= 3:
            older, previous, latest = stack[-3], stack[-2], stack[-1]
            older_range = abs(previous[1] - older[1])
            newer_range = abs(latest[1] - previous[1])
            if newer_range < older_range:
                break
            count = 0.5 if len(stack) == 3 else 1.0
            cycles.append(RainflowCycle(
                range_value=older_range,
                mean_value=0.5 * (older[1] + previous[1]), count=count,
                start_index=older[0], end_index=previous[0]))
            if len(stack) == 3:
                del stack[0]
            else:
                del stack[-3:-1]
    for first, second in zip(stack, stack[1:]):
        cycles.append(RainflowCycle(
            range_value=abs(second[1] - first[1]),
            mean_value=0.5 * (first[1] + second[1]), count=0.5,
            start_index=first[0], end_index=second[0]))
    return tuple(item for item in cycles if item.range_value > 0.0)


def equivalent_cycle_load(cycles: Iterable[RainflowCycle], *, exponent: float,
                          reference: float) -> dict[str, float]:
    if exponent <= 0.0 or reference <= 0.0:
        raise ValueError("rainflow exponent/reference must be positive")
    items = tuple(cycles)
    equivalent_exposure = sum(
        item.count * (item.range_value / reference) ** exponent for item in items)
    total_count = sum(item.count for item in items)
    equivalent_range = (reference * (equivalent_exposure / total_count)
                                  ** (1.0 / exponent)
                        if total_count > 0.0 else 0.0)
    return {"cycle_count": total_count,
            "equivalent_exposure": equivalent_exposure,
            "equivalent_range": equivalent_range,
            "maximum_range": max((item.range_value for item in items), default=0.0)}


def rainflow_matrix(cycles: Iterable[RainflowCycle], *, range_bins: int = 10,
                    mean_bins: int = 10) -> list[dict[str, float]]:
    """Create a compact deterministic range/mean matrix without numpy."""
    items = tuple(cycles)
    if not items:
        return []
    max_range = max(item.range_value for item in items)
    min_mean = min(item.mean_value for item in items)
    max_mean = max(item.mean_value for item in items)
    range_width = max(max_range / range_bins, 1.0e-15)
    mean_width = max((max_mean - min_mean) / mean_bins, 1.0e-15)
    cells: dict[tuple[int, int], float] = {}
    for item in items:
        rbin = min(range_bins - 1, int(item.range_value / range_width))
        mbin = min(mean_bins - 1, int((item.mean_value - min_mean) / mean_width))
        cells[(rbin, mbin)] = cells.get((rbin, mbin), 0.0) + item.count
    return [{
        "range_bin_lower": rbin * range_width,
        "range_bin_upper": (rbin + 1) * range_width,
        "mean_bin_lower": min_mean + mbin * mean_width,
        "mean_bin_upper": min_mean + (mbin + 1) * mean_width,
        "cycle_count": count,
    } for (rbin, mbin), count in sorted(cells.items())]
