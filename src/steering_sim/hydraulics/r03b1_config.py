"""Typed loading of generated R03-B1 configuration artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_json_config(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if "provenance" not in payload:
        raise ValueError(f"Configuration has no provenance: {path}")
    required = {"source_component", "source_submodel", "audit_file"}
    missing = required - set(payload["provenance"])
    if missing:
        raise ValueError(f"Configuration provenance missing {sorted(missing)}: {path}")
    return payload

