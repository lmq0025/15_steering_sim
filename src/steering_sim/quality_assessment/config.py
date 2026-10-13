"""Central, auditable D2 assessment assumptions."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class QualityConfig:
    raw: Mapping[str, Any]
    model_version: str
    assumption_tag: str

    @property
    def thresholds(self) -> Mapping[str, Mapping[str, Any]]:
        return self.raw["quality_thresholds"]

    @property
    def integration(self) -> Mapping[str, Any]:
        return self.raw["integration"]


def load_quality_config(path: str | Path) -> QualityConfig:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if raw.get("schema_version") != "D2.0":
        raise ValueError(f"unsupported D2 quality schema: {raw.get('schema_version')!r}")
    if raw.get("assumption_tag") != "ENGINEERING_DESIGN_ASSUMPTION":
        raise ValueError("D2 thresholds must be marked ENGINEERING_DESIGN_ASSUMPTION")
    expected = {"healthy", "subhealthy", "degraded", "direction"}
    for name, item in raw.get("quality_thresholds", {}).items():
        if not expected.issubset(item):
            raise ValueError(f"incomplete threshold for {name}")
        if item["direction"] not in ("max", "min"):
            raise ValueError(f"invalid threshold direction for {name}")
    return QualityConfig(raw=raw, model_version=str(raw["model_version"]),
                         assumption_tag=str(raw["assumption_tag"]))
