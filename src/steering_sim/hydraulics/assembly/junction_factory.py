from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RuntimeJunction:
    junction_id: str
    level: int
    domain: str
    bg_type: str
    parent_supercomponent: str


class JunctionFactory:
    @staticmethod
    def create(row: dict[str, str]) -> RuntimeJunction:
        if row["domain"] == "hydraulic":
            bg_type = "0-junction"
        elif row["domain"] in {"translation", "rotation"}:
            bg_type = "1-junction"
        else:
            raise ValueError(f"unsupported junction domain: {row['domain']}")
        return RuntimeJunction(row["junction_id"], int(row["level"]), row["domain"], bg_type, row["parent_supercomponent"])
