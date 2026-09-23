"""R03-B1 evidence-bound demo; records blockers instead of inventing dynamics."""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from steering_sim.hydraulics.r03b1_errors import UnresolvedAmesimUtilityError
from steering_sim.hydraulics.r03b1_factory import build_r03b1_rig
from steering_sim.hydraulics.single_actuator_rig import PrescribedBoundary

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "hydraulics" / "r03b1"
OUTPUT = ROOT / "outputs" / "r03b1_single_actuator" / "r03b1_blocked_diagnostic.csv"


def main() -> int:
    rig = build_r03b1_rig(CONFIG)
    rows = []
    for command in (-1.0, -0.5, 0.0, 0.5, 1.0):
        observation = rig.valve.openings(command)
        row = {"command": command, "fractional_spool_position": observation.fractional_spool_position}
        row.update({f"opening_{name}": value for name, value in observation.openings.items()})
        rows.append(row)
    boundary = PrescribedBoundary(0.5, 10e6, 0.0, 0.05, 0.0)
    try:
        rig.rhs(0.0, np.array([0.0, 0.0]), boundary)
        status, reason = "UNEXPECTED_RUN", ""
    except UnresolvedAmesimUtilityError as exc:
        status, reason = "BLOCKED_BY_TRACEABILITY_GUARD", str(exc)
    for row in rows:
        row["dynamic_run_status"] = status
        row["blocker"] = reason
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print("R03-B1: static SC_1 mapping evaluated from frozen configuration")
    print(f"Dynamic run: {status}")
    print(f"Reason: {reason}")
    print(f"Evidence CSV: {OUTPUT}")
    print("No pressure/force time history or plot was generated; no AMESim-equivalent RHS is yet justified.")
    return 2 if status.startswith("BLOCKED") else 0


if __name__ == "__main__":
    raise SystemExit(main())

