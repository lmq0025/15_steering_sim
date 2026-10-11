"""PHASE M3：优化设计机构的代表性动态工况验证。

任务书第十三节要求先验证 ``0°/±2°/±5°/±10°/±20°/±30°``（低速优先），并且：

* **必须真实积分液压状态**，不得用预设角度曲线替代；
* 检查四组执行器实际运动、十二轮机械实际角、方向、三桥锁零、缸行程、
  压力、阀门命令是否永久饱和、地面载荷是否反馈、NaN/Inf、分支跳变、镜像；
* 达不成的工况必须说明是**缸行程不足 / 液压力不足 / 传动比不合理 /
  地面附着不足 / 控制饱和 / 数值求解失败**中的哪一种，绝不用人为放大压力或
  直接改写车轮角的方式强行 PASS。
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
from steering_sim.j0_coupling.mechanism import (AS_BUILT_REFERENCE,  # noqa: E402
                                                REDESIGNED_ACKERMANN,
                                                build_mechanism_model)
from steering_sim.j0_coupling.reporting import (configure_chinese_font,  # noqa: E402
                                                write_samples_csv)
from steering_sim.j0_coupling.runner import J0Runner  # noqa: E402

WHEELS = tuple(f"axle{a}_{s}" for a in range(1, 7) for s in ("left", "right"))
REAR = (4, 5, 6)
TARGETS = (0.0, 2.0, -2.0, 5.0, -5.0, 10.0, -10.0, 20.0, -20.0, 30.0, -30.0)
DEFAULT_SPEED_KMH = 5.0


def classify_failure(summary: dict) -> str:
    """把没达成的工况归因到明确的一类，不允许含糊其辞。"""
    if not summary.get("completed", False):
        return f"数值求解失败：{summary.get('failure_reason')}"
    notes = " ".join(str(item) for item in summary.get("status_notes", []))
    if "不可达" in notes or "方向相反" in notes:
        return "作动行程不足或方向相反（控制命令不可达）"
    if "供油容量告警" in notes:
        return "供油不足（泵供量不足，阀门未饱和但流量受限）"
    if summary.get("control_saturation_fraction", 0.0) > 0.5:
        return "控制饱和（阀门命令长期在上限，控制权限不足）"
    if summary.get("max_adhesion_utilization", 0.0) > 1.0:
        return "地面附着不足（a_y > μg）"
    if summary.get("max_steady_wheel_angle_error_vs_mechanism_deg", 0.0) > 0.25:
        return "跟踪误差超差（传动比与液压力矩匹配不足或液压能力不足）"
    return ""


def run_one(runner: J0Runner, target: float, speed: float, duration: float,
            out_dir: Path, mode: str):
    case = J0CaseConfig(id=f"M3-{mode[:2]}-{target:+.0f}", target_outer_angle_deg=target,
                        speed_kmh=speed, duration_s=duration)
    target_info = runner.target(case)
    started = time.perf_counter()
    result = runner.run_case(case)
    wall = time.perf_counter() - started
    summary = dict(result.summary)
    samples = result.samples

    record: dict = {
        "case": case.id, "target_deg": target, "speed_kmh": speed,
        "duration_s": duration, "mechanical_mode": mode,
        "completed": bool(result.completed),
        "failure_reason": result.failure_reason,
        "status": summary.get("status"),
        "status_notes": summary.get("status_notes", []),
        "wall_s": round(wall, 3),
    }
    if samples:
        tail = slice(max(0, int(len(samples["time_s"]) * 0.8)), len(samples["time_s"]))
        record["wheel_actual_deg"] = {
            wheel: round(float(np.asarray(samples[f"wheel_{wheel}_actual_deg"])[-1]), 4)
            for wheel in WHEELS}
        record["wheel_ideal_deg"] = {
            wheel: round(float(summary["target_wheel_angle_deg"][wheel]), 4)
            for wheel in WHEELS}
        record["wheel_mechanism_deg"] = {
            wheel: round(float(summary["target_mechanism_wheel_angle_deg"][wheel]), 4)
            for wheel in WHEELS}
        record["tracking_error_vs_mechanism_deg"] = {
            wheel: round(float(np.max(np.abs(
                np.asarray(samples[f"wheel_{wheel}_actual_deg"])[tail]
                - np.asarray(samples[f"wheel_{wheel}_target_mechanism_deg"])[tail]))), 4)
            for wheel in WHEELS}
        record["max_tracking_error_vs_mechanism_deg"] = round(
            float(summary.get("max_steady_wheel_angle_error_vs_mechanism_deg", math.nan)), 4)
        record["stroke_final_mm"] = {
            tag: round(float(np.asarray(samples[f"{tag}_x_m"])[-1]) * 1000.0, 4)
            for tag in ("channel_front", "channel_rear_1", "channel_rear_2",
                        "channel_rear_3")}
        record["stroke_target_mm"] = {
            tag: round(float(summary["target_x_ref_m"][tag]) * 1000.0, 4)
            for tag in ("channel_front", "channel_rear_1", "channel_rear_2",
                        "channel_rear_3")}
        record["max_pressure_mpa_g"] = round(float(summary.get("max_pressure_mpa_g", math.nan)), 3)
        record["control_saturation_fraction"] = round(
            float(summary.get("control_saturation_fraction", math.nan)), 4)
        record["pump_capacity_warnings"] = int(summary.get("pump_capacity_warnings", 0))
        record["third_axle_max_abs_deg"] = float(summary.get("third_axle_max_abs_deg", math.nan))
        record["max_link_residual_m"] = float(summary.get("max_link_residual_m", math.nan))
        record["virtual_work_residual_max_abs"] = float(
            summary.get("virtual_work_residual_max_abs", math.nan))
        record["max_adhesion_utilization"] = float(
            summary.get("max_adhesion_utilization", math.nan))
        # 液压缸作动力检查（任务书第八节）：F_cyl·ds = M_steer·dδ。
        # 直接读被控对象自己算出来的两个力，不另立一套换算。
        force: dict[str, float] = {}
        for tag in ("channel_front", "channel_rear_1", "channel_rear_2",
                    "channel_rear_3"):
            hydraulic = np.asarray(samples[f"{tag}_hydraulic_force_n"])[tail]
            load = np.asarray(samples[f"{tag}_load_force_n"])[tail]
            margin = np.abs(hydraulic) - np.abs(load)
            force[tag] = round(float(np.min(margin)), 1)
        record["force_margin_n"] = force
        record["min_force_margin_n"] = min(force.values())
        record["force_sufficient"] = bool(record["min_force_margin_n"] >= 0.0)
        record["non_finite"] = bool(any(
            not np.all(np.isfinite(np.asarray(values, dtype=float)))
            for values in samples.values()))
        # 方向检查（只针对非零目标角）
        direction_ok = True
        if abs(target) > 1.0e-9:
            sign = math.copysign(1.0, target)
            for axle in REAR:
                for side in ("left", "right"):
                    value = record["wheel_actual_deg"][f"axle{axle}_{side}"]
                    if abs(value) > 0.05 and math.copysign(1.0, value) != -sign:
                        direction_ok = False
        record["wheel_direction_ok"] = direction_ok
        record["left_right_same_sign"] = all(
            math.copysign(1.0, record["wheel_actual_deg"][f"axle{axle}_left"])
            == math.copysign(1.0, record["wheel_actual_deg"][f"axle{axle}_right"])
            for axle in REAR
            if abs(record["wheel_actual_deg"][f"axle{axle}_left"]) > 0.05)
        write_samples_csv(result, out_dir / f"{case.id}_timeseries.csv")
    record["failure_class"] = classify_failure(summary)
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default=REDESIGNED_ACKERMANN,
                        choices=[REDESIGNED_ACKERMANN, AS_BUILT_REFERENCE])
    parser.add_argument("--speed", type=float, default=DEFAULT_SPEED_KMH)
    parser.add_argument("--duration", type=float, default=2.0)
    parser.add_argument("--targets", default=",".join(str(v) for v in TARGETS))
    parser.add_argument("--out", default=str(ROOT / "outputs" / "m3" / "dynamic"))
    parser.add_argument("--label", default="representative")
    args = parser.parse_args()

    configure_chinese_font()
    config = load_j0_config(ROOT / "configs" / "j0" / "j0_config.json")
    model = build_mechanism_model(
        args.mode, ROOT / "mechanical_model_input_spec_v1.0.yaml",
        ROOT / "mechanics_ackermann_v2" / "config.json",
        ROOT / "mechanics_ackermann_redesigned" / "config.json")
    runner = J0Runner(config, model, probe_authority=False, mechanical_mode=args.mode)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    records = []
    for value in [float(item) for item in args.targets.split(",") if item.strip()]:
        record = run_one(runner, value, args.speed, args.duration, out_dir, args.mode)
        records.append(record)
        print(f"{record['case']:>14s} status={record['status']:<12s} "
              f"maxerr={record.get('max_tracking_error_vs_mechanism_deg')} "
              f"dir_ok={record.get('wheel_direction_ok')} "
              f"cls={record['failure_class']}")

    payload = {"mechanical_mode": args.mode, "speed_kmh": args.speed,
               "duration_s": args.duration, "records": records}
    path = out_dir / f"m3_dynamic_{args.label}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    completed = sum(1 for item in records if item["completed"])
    print(f"\n完成 {completed}/{len(records)}；结果写入 {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
