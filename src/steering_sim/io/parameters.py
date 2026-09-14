"""Serialization-neutral parameter export for later CSV/XLSX adapters."""

from __future__ import annotations

from typing import Iterable

from steering_sim.core.parameters import ParameterMeta


def parameter_records(parameters: Iterable[ParameterMeta]) -> list[dict[str, object]]:
    return [
        {
            "name": item.name,
            "value": item.value,
            "unit": item.unit,
            "source": item.source.value,
            "confidence": item.confidence,
            "notes": item.notes,
        }
        for item in parameters
    ]

