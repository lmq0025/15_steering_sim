"""PHASE J1-R2：修正前组随动桥（二桥）的传动比。

**问题**（J1-R2 任务书第二节列出）：前组的一桥与二桥由中间拉杆 1:1 耦合，
于是二桥几乎跟着一桥转同样的角度。但二桥离三桥处的瞬时转向中心更近，理想
阿克曼角只有一桥的约 0.65 倍，实测偏差达 **13.56°**。

**解决办法**：把**二桥转向臂的有效半径**按实测标定放大 —— 同样的齿条行程
就给出更小的车轮转角。这对转向桥是标准做法（加长转向节臂即降低该桥传动比），
而且**不改动任何甲方坐标**：主销、轮心、液压缸机座点、杆长全都不动，只改
J1 已标为 `ENGINEERING_DESIGN_ASSUMPTION` 的转向臂端点。

标定方式：在 ±15°/±20°/±30° 上扫放大系数 k，取 axles 1–2 对理想阿克曼的
最大偏差最小者。**只改这一个数，不重新设计整套机构。**
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from steering_sim.engineering.mechanism import load_design, save_design  # noqa: E402
from steering_sim.mechanics import reference_geometry_from_file          # noqa: E402

SPEC = ROOT / "mechanical_model_input_spec_v1.0.yaml"
DESIGN = ROOT / "configs" / "j1" / "engineering_mechanism.json"
LEGACY_SIDE = {"left": "POS_Y", "right": "NEG_Y"}
#: 标定出的二桥转向臂有效半径放大系数（见模块说明的扫描过程）。
SCALE = 1.39


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--design", default=str(DESIGN))
    parser.add_argument("--scale", type=float, default=SCALE)
    parser.add_argument("--scan", action="store_true")
    args = parser.parse_args()

    path = Path(args.design)
    raw = json.loads(path.read_text(encoding="utf-8"))
    reference = reference_geometry_from_file(SPEC)
    group = raw["groups"]["front"]
    changed = []
    for name, side in group["sides"].items():
        if not name.startswith("axle2_"):
            continue
        which = name.split("_", 1)[1]
        pivot = np.asarray(
            reference.bodies[f"WHEEL_2_{LEGACY_SIDE[which]}"].pivot, dtype=float)
        tip = np.asarray(side["arm_tip"], dtype=float)
        arm = tip - pivot
        new_tip = pivot + float(args.scale) * arm
        changed.append((name, float(np.linalg.norm(arm)),
                        float(np.linalg.norm(new_tip - pivot))))
        side["arm_tip"] = [round(float(new_tip[0]), 6), round(float(new_tip[1]), 6)]
    if not changed:
        raise SystemExit("设计文件里没有 axle2_* 的转向臂端点")

    group["notes"] = list(group.get("notes", []))
    group["notes"].append(
        f"ENGINEERING_DESIGN_ASSUMPTION：二桥转向臂有效半径按实测标定放大 "
        f"{args.scale:.2f}×（"
        + "，".join(f"{n} {old:.4f}→{new:.4f} m" for n, old, new in changed)
        + "），把前组随动传动比降到与理想阿克伦曼匹配；甲方坐标未改。")
    raw.setdefault("provenance", {})["front_follower_retune"] = (
        f"scripts/j1r2/retune_front_follower.py --scale {args.scale:.2f}；"
        f"标定判据 = axles 1–2 对理想阿克曼角的最大偏差最小")
    path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    design = load_design(path)
    save_design(design, path)
    print(f"applied scale {args.scale:.2f}: " +
          "，".join(f"{n} {old:.4f}→{new:.4f} m" for n, old, new in changed))
    print("written:", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
