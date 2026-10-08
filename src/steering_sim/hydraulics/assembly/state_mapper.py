from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


LINE_SUBMODELS = {"HL0000", "HL0002", "HL011", "HL012"}


@dataclass(frozen=True, slots=True)
class StateIndex:
    index: int
    instance: str
    submodel: str
    state_name: str
    domain: str
    unit: str
    fidelity_mode: str
    source_states: str


def _read(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


class StateMapper:
    @staticmethod
    def full(state_csv: Path) -> tuple[StateIndex, ...]:
        rows = _read(state_csv)
        return tuple(
            StateIndex(index, row["instance"], row["submodel"], row["state_name"], row["state_domain"], "Pa" if row["unit"] == "bar" else row["unit"], "FULL", row["state_name"])
            for index, row in enumerate(rows)
        )

    @staticmethod
    def fast(state_csv: Path, reduction_csv: Path) -> tuple[StateIndex, ...]:
        rows = _read(state_csv)
        reduction = {row["instance"]: row for row in _read(reduction_csv)}
        entries: list[StateIndex] = []
        for row in rows:
            if row["submodel"] not in LINE_SUBMODELS:
                entries.append(StateIndex(len(entries), row["instance"], row["submodel"], row["state_name"], row["state_domain"], "Pa" if row["unit"] == "bar" else row["unit"], "FAST", row["state_name"]))
        by_instance: dict[str, list[dict[str, str]]] = {}
        for row in rows:
            if row["submodel"] in LINE_SUBMODELS:
                by_instance.setdefault(row["instance"], []).append(row)
        for instance in sorted(by_instance):
            original = by_instance[instance]
            count = int(reduction[instance]["fast_state_count"])
            for cell in range(count):
                name = "p_eq" if count == 1 else f"p_eq_{cell + 1}"
                entries.append(StateIndex(len(entries), instance, original[0]["submodel"], name, "hydraulic", "Pa", "FAST", ";".join(row["state_name"] for row in original)))
        return tuple(entries)
