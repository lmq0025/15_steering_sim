from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class BondGraphIR:
    ports: tuple[dict[str, str], ...]
    junctions: tuple[dict[str, str], ...]

    def validate(self) -> None:
        ids = {j["junction_id"] for j in self.junctions}
        missing = sorted({p["connected_junction"] for p in self.ports if p["connected_junction"] not in ids and p["connected_junction"] != "EXTERNAL_MECHANICAL_BOUNDARY"})
        if missing:
            raise ValueError(f"power ports reference missing junctions: {missing}")


def _read(path: Path) -> tuple[dict[str, str], ...]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return tuple(csv.DictReader(f))


def load_ir_v2(audit_dir: str | Path) -> BondGraphIR:
    root = Path(audit_dir)
    ir = BondGraphIR(_read(root / "12B_bondgraph_ports_v2.csv"), _read(root / "12C_bondgraph_junctions_v2.csv"))
    ir.validate()
    return ir
