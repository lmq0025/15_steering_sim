"""中文机械 baseline 人工试车入口；所有机械计算复用 R02-E/R02-D。"""
from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, is_dataclass
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import sys
from collections.abc import Mapping

if __package__:
    from .run_vehicle_steering_demo import (
        ROOT, IO_BASELINE, COORDINATION_BASELINE, build_coordinator, plot_vehicle_demo,
    )
else:
    from run_vehicle_steering_demo import (
        ROOT, IO_BASELINE, COORDINATION_BASELINE, build_coordinator, plot_vehicle_demo,
    )
from steering_sim.mechanics import SteeringMode, KinematicsError

DISPLAY_LEFT_TURN_SIGN = +1
BASELINE_VERSION = "MECHANICAL BASELINE v0.1"
DISCLAIMER = "NOT CUSTOMER CALIBRATED"
DISPLAY_CONVENTION = (
    "当前显示约定：左转 = +Y / 正转角；若客户数据采用相反符号，"
    "后续只改显示/数据映射，不改机械几何。"
)
MODE_MAP = {
    "customer-hint": ("customer-hint", SteeringMode.LOW_SPEED_COUNTER_PHASE),
    "public": ("public", SteeringMode.LOW_SPEED_COUNTER_PHASE),
    "crab": ("customer-hint", SteeringMode.CRAB),
    "front-only": ("customer-hint", SteeringMode.FRONT_GROUP_ONLY),
}
STATUS = {
    "matched_within_display_tolerance": "OK（显示容差内）",
    "baseline_mismatch": "baseline_mismatch（基准目标不匹配）",
    "geometry_limited": "geometry_limited（数值区间边界受限）",
}


def signed_command(angle: float, direction: str) -> float:
    if not math.isfinite(angle) or angle < 0:
        raise ValueError("目标角必须是有限的非负绝对值。")
    if direction not in ("left", "right"):
        raise ValueError("方向必须为 left 或 right。")
    return DISPLAY_LEFT_TURN_SIGN * angle * (1 if direction == "left" else -1)


def run_case(preset="customer-hint", angle=1.5, direction="left", coordinator=None):
    coordinator = coordinator or build_coordinator()
    model_preset, mode = MODE_MAP[preset]
    result = coordinator.coordinate(signed_command(angle, direction), model_preset, mode)
    return coordinator, result


def actuator_positions(result):
    positions = {"front_mapped_position_mm": result.actuator_input.front_position * 1000}
    for axle in range(3, 7):
        for side in ("A", "B"):
            positions[f"axle{axle}_{side}_stroke_mm"] = (
                getattr(result.actuator_input, f"axle{axle}_{side}").value_m * 1000
            )
    return positions


def infeasible_message(result):
    if result.feasible:
        return ""
    equivalent = result.target_axle1_mean_angle_deg * result.largest_feasible_scale
    return (
        f"当前 {result.target_axle1_mean_angle_deg:+.3f} deg 请求超过已验证 "
        "numerical interval 内可实现范围；这不是客户机械极限。"
        f"建议可展示目标为 {equivalent:+.3f} deg。"
        "该建议仍可能存在 baseline mismatch，请查看逐桥残差。"
    )


def print_result(result, direction):
    print("\n【输入】")
    print(f"模式：{result.preset} / {result.mode.value}")
    print(f"方向：{'左' if direction == 'left' else '右'}")
    print(f"第一桥目标平均角：{result.target_axle1_mean_angle_deg:+.3f} deg")
    print(f"说明：BASELINE ONLY / {DISCLAIMER}")
    print(DISPLAY_CONVENTION)
    print("\n【六桥实际平均转角】")
    print("桥号  理想平均角[deg]  实际平均角[deg]  相位（相对一桥）  状态")
    front = result.axles[1].actual_mean_rad
    for axle, item in result.axles.items():
        phase = "零位" if abs(item.actual_mean_rad) < 1e-10 else (
            "同向" if item.actual_mean_rad * front > 0 else "反向"
        )
        print(f"{axle}     {math.degrees(item.ideal_mean_rad):+10.6f}       "
              f"{math.degrees(item.actual_mean_rad):+10.6f}       {phase}  {STATUS[item.status]}")
    print("\n【12个车轮实际转角】")
    for name, value in result.mechanical_output.wheel_angles_rad.items():
        print(f"{name}: {math.degrees(value):+.6f} deg")
    print("\n【机械模型所需执行器位置】")
    for name, value in actuator_positions(result).items():
        label = "前桥组映射位置" if name.startswith("front") else name.replace("_stroke_mm", " 行程")
        print(f"{label}: {value:+.6f} mm")
    print("共9个位置量；二桥通过前桥组机械联动，无独立执行器输入。")
    print("\n【诊断】")
    print(f"数值可行 feasible = {result.feasible}")
    print("可行标志仅反映已验证数值区间；实际轮角与理想目标仍可能有明显偏差。")
    if not result.feasible:
        print(f"最大可行比例 largest_feasible_scale = {result.largest_feasible_scale:.8f}")
        print(infeasible_message(result))
    print(f"瞬时转动中心 ICR = ({result.x_icr_m}, {result.y_icr_m}) m（空值表示无有限ICR）")
    print(f"最大目标偏差 = {max(a.ackermann_error_deg for a in result.axles.values()):.6f} deg")
    for axle in (5, 6):
        a = result.axles[axle]
        print(f"第{axle}桥：{STATUS[a.status]}；q={a.q_rad:+.8f} rad；"
              f"残差={math.degrees(a.geometry_residual_rad):.6f} deg RMS；"
              f"分支={a.monotonic_branch_used}；连续={a.branch_continuity}")


