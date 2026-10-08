from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Topology:
    junction_ids: set[str] = field(default_factory=set)
    port_to_junction: dict[tuple[str, str], str] = field(default_factory=dict)

    def connect(self, element_id: str, port_id: str, junction_id: str) -> None:
        if junction_id not in self.junction_ids:
            raise KeyError(f"unknown junction: {junction_id}")
        self.port_to_junction[(element_id, str(port_id))] = junction_id

    def validate(self) -> None:
        missing = sorted({j for j in self.port_to_junction.values() if j not in self.junction_ids})
        if missing:
            raise ValueError(f"ports reference missing junctions: {missing}")
