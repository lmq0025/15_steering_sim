"""PHASE J1 第一关：61 个目标角的机械模型全范围校核（不接液压）。

输出 ``outputs/j1/gate1_angle_table.csv`` —— 每个目标角一行，含：
理想阿克曼角、工程机构理论角、四组目标行程、传动比与行程雅可比、
方向 / 同桥同向 / 左右镜像 / 三桥锁零 / 连续性 / 一桥外轮跟随 / 阿克罗曼偏差。
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from steering_sim.engineering.model import EngineeringSteeringModel  # noqa: E402
from steering_sim.engineering.mechanism import WHEEL_ORDER  # noqa: E402

SPEC = ROOT / "mechanical_model_input_spec_v1.0.yaml"
CONFIG = ROOT / "configs" / "j1" / "engineering_config.json"
DESIGN = ROOT / "configs" / "j1" / "engineering_mechanism.json"
ANGLES = tuple(float(v) for v in range(-30, 31))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "outputs" / "j1"))
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    model = EngineeringSteeringModel(SPEC, CONFIG, DESIGN)
    rows: list[dict] = []
    previous: dict[str, float] | None = None
    max_jump = 0.0
    problems: list[str] = []

    for angle in ANGLES:
        geometry = model.solve_geometry(angle)
        state = model.mechanism_state(geometry.q_rad)
        mech = state.wheel_angles_deg
        ideal = geometry.ideal_ackermann_angle_deg
        row: dict = {"目标角_deg": angle, "几何状态": geometry.geometry_class}
        for wheel in WHEEL_ORDER:
            row[f"理想_{wheel}"] = round(float(ideal[wheel]), 4)
            row[f"机构_{wheel}"] = round(float(mech[wheel]), 4)
            row[f"偏差_{wheel}"] = round(float(mech[wheel] - ideal[wheel]), 4)
        for dof, value in geometry.q_rad.items():
            row[f"{dof}_rad"] = round(float(value), 6)
        for name, value in state.representative_stroke_m.items():
            row[f"目标行程_{name}_mm"] = round(float(value) * 1000.0, 4)
        for name, value in state.cylinder_stroke_m.items():
            row[f"缸行程_{name}_mm"] = round(float(value) * 1000.0, 4)
        # 方向 / 同向 / 锁零 / 镜像
        sign = math.copysign(1.0, angle) if abs(angle) > 1e-12 else 0.0
        direction_ok = True
        same_sign_ok = True
        for axle in range(1, 7):
            left, right = mech[f"axle{axle}_left"], mech[f"axle{axle}_right"]
            if axle == 3:
                if abs(left) > 1e-9 or abs(right) > 1e-9:
                    direction_ok = False
                continue
            want = sign if axle in (1, 2) else -sign
            for value in (left, right):
                if abs(value) > 0.02 and sign and math.copysign(1.0, value) != want:
                    direction_ok = False
            if abs(left) > 1e-6 and abs(right) > 1e-6 and \
                    math.copysign(1.0, left) != math.copysign(1.0, right):
                same_sign_ok = False
        row["方向正确"] = direction_ok
        row["同桥同向"] = same_sign_ok
        row["三桥锁零"] = abs(mech["axle3_left"]) < 1e-9 and abs(mech["axle3_right"]) < 1e-9
        # 一桥外轮跟随
        outer = geometry.outer_wheel
        row["一桥外轮"] = outer
        row["一桥外轮跟随误差_deg"] = (None if outer is None else
                                       round(float(mech[outer] - angle), 4))
        # 阿克曼 RMS（四、五、六桥）
        values = [mech[f"axle{a}_{s}"] - ideal[f"axle{a}_{s}"]
                  for a in (4, 5, 6) for s in ("left", "right")]
        row["后三桥阿克曼RMS_deg"] = round(math.sqrt(sum(v * v for v in values) / len(values)), 4)
        # 连续性
        if previous is not None:
            jump = max(abs(mech[w] - previous[w]) for w in WHEEL_ORDER)
            row["相对上一档最大跳变_deg"] = round(jump, 4)
            max_jump = max(max_jump, jump)
        else:
            row["相对上一档最大跳变_deg"] = 0.0
        previous = dict(mech)
        rows.append(row)
        if not direction_ok:
            problems.append(f"{angle:+.0f}°: 车轮方向错误")
        if not same_sign_ok:
            problems.append(f"{angle:+.0f}°: 同桥左右轮反号")
        if outer is not None and abs(mech[outer] - angle) > 0.05:
            problems.append(f"{angle:+.0f}°: 一桥外轮未跟随（{mech[outer]:.3f}°）")

    # 镜像校核（δ(轮, −t) = −δ(左右互换的轮, +t)）
    mirror_bad = []
    by_angle = {int(row["目标角_deg"]): row for row in rows}
    flip = {w: w.replace("_left", "_TMP").replace("_right", "_left").replace("_TMP", "_right")
            for w in WHEEL_ORDER}
    for angle in range(1, 31):
        plus = by_angle[angle]
        minus = by_angle[-angle]
        for wheel in WHEEL_ORDER:
            total = minus[f"机构_{wheel}"] + plus[f"机构_{flip[wheel]}"]
            if abs(total) > 0.08:
                mirror_bad.append((angle, wheel, total))
                break
    # 行程单调性
    stroke_monotone = {}
    for dof in ("q_front", "q4", "q5", "q6"):
        values = [row[f"{dof}_rad"] for row in rows]
        step = np.diff(values)
        stroke_monotone[dof] = bool(np.all(step >= -1e-9) or np.all(step <= 1e-9))

    path = out / "gate1_angle_table.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    summary = {
        "angles": len(rows),
        "direction_ok": sum(1 for r in rows if r["方向正确"]),
        "same_sign_ok": sum(1 for r in rows if r["同桥同向"]),
        "third_axle_locked": sum(1 for r in rows if r["三桥锁零"]),
        "mirror_ok": len(range(1, 31)) - len(mirror_bad),
        "max_step_jump_deg": round(max_jump, 4),
        "max_ackermann_rms_deg": round(max(r["后三桥阿克曼RMS_deg"] for r in rows), 4),
        "max_outer_follow_error_deg": round(max(
            abs(r["一桥外轮跟随误差_deg"] or 0.0) for r in rows), 4),
        "q_monotone": stroke_monotone,
        "max_wheel_angle_deg": round(max(abs(r[f"机构_{w}"]) for r in rows
                                         for w in WHEEL_ORDER), 3),
        "problems": problems[:20],
        "mirror_problems": mirror_bad[:10],
    }
    (out / "gate1_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("written:", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
