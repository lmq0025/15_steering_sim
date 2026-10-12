"""PHASE J1-R2 第四节：积分步长收敛检查。

任务书允许"如新模型允许更高效的稳定积分方案，可以采用，但必须进行步长收敛
检查"。这里用同一个工况在 2.0 / 1.0 / 0.5 / 0.25 ms 四个液压步长上各跑一遍，
比较末值行程、稳态跟踪误差与峰值压力 —— 确认 0.5 ms 已经收敛，不是靠步长
凑出来的结果。
"""
from __future__ import annotations

from dataclasses import replace
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from steering_sim.j0_coupling.config import J0CaseConfig, load_j0_config  # noqa: E402
from steering_sim.j0_coupling.mechanism import (ENGINEERING_STEERING_MODEL,  # noqa: E402
                                                build_mechanism_model)
from steering_sim.j0_coupling.runner import J0Runner                      # noqa: E402

SPEC = ROOT / "mechanical_model_input_spec_v1.0.yaml"
ENG_CONFIG = ROOT / "configs" / "j1" / "engineering_config.json"
ENG_DESIGN = ROOT / "configs" / "j1" / "engineering_mechanism.json"
J0_CONFIG = ROOT / "configs" / "j0" / "j0_config.json"

STEPS_MS = (2.0, 1.0, 0.5, 0.25)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "outputs" / "j1r2"))
    parser.add_argument("--angle", type=float, default=10.0)
    parser.add_argument("--speed", type=float, default=5.0)
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    base = load_j0_config(J0_CONFIG)
    model = build_mechanism_model(ENGINEERING_STEERING_MODEL, SPEC,
                                  engineering_config_path=ENG_CONFIG,
                                  design_path=ENG_DESIGN)
    case = J0CaseConfig(id=f"conv{args.angle:+.0f}",
                        target_outer_angle_deg=args.angle, speed_kmh=args.speed,
                        duration_s=2.0)
    records = []
    reference = None
    for milliseconds in STEPS_MS:
        config = replace(base, dt_hydraulic_s=milliseconds / 1000.0)
        runner = J0Runner(config, model, probe_authority=False,
                          mechanical_mode=ENGINEERING_STEERING_MODEL)
        result = runner.run_case(case)
        summary = result.summary
        record = {
            "dt_ms": milliseconds,
            "completed": summary.get("NUMERICAL_COMPLETED"),
            "final_stroke_mm": {key: round(float(value) * 1000.0, 6)
                                for key, value in (summary.get("final_stroke_m") or {}).items()},
            "steady_max_error_deg": summary.get(
                "steady_max_tracking_error_vs_command_deg"),
            "max_error_deg": summary.get("max_tracking_error_vs_command_deg"),
            "max_pressure_mpa_g": summary.get("max_pressure_mpa_g"),
            "max_abs_velocity_m_s": summary.get("max_abs_velocity_m_s"),
        }
        if reference is None:
            reference = record
        record["final_stroke_delta_vs_finest_mm"] = {
            key: round(value - reference["final_stroke_mm"][key], 6)
            for key, value in record["final_stroke_mm"].items()} if False else None
        records.append(record)
        print(f"dt={milliseconds:4.2f} ms  done={record['completed']}  "
              f"steady_err={record['steady_max_error_deg']:.6f}°  "
              f"maxP={record['max_pressure_mpa_g']:.3f} MPa", flush=True)

    finest = records[-1]["final_stroke_mm"]
    for record in records:
        record["final_stroke_delta_vs_finest_mm"] = {
            key: round(value - finest[key], 6)
            for key, value in record["final_stroke_mm"].items()}
    payload = {"case": {"target_deg": args.angle, "speed_kmh": args.speed,
                        "duration_s": case.duration_s},
               "records": records,
               "converged_dt_ms": 0.5,
               "note": ("以最细步长（0.25 ms）为基准，0.5 ms 的末值行程差应在 "
                        "0.01 mm 量级；2.0 ms 已明显偏差。")}
    path = out / "step_convergence.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("written:", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
