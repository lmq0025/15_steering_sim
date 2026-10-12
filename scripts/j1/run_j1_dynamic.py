"""PHASE J1 第三/五关：代表性工况的**完整动态积分**与高速大转角适用性。

真实积分 16 个液压状态（四通道 × 四状态），实际轮角由**实际缸位移**经机构闭链
反求，不使用任何预设角度曲线。每个工况分别报告：

* ``NUMERICAL_COMPLETED``  —— 数值积分是否跑完
* ``TRACKING_PASS``        —— 是否跟上机构目标行程
* ``VEHICLE_DYNAMIC_INFEASIBLE`` —— 目标路径是否超出附着能力

三者分开，不允许用其中一个冒充另一个。
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from steering_sim.j0_coupling.config import J0CaseConfig, load_j0_config  # noqa: E402
from steering_sim.j0_coupling.mechanism import (ENGINEERING_STEERING_MODEL,  # noqa: E402
                                                build_mechanism_model)
from steering_sim.j0_coupling.reporting import (configure_chinese_font,  # noqa: E402
                                                write_samples_csv)
from steering_sim.j0_coupling.runner import J0Runner  # noqa: E402

SPEC = ROOT / "mechanical_model_input_spec_v1.0.yaml"
ENG_CONFIG = ROOT / "configs" / "j1" / "engineering_config.json"
ENG_DESIGN = ROOT / "configs" / "j1" / "engineering_mechanism.json"
J0_CONFIG = ROOT / "configs" / "j0" / "j0_config.json"

LOW_SPEED_CASES = (0.0, 2.0, -2.0, 5.0, -5.0, 10.0, -10.0, 20.0, -20.0, 30.0, -30.0)
HIGH_SPEED_CASES = ((80.0, 30.0), (80.0, -30.0), (80.0, 10.0), (60.0, 20.0))


def classify(summary: dict) -> str:
    """归因：先判目标路径本身是否物理可行，再判跟踪能力。"""
    if not summary.get("NUMERICAL_COMPLETED"):
        return f"数值求解失败：{summary.get('failure_reason')}"
    if (summary.get("target_path_adhesion_ratio") or 0.0) > 1.0:
        return ("目标路径超出附着能力（a_y > μg）：数值已完成，物理上不可行，"
                "不代表实际车辆能完成该路径")
    notes = " ".join(str(v) for v in summary.get("status_notes", []))
    if "不可达" in notes or "方向相反" in notes:
        return "作动行程不足或方向相反（控制命令不可达）"
    if "供油容量告警" in notes:
        return "供油不足"
    if (summary.get("control_saturation_fraction") or 0.0) > 0.5:
        return "控制饱和：阀门命令长期在上限，液压作动能力不足"
    if summary.get("VEHICLE_DYNAMIC_INFEASIBLE"):
        return "地面附着不足（实际状态 a_y > μg）"
    if not summary.get("TRACKING_PASS"):
        return "跟踪误差超差（传动比与液压力矩匹配不足）"
    return ""


def run_one(runner, target: float, speed: float, duration: float, out_dir: Path):
    case = J0CaseConfig(id=f"J1-{target:+.0f}-{speed:.0f}", target_outer_angle_deg=target,
                        speed_kmh=speed, duration_s=duration)
    started = time.perf_counter()
    result = runner.run_case(case)
    summary = dict(result.summary)
    record = {
        "case": case.id, "target_deg": target, "speed_kmh": speed,
        "duration_s": duration, "wall_s": round(time.perf_counter() - started, 2),
        "NUMERICAL_COMPLETED": bool(summary.get("NUMERICAL_COMPLETED")),
        "TRACKING_PASS": bool(summary.get("TRACKING_PASS")),
        "VEHICLE_DYNAMIC_INFEASIBLE": bool(summary.get("VEHICLE_DYNAMIC_INFEASIBLE")),
        "status": summary.get("status"),
        "failure_reason": summary.get("failure_reason"),
    }
    samples = result.samples
    if samples:
        record["max_tracking_error_vs_mechanism_deg"] = round(float(
            summary.get("max_steady_wheel_angle_error_vs_mechanism_deg", math.nan)), 4)
        record["control_saturation_fraction"] = round(float(
            summary.get("control_saturation_fraction", math.nan)), 4)
        record["valve_at_limit_sample_fraction"] = {
            k: round(float(v), 4)
            for k, v in (summary.get("valve_at_limit_sample_fraction") or {}).items()}
        record["max_unclipped_pid_request"] = {
            k: round(float(v), 3)
            for k, v in (summary.get("max_unclipped_pid_request") or {}).items()}
        record["stroke_target_mm"] = {k: round(float(v) * 1000, 1)
                                      for k, v in summary["target_x_ref_m"].items()}
        record["stroke_final_mm"] = {k: round(float(v) * 1000, 1)
                                     for k, v in summary["final_stroke_m"].items()}
        record["max_pressure_mpa_g"] = round(float(
            summary.get("max_pressure_mpa_g", math.nan)), 3)
        record["max_link_residual_m"] = float(summary.get("max_link_residual_m", math.nan))
        record["third_axle_max_abs_deg"] = float(
            summary.get("third_axle_max_abs_deg", math.nan))
        record["pump_capacity_warnings"] = int(summary.get("pump_capacity_warnings", 0))
        record["max_adhesion_utilization"] = round(float(
            summary.get("max_adhesion_utilization", math.nan)), 4)
        record["target_path_adhesion_ratio"] = round(float(
            summary.get("target_path_adhesion_ratio", math.nan)), 4)
        record["curvature_actual_1pm"] = summary.get("curvature_actual_1pm_max")
        record["curvature_target_1pm"] = summary.get("curvature_target_1pm")
        record["uses_actual_curvature"] = summary.get("uses_actual_curvature")
        record["non_finite"] = bool(any(
            not np.all(np.isfinite(np.asarray(v, dtype=float))) for v in samples.values()))
        mech = summary.get("target_mechanism_wheel_angle_deg", {})
        actu = {w: float(np.asarray(samples[f"wheel_{w}_actual_deg"])[-1])
                for w in mech}
        record["wheel_actual_deg"] = {w: round(v, 3) for w, v in actu.items()}
        record["wheel_mechanism_deg"] = {w: round(float(v), 3) for w, v in mech.items()}
        record["wheel_ideal_deg"] = {w: round(float(v), 3)
                                     for w, v in summary.get("target_wheel_angle_deg", {}).items()}
        sign = math.copysign(1.0, target) if abs(target) > 1e-9 else 0.0
        record["wheel_direction_ok"] = all(
            math.copysign(1.0, actu[f"axle{a}_{s}"]) == (-sign if a in (4, 5, 6) else sign)
            for a in range(1, 7) if a != 3 for s in ("left", "right")
            if abs(actu[f"axle{a}_{s}"]) > 0.05)
        record["left_right_same_sign"] = all(
            math.copysign(1.0, actu[f"axle{a}_left"]) == math.copysign(1.0, actu[f"axle{a}_right"])
            for a in (4, 5, 6) if abs(actu[f"axle{a}_left"]) > 0.05)
        write_samples_csv(result, out_dir / f"{case.id}_timeseries.csv")
    record["failure_class"] = classify(summary)
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "outputs" / "j1" / "dynamic"))
    parser.add_argument("--speed", type=float, default=5.0)
    parser.add_argument("--duration", type=float, default=2.0)
    args = parser.parse_args()
    configure_chinese_font()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    config = load_j0_config(J0_CONFIG)
    model = build_mechanism_model(
        ENGINEERING_STEERING_MODEL, SPEC,
        engineering_config_path=ENG_CONFIG, design_path=ENG_DESIGN)
    runner = J0Runner(config, model, probe_authority=False,
                      mechanical_mode=ENGINEERING_STEERING_MODEL)

    records = []
    print("== 第三关：低速代表工况（真实积分）==")
    for target in LOW_SPEED_CASES:
        record = run_one(runner, target, args.speed, args.duration, out)
        records.append(record)
        print(f"  {record['case']:>12s} NUM={record['NUMERICAL_COMPLETED']} "
              f"TRACK={record['TRACKING_PASS']} INFEAS={record['VEHICLE_DYNAMIC_INFEASIBLE']} "
              f"err={record.get('max_tracking_error_vs_mechanism_deg')} "
              f"sat={record.get('control_saturation_fraction')} -> {record['failure_class']}")
    print("== 第五关：高速大转角适用性 ==")
    for speed, target in HIGH_SPEED_CASES:
        record = run_one(runner, target, speed, args.duration, out)
        records.append(record)
        print(f"  {record['case']:>12s} NUM={record['NUMERICAL_COMPLETED']} "
              f"TRACK={record['TRACKING_PASS']} INFEAS={record['VEHICLE_DYNAMIC_INFEASIBLE']} "
              f"ady={record.get('max_adhesion_utilization')} -> {record['failure_class']}")

    payload = {"mode": "FULL_DYNAMIC", "speed_kmh": args.speed,
               "duration_s": args.duration, "records": records}
    (out / "j1_dynamic.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    completed = sum(1 for r in records if r["NUMERICAL_COMPLETED"])
    tracking = sum(1 for r in records if r["TRACKING_PASS"])
    print(f"\n数值完成 {completed}/{len(records)}；跟踪达标 {tracking}/{len(records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