def _plain(value):
    if is_dataclass(value):
        return _plain(asdict(value))
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if hasattr(value, "item"):
        return value.item()
    return value


def make_payload(result, coordinator, preset, angle, direction):
    configs = {}
    for name, path in (("mechanical_io", IO_BASELINE), ("coordination", COORDINATION_BASELINE)):
        raw = path.read_bytes()
        configs[name] = {
            "path": str(path.relative_to(ROOT)),
            "schema_version": json.loads(raw)["schema_version"],
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    return _plain({
        "schema_version": "1.0",
        "baseline_version": BASELINE_VERSION,
        "disclaimer": DISCLAIMER,
        "created_at": datetime.now().astimezone().isoformat(),
        "user_input": {"preset": preset, "angle_abs_deg": angle, "direction": direction},
        "signed_command_deg": result.target_axle1_mean_angle_deg,
        "display_convention": DISPLAY_CONVENTION,
        "preset": result.preset, "mode": result.mode.value,
        "ideal_wheel_angles_deg": {k: math.degrees(v) for k, v in result.ideal_wheel_angles_rad.items()},
        "ideal_axle_mean_angles_deg": {k: math.degrees(v.ideal_mean_rad) for k, v in result.axles.items()},
        "actual_wheel_angles_deg": {k: math.degrees(v) for k, v in result.mechanical_output.wheel_angles_rad.items()},
        "actual_axle_mean_angles_deg": {k: math.degrees(v.actual_mean_rad) for k, v in result.axles.items()},
        "actuator_positions_mm": actuator_positions(result),
        "actuator_definition": "front: R02-D mapped position; rear: calibrated stroke_from_reference_m converted to mm",
        "q_rad": dict(result.mechanical_output.generalized_coordinates),
        "q_target_rad": dict(result.q_target_rad),
        "icr_m": {"x": result.x_icr_m, "y": result.y_icr_m},
        "feasible": result.feasible,
        "largest_feasible_scale": result.largest_feasible_scale,
        "diagnostics": {
            "axles": {k: asdict(v) for k, v in result.axles.items()},
            "mechanical_io": dict(result.mechanical_output.diagnostics),
            "actuator_residuals_m": dict(result.mechanical_output.actuator_residuals),
            "constraint_residuals_m": dict(result.mechanical_output.constraint_residuals),
            "valid": result.mechanical_output.valid,
            "singular": result.mechanical_output.singular,
            "out_of_range": result.mechanical_output.out_of_range,
            "coordinator": dict(result.diagnostics),
            "infeasible_message": infeasible_message(result),
        },
        "configs": configs,
        "geometry_sha256": coordinator.reference.source_sha256,
    })


def save_results(payload, json_path, csv_path):
    json_path, csv_path = Path(json_path), Path(csv_path)
    if json_path.resolve() == csv_path.resolve():
        raise ValueError("JSON 与 CSV 必须使用不同路径。")
    for path in (json_path, csv_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    rows = []
    for axle in range(1, 7):
        key = str(axle)
        d = payload["diagnostics"]["axles"][key]
        rows.append({
            "axle": axle, "preset": payload["preset"], "mode": payload["mode"],
            "signed_command_deg": payload["signed_command_deg"],
            "ideal_mean_deg": payload["ideal_axle_mean_angles_deg"][key],
            "actual_mean_deg": payload["actual_axle_mean_angles_deg"][key],
            "POS_Y_actual_deg": payload["actual_wheel_angles_deg"][f"axle{axle}_POS_Y"],
            "NEG_Y_actual_deg": payload["actual_wheel_angles_deg"][f"axle{axle}_NEG_Y"],
            "front_mapped_position_mm": payload["actuator_positions_mm"]["front_mapped_position_mm"] if axle == 1 else None,
            "actuator_A_stroke_mm": payload["actuator_positions_mm"].get(f"axle{axle}_A_stroke_mm"),
            "actuator_B_stroke_mm": payload["actuator_positions_mm"].get(f"axle{axle}_B_stroke_mm"),
            "q_rad": d["q_rad"], "status": d["status"],
            "ackermann_error_deg": d["ackermann_error_deg"],
            "feasible": payload["feasible"], "largest_feasible_scale": payload["largest_feasible_scale"],
            "baseline_version": BASELINE_VERSION,
        })
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def prompt_inputs():
    print("请选择转向模式：")
    print("1. customer-hint （一二桥与三～六桥反相，当前推荐演示）")
    print("2. public        （一二三桥与四～六桥反相）")
    print("3. crab          （同相/蟹行 baseline）")
    print("4. front-only    （仅前桥组）")
    choices = dict(zip(("1", "2", "3", "4"), MODE_MAP))
    while True:
        choice = input("模式 [默认1]：").strip().lower() or "1"
        preset = choices.get(choice, choice)
        if preset in MODE_MAP:
            break
        print("请输入1～4或对应模式名称。")
    while True:
        raw = input("请输入第一桥目标平均转角绝对值 [deg，默认1.5]：").strip() or "1.5"
        try:
            angle = float(raw.removesuffix("°").strip())
            signed_command(angle, "left")
            break
        except ValueError:
            print("请输入有限的非负数，例如1.5。")
    while True:
        raw = input("请输入方向 [左/右，默认左]：").strip().lower() or "左"
        direction = {"左": "left", "右": "right", "left": "left", "right": "right"}.get(raw)
        if direction:
            return preset, angle, direction
        print("请输入左或右。")


def main(argv=None):
    # Windows redirected output can otherwise inherit a legacy code page.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    print(f"{BASELINE_VERSION}\n{DISCLAIMER}\n机械基准人工试车入口")
    parser = argparse.ArgumentParser(description="中文机械 baseline 人工试车")
    parser.add_argument("--preset", choices=tuple(MODE_MAP), default="customer-hint", help="演示模式")
    parser.add_argument("--axle1-deg", type=float, default=1.5, help="第一桥目标角绝对值[deg]")
    parser.add_argument("--direction", choices=("left", "right"), default="left", help="左/右转")
    parser.add_argument("--save-json", type=Path, help="JSON保存路径")
    parser.add_argument("--save-csv", type=Path, help="CSV保存路径")
    parser.add_argument("--plot", action="store_true", help="保存本次案例图")
    parser.add_argument("--demo", action="store_true", help="推荐：customer-hint、1.5度、左转、绘图")
    arguments = sys.argv[1:] if argv is None else argv
    args = parser.parse_args(arguments)
    try:
        if not arguments:
            args.preset, args.axle1_deg, args.direction = prompt_inputs()
        if args.demo:
            args.preset, args.axle1_deg, args.direction, args.plot = "customer-hint", 1.5, "left", True
        signed_command(args.axle1_deg, args.direction)
        coordinator, result = run_case(args.preset, args.axle1_deg, args.direction)
        print_result(result, args.direction)
        payload = make_payload(result, coordinator, args.preset, args.axle1_deg, args.direction)
        stem = ROOT / "outputs/manual_demo" / datetime.now().strftime("mechanical_demo_%Y%m%d_%H%M%S")
        # Keep same-second repeated runs rather than silently replacing their default artifacts.
        counter = 1
        original = stem
        while any(stem.with_suffix(s).exists() for s in (".json", ".csv", ".png")):
            stem = original.with_name(f"{original.name}_{counter:02d}")
            counter += 1
        json_path = args.save_json or stem.with_suffix(".json")
        csv_path = args.save_csv or stem.with_suffix(".csv")
        save_results(payload, json_path, csv_path)
        print(f"\n已保存 JSON：{json_path}\n已保存 CSV：{csv_path}")
        if args.plot:
            plot_path = stem.with_suffix(".png")
            plot_path.parent.mkdir(parents=True, exist_ok=True)
            plot_vehicle_demo(result, coordinator, plot_path, title=f"{BASELINE_VERSION}\n{DISCLAIMER}")
            print(f"已保存案例图：{plot_path}")
        return 0
    except (ValueError, KinematicsError, OSError) as exc:
        print(f"本次试车未完成：{exc}\n请检查输入或文件路径；不会扩展已验证数值区间。", file=sys.stderr)
        return 2
    except (EOFError, KeyboardInterrupt):
        print("\n已取消本次试车。")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
