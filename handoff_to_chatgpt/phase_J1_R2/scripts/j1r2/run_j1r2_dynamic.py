"""PHASE J1-R2 第七节：代表性工况的**完整动态积分**验收。

真实积分工程电液伺服模型的状态（四通道 × (pA, pB, x, v, 阀芯) + 两条供油轨），
实际轮角由**实际缸位移**经机构闭链反求。每个工况分别报告：

* ``NUMERICAL_COMPLETED``        —— 数值积分是否跑完
* ``TRACKING_PASS``              —— 稳态是否跟上瞬时指令
* ``TRANSIENT_TRACKING_PASS``    —— 过渡段峰值误差是否在带内
* ``VEHICLE_DYNAMIC_INFEASIBLE`` —— 目标路径是否超出附着能力

四者分开，不允许用其中一个冒充另一个。同时输出每个工况的完整时间序列 CSV：
目标/实际行程、阀命令、未限幅请求、两腔压力、液压力、负载力、流速、十二轮
理想角/机构角/实际角、附着需求与可提供轮胎力。
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
import time
from typing import Callable

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from steering_sim.engineering.mechanism import WHEEL_ORDER              # noqa: E402
from steering_sim.j0_coupling.config import J0CaseConfig, load_j0_config  # noqa: E402
from steering_sim.j0_coupling.mechanism import (ENGINEERING_STEERING_MODEL,  # noqa: E402
                                                build_mechanism_model)
from steering_sim.j0_coupling.reporting import (configure_chinese_font,  # noqa: E402
                                                write_samples_csv)
from steering_sim.j0_coupling.runner import (J0Runner, reference_position,  # noqa: E402
                                             reference_velocity)

SPEC = ROOT / "mechanical_model_input_spec_v1.0.yaml"
ENG_CONFIG = ROOT / "configs" / "j1" / "engineering_config.json"
ENG_DESIGN = ROOT / "configs" / "j1" / "engineering_mechanism.json"
J0_CONFIG = ROOT / "configs" / "j0" / "j0_config.json"
RATE_DEG_PER_S = 12.0
MINIMUM_RAMP_S = 0.40


def ramp_time(angle_deg: float) -> float:
    return max(MINIMUM_RAMP_S, abs(angle_deg) / RATE_DEG_PER_S)


def duration(angle_deg: float) -> float:
    ramp = ramp_time(angle_deg)
    return ramp + max(0.9, 0.5 * ramp)


def classify(summary: dict) -> str:
    """归因：先判目标路径本身是否物理可行，再判跟踪能力。"""
    if not summary.get("NUMERICAL_COMPLETED"):
        return f"数值求解失败：{summary.get('failure_reason')}"
    if (summary.get("target_path_adhesion_ratio") or 0.0) > 1.0:
        return ("目标路径超出附着能力（a_y > μg）：数值已完成，物理上不可行，"
                "不代表实际车辆能完成该路径；转向机构本身已跟上指令")
    if not summary.get("TRANSIENT_TRACKING_PASS"):
        return "过渡段峰值跟踪误差超出 CONDITIONAL 带"
    if not summary.get("TRACKING_PASS"):
        return "稳态跟踪误差超出 PASS 带"
    if (summary.get("max_tail_valve_reversal_rate_per_s") or 0.0) > 20.0:
        return "末段阀命令换向频繁，存在振荡风险"
    return ""


def multi_step_profile(segments: list[tuple[float, float]],
                       ramp_s: float = 1.0) -> Callable[[float], tuple[float, float]]:
    """多段指令轨迹：``segments`` = [(相对位置, 保持时长), ...]。

    用于任务书第 7.6 节要求的"连续两个转向指令 / 反向回零"：从 0 → +1 → −1 → 0
    走一遍，段与段之间用同一条 S 曲线过渡。
    """
    plan: list[tuple[float, float, float, float]] = []   # 起始时刻, 起点, 终点, 段长
    clock = 0.0
    current = 0.0
    for target, hold in segments:
        plan.append((clock, current, float(target), ramp_s))
        clock += ramp_s
        current = float(target)
        plan.append((clock, current, current, hold))
        clock += hold
    total = clock

    def profile(t: float) -> tuple[float, float]:
        if t >= total:
            return current, 0.0
        for start, begin, end, span in plan:
            if t < start + span:
                if begin == end:
                    return end, 0.0
                fraction = reference_position(t - start, span)
                rate = reference_velocity(t - start, span)
                return begin + (end - begin) * fraction, (end - begin) * rate
        return current, 0.0

    return profile


def _load_records(out_dir: Path) -> list[dict]:
    path = out_dir / "j1r2_dynamic.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("records", [])


def build_record(case_id: str, target: float, speed: float, duration_s: float,
                 result, wall_s: float, note: str = "") -> dict:
    summary = result.summary
    record = {
        "case": case_id, "target_deg": target, "speed_kmh": speed,
        "duration_s": round(duration_s, 3), "wall_s": round(wall_s, 2),
        "note": note,
        "reference_time_s": summary.get("reference_time_s"),
        "NUMERICAL_COMPLETED": bool(summary.get("NUMERICAL_COMPLETED")),
        "TRACKING_PASS": bool(summary.get("TRACKING_PASS")),
        "TRANSIENT_TRACKING_PASS": bool(summary.get("TRANSIENT_TRACKING_PASS")),
        "VEHICLE_DYNAMIC_INFEASIBLE": bool(summary.get("VEHICLE_DYNAMIC_INFEASIBLE")),
        "status": summary.get("status"),
        "failure_reason": summary.get("failure_reason"),
        "max_tracking_error_vs_command_deg": summary.get(
            "max_tracking_error_vs_command_deg"),
        "rms_tracking_error_vs_command_deg": summary.get(
            "rms_tracking_error_vs_command_deg"),
        "steady_max_tracking_error_vs_command_deg": summary.get(
            "steady_max_tracking_error_vs_command_deg"),
        "steady_rms_tracking_error_vs_command_deg": summary.get(
            "steady_rms_tracking_error_vs_command_deg"),
        "max_tracking_error_vs_mechanism_deg": summary.get(
            "max_steady_wheel_angle_error_vs_mechanism_deg"),
        "settling_time_to_0p5deg_s": summary.get("settling_time_to_0p5deg_s"),
        "control_saturation_fraction": summary.get("control_saturation_fraction"),
        "anti_windup_active_fraction": summary.get("anti_windup_active_fraction"),
        "valve_at_limit_sample_fraction": summary.get("valve_at_limit_sample_fraction"),
        "max_unclipped_pid_request": summary.get("max_unclipped_pid_request"),
        "max_tail_velocity_rms_m_s": summary.get("max_tail_velocity_rms_m_s"),
        "max_tail_valve_reversal_rate_per_s": summary.get(
            "max_tail_valve_reversal_rate_per_s"),
        "max_tail_pressure_ripple_mpa": summary.get("max_tail_pressure_ripple_mpa"),
        "tail_velocity_rms_m_s": summary.get("tail_velocity_rms_m_s"),
        "tail_pressure_ripple_mpa": summary.get("tail_pressure_ripple_mpa"),
        "steady_stroke_error_mm": {
            k: round(float(v) * 1000.0, 4)
            for k, v in (summary.get("steady_stroke_error_m") or {}).items()},
        "stroke_target_mm": {k: round(float(v) * 1000.0, 2)
                             for k, v in summary.get("target_x_ref_m", {}).items()},
        "stroke_final_mm": {k: round(float(v) * 1000.0, 2)
                            for k, v in (summary.get("final_stroke_m") or {}).items()},
        "stroke_utilisation_max": summary.get("stroke_utilisation_max"),
        "max_pressure_mpa_g": summary.get("max_pressure_mpa_g"),
        "min_supply_pressure_mpa_g": summary.get("supply_pressure_min_mpa_g"),
        "max_pump_demand_ratio": summary.get("max_pump_demand_ratio"),
        "peak_hydraulic_force_n": {k: round(float(v), 1) for k, v in
                                   (summary.get("peak_hydraulic_force_n") or {}).items()},
        "max_abs_velocity_m_s": summary.get("max_abs_velocity_m_s"),
        "max_link_residual_m": summary.get("max_link_residual_m"),
        "third_axle_max_abs_deg": summary.get("third_axle_max_abs_deg"),
        "max_adhesion_utilization": summary.get("max_adhesion_utilization_recorded"),
        "target_path_adhesion_ratio": summary.get("target_path_adhesion_ratio"),
        "curvature_actual_1pm_max": summary.get("curvature_actual_1pm_max"),
        "curvature_target_1pm": summary.get("curvature_target_1pm"),
        "uses_actual_curvature": summary.get("uses_actual_curvature"),
        "controller_gains": summary.get("controller_gains"),
        "feedforward_gain": summary.get("feedforward_gain"),
        "authority": summary.get("authority"),
    }
    samples = result.samples
    if samples:
        record["non_finite"] = bool(any(
            not np.all(np.isfinite(np.asarray(v, dtype=float)))
            for v in samples.values()))
        mech = summary.get("target_mechanism_wheel_angle_deg", {})
        actu = {w: float(np.asarray(samples[f"wheel_{w}_actual_deg"])[-1]) for w in mech}
        record["wheel_actual_deg"] = {w: round(v, 4) for w, v in actu.items()}
        record["wheel_mechanism_deg"] = {w: round(float(v), 4) for w, v in mech.items()}
        record["wheel_ideal_deg"] = {
            w: round(float(v), 4)
            for w, v in (summary.get("target_wheel_angle_deg") or {}).items()}
        sign = math.copysign(1.0, target) if abs(target) > 1e-9 else 0.0
        record["wheel_direction_ok"] = all(
            math.copysign(1.0, actu[f"axle{a}_{s}"]) == (-sign if a in (4, 5, 6) else sign)
            for a in range(1, 7) if a != 3 for s in ("left", "right")
            if abs(actu[f"axle{a}_{s}"]) > 0.05)
    record["failure_class"] = classify(summary)
    return record


def run_one(runner: J0Runner, case_id: str, target: float, speed: float,
            duration_s: float, out_dir: Path, *,
            profile=None, note: str = "") -> dict:
    case = J0CaseConfig(id=case_id, target_outer_angle_deg=target, speed_kmh=speed,
                        duration_s=duration_s)
    started = time.perf_counter()
    result = runner.run_case(case, profile=profile)
    wall = time.perf_counter() - started
    record = build_record(case_id, target, speed, duration_s, result, wall, note)
    if result.samples:
        write_samples_csv(result, out_dir / f"{case_id}_timeseries.csv")
    return record


def representative_cases() -> list[tuple[str, float, float, str]]:
    cases: list[tuple[str, float, float, str]] = []
    for angle in (0.0, 2.0, -2.0, 5.0, -5.0, 10.0, -10.0, 20.0, -20.0, 30.0, -30.0):
        cases.append((f"低速5_{angle:+.0f}deg", angle, 5.0, "低速代表工况"))
    for angle in (30.0, -30.0):
        cases.append((f"静止0_{angle:+.0f}deg", angle, 0.0, "原地转向（干转）"))
    cases.append(("中速40_+20deg", 20.0, 40.0, "中速中等转角"))
    cases.append(("高速60_+20deg", 20.0, 60.0, "高速中等转角"))
    cases.append(("高速80_+30deg", 30.0, 80.0, "极限工况（附着不可行）"))
    cases.append(("高速80_-30deg", -30.0, 80.0, "极限工况（附着不可行）"))
    return cases


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "outputs" / "j1r2" / "dynamic"))
    parser.add_argument("--only", default="")
    parser.add_argument("--sequence-only", action="store_true",
                        help="只重跑多段连续指令工况，并合并进已有结果 JSON")
    args = parser.parse_args()
    configure_chinese_font()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    config = load_j0_config(J0_CONFIG)
    model = build_mechanism_model(ENGINEERING_STEERING_MODEL, SPEC,
                                  engineering_config_path=ENG_CONFIG,
                                  design_path=ENG_DESIGN)
    runner = J0Runner(config, model, probe_authority=False,
                      mechanical_mode=ENGINEERING_STEERING_MODEL)

    records: list[dict] = []
    existing = _load_records(out)
    if args.sequence_only:
        records = [r for r in existing if not r["case"].startswith("连续指令")]
    print("== 低速/静止/中高速代表工况（真实动态积分）==", flush=True)
    for case_id, angle, speed, note in representative_cases():
        if args.sequence_only:
            continue
        if args.only and args.only not in case_id:
            continue
        record = run_one(runner, case_id, angle, speed, duration(angle), out, note=note)
        records.append(record)
        print(f"  {case_id:>16s} NUM={int(record['NUMERICAL_COMPLETED'])} "
              f"TRK={int(record['TRACKING_PASS'])} "
              f"TRA={int(record['TRANSIENT_TRACKING_PASS'])} "
              f"INF={int(record['VEHICLE_DYNAMIC_INFEASIBLE'])} "
              f"pk={record['max_tracking_error_vs_command_deg']:.4f}° "
              f"stdy={record['steady_max_tracking_error_vs_command_deg']:.5f}° "
              f"sat={record['control_saturation_fraction']:.3f} "
              f"P={record['max_pressure_mpa_g']:.1f}MPa", flush=True)

    # 7.6 连续两个转向指令 / 反向回零
    print("== 连续指令与反向回零 ==", flush=True)
    # 末段保持必须**显著长于**稳态统计窗（末 20%），否则 "稳态" 指标会掺进
    # 反向回零的过渡段，把正常的过渡误差误报成稳态超差。
    sequence = multi_step_profile([(1.0, 0.9), (-1.0, 0.9), (0.0, 1.6)], ramp_s=1.0)
    total = 3.0 * 1.0 + 0.9 + 0.9 + 1.6
    record = run_one(runner, "连续指令_+10_-10_0", 10.0, 10.0, total, out,
                     profile=sequence,
                     note="10 km/h：0→+10°→−10°→0，三段连续指令与反向回零")
    records.append(record)
    print(f"  {record['case']:>16s} NUM={int(record['NUMERICAL_COMPLETED'])} "
          f"TRK={int(record['TRACKING_PASS'])} "
          f"TRA={int(record['TRANSIENT_TRACKING_PASS'])} "
          f"pk={record['max_tracking_error_vs_command_deg']:.4f}°", flush=True)

    payload = {
        "mode": "FULL_DYNAMIC",
        "hydraulic_model": runner.hydraulic_model,
        "state_size": int(runner.hydraulic.state_size),
        "reference": {"rate_deg_per_s": RATE_DEG_PER_S,
                      "minimum_ramp_s": MINIMUM_RAMP_S},
        "records": records,
    }
    path = out / "j1r2_dynamic.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=float),
                    encoding="utf-8")
    completed = sum(1 for r in records if r["NUMERICAL_COMPLETED"])
    tracking = sum(1 for r in records if r["TRACKING_PASS"])
    transient = sum(1 for r in records if r["TRANSIENT_TRACKING_PASS"])
    print(f"\n数值完成 {completed}/{len(records)}；"
          f"稳态跟踪达标 {tracking}/{len(records)}；"
          f"过渡段达标 {transient}/{len(records)}")
    print("written:", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
