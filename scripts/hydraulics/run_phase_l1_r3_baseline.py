from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(r"E:\15_project")
sys.path.insert(0, str(ROOT / "src"))

from steering_sim.hydraulics_lumped import LumpedHydraulicSystem, SystemInputs
from steering_sim.hydraulics_lumped.simulation import simulate_rk4

AUD = ROOT / "hydraulic_audit_lumped"
RAW = AUD / "32_amesim_paired_raw.json"
ACTUATORS = ["actuator002", "actuator001", "actuator001_1", "actuator001_2"]
PRIMARY_VALVES = ["dirvalve_6", "dirvalve_1", "dirvalve_8", "dirvalve_11"]
ALL_VALVES = ["dirvalve_1", "dirvalve_2", "dirvalve_6", "dirvalve_8",
              "dirvalve_9", "dirvalve_11", "dirvalve_12"]
PUMPS = ["pump01", "pump01_1", "pump01_2", "pump01_3"]


def _series(record: dict, path: str) -> np.ndarray:
    return np.asarray(record["series"][path], dtype=float)


def _value(record: dict, path: str, t: float) -> float:
    data = _series(record, path)
    return float(np.interp(t, data[:, 0], data[:, 1]))


def _inputs(record: dict, t: float) -> SystemInputs:
    valve = {a: _value(record, "signal_input@" + a, t) for a in ALL_VALVES}
    pump = {a: _value(record, "speed@" + a, t) * 2.0 * math.pi / 60.0 for a in PUMPS}
    motion = {}
    for alias in ACTUATORS:
        left, right = max(0.0, t - 0.001), min(1.0, t + 0.001)
        acceleration = (_value(record, "v@" + alias, right)
                        - _value(record, "v@" + alias, left)) / max(right - left, 1e-12)
        motion[alias] = (_value(record, "x@" + alias, t),
                         _value(record, "v@" + alias, t), acceleration)
    return SystemInputs(
        [valve[a] for a in PRIMARY_VALVES],
        [pump["pump01"], pump["pump01_2"], pump["pump01_2"], pump["pump01_2"]],
        [0.0] * 4, pump_speeds_by_alias=pump,
        valve_commands_by_alias=valve, prescribed_motion_by_alias=motion)


def _initial(record: dict) -> np.ndarray:
    state = np.zeros(16)
    for i, alias in enumerate(ACTUATORS):
        state[4 * i:4 * i + 4] = [
            _value(record, "p1@" + alias, 0.0) * 1e5,
            _value(record, "p2@" + alias, 0.0) * 1e5,
            _value(record, "x@" + alias, 0.0),
            _value(record, "v@" + alias, 0.0),
        ]
    return state


def main() -> int:
    raw = json.loads(RAW.read_text(encoding="utf-8"))
    record = raw["scenarios"]["S1"]
    model = LumpedHydraulicSystem()
    times, states = simulate_rk4(model, 1.0, 0.0005,
                                 lambda t: _inputs(record, t), _initial(record))
    rows: list[dict] = []
    for k, t in enumerate(times):
        inputs = _inputs(record, float(t))
        dx, outputs = model.evaluate(float(t), states[k], inputs)
        for i, (channel, actuator) in enumerate(zip(model.channels, ACTUATORS)):
            out = outputs[i]
            rows.append({
                "stage": "R3-0_R2_BASELINE", "scenario": "S1", "time_s": float(t),
                "channel": channel.name, "actuator": actuator,
                "pump_outlet_pressure_pa_g": out["pump_outlet_pressure"],
                "valve_manifold_pressure_pa_g": out["manifold_pressure"],
                "pA_pa_g": out["pA"], "pB_pa_g": out["pB"],
                "QA_m3_s": out["QA"], "QB_m3_s": out["QB"],
                "prescribed_x_m": out["position"], "prescribed_v_m_s": out["velocity"],
                "primary_valve_command": inputs.valve_commands[i],
                "maximum_branch_opening_m2": out["valve_opening"],
                "group_pump_flow_m3_s": out["group_pump_flow"],
                "relief_flow_m3_s": out["relief_flow"],
                "dpA_dt_pa_s": float(dx[4 * i]), "dpB_dt_pa_s": float(dx[4 * i + 1]),
                "hydraulic_force_n": out["hydraulic_force"],
                "source_type": "PYTHON_SIMULATED_R2_FROZEN_BASELINE",
            })
    target = AUD / "33A_baseline_pressure_failure_trace.csv"
    with target.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    max_pressure = max(max(r["pA_pa_g"], r["pB_pa_g"]) for r in rows)
    print(f"ROWS={len(rows)} MAX_CHAMBER_PRESSURE_PA={max_pressure:.9g} OUTPUT={target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
