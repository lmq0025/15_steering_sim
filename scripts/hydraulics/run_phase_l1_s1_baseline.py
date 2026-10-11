from __future__ import annotations

import cProfile
import hashlib
import io
import json
import math
import pstats
import sys
import time
from pathlib import Path

import numpy as np


ROOT = Path(r"E:\15_project")
AUDIT = ROOT / "hydraulic_audit_lumped"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "hydraulics"))

from run_phase_l1_r3_validation import Oracle
from steering_sim.hydraulics_lumped import LumpedHydraulicSystem
from steering_sim.hydraulics_lumped.simulation import simulate_rk4


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_profile(duration: float, oracle: Oracle) -> tuple[dict, pstats.Stats]:
    model = LumpedHydraulicSystem()

    def periodic_inputs(t: float):
        phase = t - math.floor(t)
        if phase > 1.0 - 1.0e-12 and t > 0.0:
            phase = 1.0
        return oracle.inputs(phase)

    profiler = cProfile.Profile()
    started = time.perf_counter()
    profiler.enable()
    times, states = simulate_rk4(
        model, duration, 0.0005, periodic_inputs, oracle.initial_state())
    profiler.disable()
    wall = time.perf_counter() - started
    pressures = states[:, [0, 1, 4, 5, 8, 9, 12, 13]]
    stats = pstats.Stats(profiler)
    return {
        "physical_time_s": duration,
        "wall_time_s": wall,
        "real_time_factor": wall / duration,
        "steps": len(times) - 1,
        "rhs_calls": 4 * (len(times) - 1),
        "final_time_s": float(times[-1]),
        "max_chamber_pressure_pa": float(np.max(pressures)),
        "min_chamber_pressure_pa": float(np.min(pressures)),
        "final_state": states[-1].tolist(),
        "finite": bool(np.isfinite(states).all()),
    }, stats


def function_row(stats: pstats.Stats, needle: str) -> dict:
    rows = []
    for (filename, line, function), data in stats.stats.items():
        if needle in function or needle in filename:
            cc, nc, tt, ct, _ = data
            rows.append((ct, tt, nc, cc, filename, line, function))
    if not rows:
        return {"needle": needle, "calls": 0, "self_s": 0.0,
                "cumulative_s": 0.0, "location": "NOT_PRESENT"}
    rows.sort(reverse=True)
    ct, tt, nc, cc, filename, line, function = rows[0]
    return {"needle": needle, "calls": nc, "primitive_calls": cc,
            "self_s": tt, "cumulative_s": ct,
            "location": f"{Path(filename).name}:{line}:{function}"}


def main() -> int:
    raw = json.loads((AUDIT / "32_amesim_paired_raw.json").read_text(encoding="utf-8"))
    oracle = Oracle(raw["scenarios"]["S2"])
    one, one_stats = run_profile(1.0, oracle)
    ten, ten_stats = run_profile(10.0, oracle)

    r3_results = json.loads((AUDIT / "33L_phase_L1_R3_results.json").read_text(encoding="utf-8"))
    original_100 = r3_results["benchmark_100s"]
    baseline = {
        "phase": "L1-S1",
        "scenario": "S2_PERIODIC",
        "solver": "original R3 RK4",
        "dt_s": 0.0005,
        "dynamic_states": 16,
        "pipe_dynamic_states": 0,
        "physics_equations_changed": False,
        "runs": {"1s": one, "10s": ten, "100s_frozen": original_100},
        "environment": {"python": sys.executable, "numpy": np.__version__},
        "protected_model_hashes": {
            name: sha256(ROOT / name)
            for name in ("qh1_1.ame", "qh1_1_MCP_AUDIT.ame")
        },
    }
    (AUDIT / "35A_original_performance_baseline.json").write_text(
        json.dumps(baseline, indent=2), encoding="utf-8")

    needles = [
        "solve_sc1_load_sensing_network", "network_at_low", "return_residual",
        "brentq", "sc1_four_port_flows", "fractional_area_percent",
        "characteristic_orifice_flow", "evaluate", "inputs", "simulate_rk4",
    ]
    rows = [function_row(ten_stats, name) for name in needles]
    stream = io.StringIO()
    ten_stats.stream = stream
    ten_stats.sort_stats("cumulative").print_stats(40)
    report = [
        "# Phase L1-S1 original runtime profile",
        "",
        "This profile freezes the unmodified Phase L1-R3 S2 periodic workload. "
        "It uses RK4 with a 0.5 ms step and prescribed Amesim motion boundary.",
        "",
        f"- 1 s wall time: {one['wall_time_s']:.6f} s",
        f"- 10 s wall time: {ten['wall_time_s']:.6f} s",
        f"- Frozen measured 100 s wall time: {float(original_100['wall_time_s']):.6f} s",
        f"- 10 s RHS calls: {ten['rhs_calls']}",
        "",
        "## Required hotspot categories",
        "",
        "| category | calls | self s | cumulative s | matched location |",
        "|---|---:|---:|---:|---|",
    ]
    for row in rows:
        report.append(
            f"| {row['needle']} | {row['calls']} | {row['self_s']:.6f} | "
            f"{row['cumulative_s']:.6f} | {row['location']} |")
    report.extend(["", "## Top 40 cumulative profile entries", "", "```text",
                   stream.getvalue().rstrip(), "```", ""])
    (AUDIT / "35B_runtime_profile.md").write_text("\n".join(report), encoding="utf-8")
    print(json.dumps(baseline, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
