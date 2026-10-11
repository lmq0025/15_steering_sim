from __future__ import annotations

import csv
import json
import math
import sys
import time
from pathlib import Path


ROOT = Path(r"E:\15_project")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "hydraulics"))

from run_phase_l1_r3_validation import Oracle
from steering_sim.hydraulics_lumped import LumpedHydraulicSystem
from steering_sim.hydraulics_lumped.simulation import simulate_rk4


def main() -> int:
    audit = ROOT / "hydraulic_audit_lumped"
    raw = json.loads((audit / "32_amesim_paired_raw.json").read_text(encoding="utf-8"))
    oracle = Oracle(raw["scenarios"]["S2"])
    model = LumpedHydraulicSystem()

    def periodic_inputs(t: float):
        phase = t - math.floor(t)
        if phase > 1.0 - 1e-12 and t > 0.0:
            phase = 1.0
        return oracle.inputs(phase)

    started = time.perf_counter()
    times, states = simulate_rk4(model, 100.0, 0.0005, periodic_inputs,
                                 oracle.initial_state())
    wall = time.perf_counter() - started
    pressure_columns = [0,1,4,5,8,9,12,13]
    if not (states[:, pressure_columns] == states[:, pressure_columns]).all():
        raise RuntimeError("NaN in 100 s benchmark")
    row = {
        "scenario":"S2_PERIODIC","physical_time_s":100.0,"dt_s":0.0005,
        "wall_time_s":wall,"measurement":"ACTUAL",
        "status":"PASS","final_time_s":float(times[-1]),
        "max_chamber_pressure_pa":float(states[:,pressure_columns].max()),
        "min_chamber_pressure_pa":float(states[:,pressure_columns].min()),
    }
    path = audit / "33K_runtime_benchmark.csv"
    rows = []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = [r for r in csv.DictReader(stream) if r["physical_time_s"] != "100.0"]
    fields = list(row)
    for existing in rows:
        for field in fields:
            existing.setdefault(field, "")
    rows.append(row)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)
    result_path = audit / "33L_phase_L1_R3_results.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["benchmark_100s"] = row
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(row, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
