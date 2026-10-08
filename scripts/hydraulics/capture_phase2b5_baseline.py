from __future__ import annotations

import csv
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "hydraulic_audit"


def read_csv(name: str) -> list[dict[str, str]]:
    with (AUDIT / name).open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def main() -> None:
    benchmark = next(row for row in read_csv("18E_fast_performance_benchmark.csv") if float(row["physical_time"]) == 1.0)
    timeseries = read_csv("18I_fast_key_timeseries.csv")
    selected = [
        key for key in timeseries[0]
        if key == "time_s" or key.startswith("pump01.") or key.startswith("actuator001.")
        or key.startswith("actuator001_1.") or key.startswith("actuator001_2.")
        or key.startswith("actuator002.") or key == "max_hydraulic_residual_m3_s"
    ]
    metrics: dict[str, dict[str, float]] = {}
    compact_series: dict[str, list[float]] = {}
    for key in selected:
        values = [float(row[key]) for row in timeseries]
        compact_series[key] = values
        if key != "time_s":
            metrics[key] = {
                "final": values[-1],
                "peak_abs": max(abs(value) for value in values),
                "rms": math.sqrt(sum(value * value for value in values) / len(values)),
            }
    payload = {
        "frozen": True,
        "source": ["18E_fast_performance_benchmark.csv", "18I_fast_key_timeseries.csv", "18J_fast_simulation_results.json"],
        "scenario": "steering_like",
        "solver": {"method": "BDF", "rtol": 1.0e-4, "atol": "18D_state_scaling.csv", "fast_states": 109, "fast_line_states": 67},
        "physical_time_s": 1.0,
        "wall_time_s": float(benchmark["wall_time"]),
        "real_time_factor": float(benchmark["real_time_factor"]),
        "nfev": int(benchmark["nfev"]),
        "njev": int(benchmark["njev"]),
        "nlu": int(benchmark["nlu"]),
        "solver_steps": int(benchmark["solver_steps"]),
        "algebraic_calls": int(benchmark["algebraic_solve_calls"]),
        "algebraic_iterations": int(benchmark["Newton_iterations"]),
        "metrics": metrics,
        "timeseries": compact_series,
    }
    path = AUDIT / "19A_performance_baseline.json"
    if path.exists():
        raise SystemExit("19A baseline already exists; refusing to overwrite frozen baseline")
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"FROZEN BASELINE = {payload['wall_time_s']:.6f} s; {len(metrics)} key outputs")


if __name__ == "__main__":
    main()
