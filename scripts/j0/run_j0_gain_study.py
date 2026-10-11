"""PHASE J0 PID gain sensitivity study.

Answers one question with evidence: can the four-channel loop be closed on the
delivered L1-Fast V1 plant by control tuning alone, at the J0-fixed 10 ms control
period and with the existing unfiltered ``PIDController``?

The study never changes the plant or the hydraulic equations; it only changes
``(kp, ki, kd)``.  Results are written to JSON and CSV next to the J0 report.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mechanics_ackermann_v2.model import PhaseM1Model  # noqa: E402
from steering_sim.j0_coupling.config import J0CaseConfig, load_j0_config  # noqa: E402
from steering_sim.j0_coupling.reporting import write_summary_json  # noqa: E402
from steering_sim.j0_coupling.runner import J0Runner  # noqa: E402

REAR_CHANNELS = ("channel_rear_1", "channel_rear_2", "channel_rear_3")

GRID = [
    (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0), (5.0, 0.0, 0.0),
    (10.0, 0.0, 0.0), (20.0, 0.0, 0.0), (40.0, 0.0, 0.0),
    (2.0, 0.2, 0.0), (5.0, 0.5, 0.0), (20.0, 2.0, 0.0),
    (2.0, 0.0, 2.0), (2.0, 0.0, 5.0), (2.0, 0.0, 10.0), (5.0, 0.0, 20.0),
    (1.0, 0.0, 30.0), (0.5, 0.0, 100.0), (20.0, 0.0, 60.0), (40.0, 0.0, 150.0),
    (2.0, 0.2, 20.0), (40.0, 4.0, 0.4),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(ROOT / "configs" / "j0" / "j0_config.json"))
    parser.add_argument("--output", default=str(ROOT / "outputs" / "j0" / "gain_study"))
    parser.add_argument("--case", default="J0-02")
    parser.add_argument("--duration", type=float, default=1.0)
    args = parser.parse_args()

    config = load_j0_config(args.config)
    model = PhaseM1Model(ROOT / "mechanical_model_input_spec_v1.0.yaml",
                         ROOT / "mechanics_ackermann_v2" / "config.json")
    runner = J0Runner(config, model, probe_authority=False)
    base = next(case for case in config.cases if case.id == args.case)
    case = J0CaseConfig(base.id, base.target_outer_angle_deg, base.speed_kmh, args.duration)

    rows = []
    for kp, ki, kd in GRID:
        gains = {"channel_front": (0.0, 0.0, 0.0)}
        for name in REAR_CHANNELS:
            gains[name] = (kp, ki, kd)
        result = runner.run_case(case, gains=gains)
        summary = result.summary
        rows.append({
            "kp": kp, "ki": ki, "kd": kd,
            "completed": result.completed,
            "failure_time_s": result.failure_time_s,
            "failure_reason": result.failure_reason,
            "status": summary["status"],
            "max_stroke_error_m": summary["max_stroke_error_m"],
            "max_steady_wheel_angle_error_deg": summary["max_steady_wheel_angle_error_deg"],
            "max_abs_velocity_m_s": summary["max_abs_velocity_m_s"],
            "max_pressure_mpa_g": summary["max_pressure_mpa_g"],
        })
        print(f"kp={kp:6.1f} ki={ki:5.1f} kd={kd:6.1f} completed={result.completed} "
              f"t_fail={result.failure_time_s} reason={result.failure_reason}")

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    write_summary_json({"case": case.id, "duration_s": args.duration, "grid": rows},
                       output / f"gain_study_{case.id}.json")
    with (output / f"gain_study_{case.id}.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
