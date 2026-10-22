"""Run the D4-R1 real 22-state ramp acceptance matrix."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
for item in (ROOT, ROOT / "src"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from steering_sim.desktop.services import DesktopCalculationService


OUTPUT = ROOT / "outputs" / "desktop" / "r1"
CASES = (
    ("0_to_p2", 0.0, 2.0),
    ("0_to_p5", 0.0, 5.0),
    ("0_to_p10", 0.0, 10.0),
    ("0_to_n10", 0.0, -10.0),
    ("p10_to_n10", 10.0, -10.0),
    ("0_to_p30", 0.0, 30.0),
)


def run(selected: set[str] | None = None) -> Path:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    service = DesktopCalculationService(OUTPUT / "ramp_acceptance_runs")
    rows: list[dict[str, object]] = []
    for name, initial, final in CASES:
        if selected and name not in selected:
            continue
        started = time.perf_counter()
        print(f"START {name}: {initial:+g} -> {final:+g} deg", flush=True)
        result = service.run_simulation(
            scenario={
                "command_type": "ramp",
                "initial_outer_angle_deg": initial,
                "target_outer_angle_deg": final,
                "seconds_per_degree": 6.0,
                "hold_observation_s": 5.0,
                "speed_kmh": 5.0,
                "friction_coefficient": 0.8,
                "duration_s": 5.0,
                "axle_mass_t": [11.5] * 6,
            },
            progress=lambda fraction, message: None,
            is_cancelled=lambda: False,
        )
        elapsed = time.perf_counter() - started
        response = result["response"]
        result["wheel_response_table"].to_csv(
            OUTPUT / f"wheel_response_times_{name}.csv", index=False, encoding="utf-8-sig")
        result["cylinder_response_table"].to_csv(
            OUTPUT / f"cylinder_response_times_{name}.csv", index=False, encoding="utf-8-sig")
        row = {
            "case": name,
            "initial_outer_angle_deg": initial,
            "final_outer_angle_deg": final,
            "seconds_per_degree": 6.0,
            "hydraulic_step_s": response["criteria"].slow_ramp_hydraulic_step_s,
            "command_completion_s": response["command_completion_s"],
            "all_wheels_settled_s": response["all_wheels_settled_s"],
            "all_cylinders_settled_s": response["all_cylinders_settled_s"],
            "system_settled_s": response["system_settled_s"],
            "system_status": response["system_status"],
            "runner_wall_s": result["runtime_s"],
            "service_wall_s": elapsed,
            "calculation_success": result["calculation_success"],
            "timeseries_csv": result["csv_path"],
        }
        rows.append(row)
        print("DONE " + json.dumps(row, ensure_ascii=False), flush=True)
        path = OUTPUT / "ramp_acceptance_summary.json"
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return OUTPUT / "ramp_acceptance_summary.json"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("cases", nargs="*", help="Optional case IDs; default runs all six.")
    args = parser.parse_args()
    print(run(set(args.cases) if args.cases else None))
