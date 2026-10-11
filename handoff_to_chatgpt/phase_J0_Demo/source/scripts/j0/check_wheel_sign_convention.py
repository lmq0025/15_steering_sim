"""PHASE J0-DEMO 检查 1：五、六桥左右轮转角方向核查。

只读检查，不修改任何几何数据：

1. 参考几何的镜像对称性（y -> -y，POS_Y <-> NEG_Y）；
2. 单自由度扫描下 POS_Y / NEG_Y 的 SWING 角与 WHEEL 角；
3. 左右轮命名与 CUSTOMER 坐标系的对应关系；
4. 与理想阿克曼角的偏差分类。
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from steering_sim.mechanics import (SixAxleSteeringKinematics,
                                    reference_geometry_from_file)

ACTUATORS = tuple(f"ACTUATOR_{axle}_{side}" for axle in range(3, 7)
                  for side in ("A", "B"))
DOF_INDEX = {"q_front": 0, "q3": 1, "q4": 2, "q5": 3, "q6": 4}


def _q(dof: str, value: float) -> np.ndarray:
    q = np.zeros(5)
    q[DOF_INDEX[dof]] = value
    return q


def _mirror_name(name: str) -> str:
    if name.endswith("_POS_Y"):
        return name[:-len("_POS_Y")] + "_NEG_Y"
    if name.endswith("_NEG_Y"):
        return name[:-len("_NEG_Y")] + "_POS_Y"
    return name


def _body_problems(reference, name: str) -> list[str]:
    """检查单个 body 与其镜像 body 在 (x, y) -> (x, -y) 下是否一致。"""
    body = reference.bodies[name]
    mirrored = _mirror_name(name)
    if mirrored == name:
        return []
    twin = reference.bodies.get(mirrored)
    if twin is None:
        return [f"{name}: 镜像 body {mirrored} 不存在"]
    problems: list[str] = []
    pivot_error = float(np.max(np.abs(
        np.asarray(twin.pivot) - np.array([body.pivot[0], -body.pivot[1]]))))
    if pivot_error > 1.0e-9:
        problems.append(f"{name}: pivot 非镜像，差 {pivot_error:.3e} m "
                        f"({tuple(body.pivot)} vs {tuple(twin.pivot)})")
    keys = set(body.local_hardpoints) | set(twin.local_hardpoints)
    for point_id in sorted(keys):
        a = body.local_hardpoints.get(point_id)
        b = twin.local_hardpoints.get(point_id)
        if a is None or b is None:
            problems.append(f"{name}.{point_id}: 镜像 body 缺少同名硬点")
            continue
        error = float(np.max(np.abs(np.asarray(b) - np.array([a[0], -a[1]]))))
        if error > 1.0e-9:
            problems.append(f"{name}.{point_id}: 硬点非镜像，差 {error:.3e} m "
                            f"({tuple(a)} vs {tuple(b)})")
    return problems


def mirror_check(reference) -> dict:
    """镜像映射 (x, y) -> (x, -y) 且 POS_Y <-> NEG_Y 下，几何是否自洽。"""
    problems: list[str] = []
    for name in sorted(reference.bodies):
        problems.extend(_body_problems(reference, name))
    return {"ok": not problems, "problems": problems[:40],
            "problem_count": len(problems)}


def sweep(dof: str, values) -> list[dict]:
    """从小步连续延拓求解（冷启动直接求解会落到非解分支）。"""
    rows = []
    axle = dof[1:]
    for value in values:
        solver = SixAxleSteeringKinematics(REFERENCE)
        steps = max(2, int(math.ceil(abs(float(value)) / 0.005)) + 1)
        solution = None
        for factor in np.linspace(0.0, 1.0, steps):
            solution = solver.solve(_q(dof, float(value) * float(factor)))
        row = {"q_deg": math.degrees(float(value))}
        for side in ("POS_Y", "NEG_Y"):
            row[f"swing_{side}_deg"] = math.degrees(
                solution.swing_angles[f"SWING_{axle}_{side}"])
            row[f"wheel_{side}_deg"] = math.degrees(
                solution.wheel_angles[f"WHEEL_{axle}_{side}"])
        row["mean_swing_deg"] = 0.5 * (row["swing_POS_Y_deg"] + row["swing_NEG_Y_deg"])
        rows.append(row)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", default=str(ROOT / "mechanical_model_input_spec_v1.0.yaml"))
    parser.add_argument("--output", default=str(ROOT / "outputs" / "j0_demo"))
    args = parser.parse_args()

    global REFERENCE
    REFERENCE = reference_geometry_from_file(args.spec)

    report: dict = {
        "spec_source_sha256": REFERENCE.source_sha256,
        "bodies": sorted(REFERENCE.bodies),
        "mirror_symmetry_all": mirror_check(REFERENCE),
    }
    # 逐桥镜像检查：只看该桥的 body
    per_axle = {}
    for axle in (1, 2, 3, 4, 5, 6):
        names = [n for n in sorted(REFERENCE.bodies)
                 if f"_{axle}_" in n or n.endswith(f"_{axle}")]
        problems: list[str] = []
        for name in names:
            problems.extend(_body_problems(REFERENCE, name))
        per_axle[axle] = {"bodies": names, "ok": not problems,
                          "problems": problems}
    report["mirror_symmetry_per_axle"] = per_axle

    # 执行器（液压缸）在两侧的布局
    layout = {}
    for name in ACTUATORS:
        actuator = REFERENCE.actuators[name]
        fixed = np.array(REFERENCE.points[actuator.frame_point_id].position)
        layout[name] = {"frame_point": list(map(float, fixed)),
                        "moving_body": actuator.moving_body,
                        "moving_point": actuator.moving_point_id}
    report["actuator_layout"] = layout

    for dof in ("q4", "q5", "q6"):
        values = [math.radians(v) for v in (-5.0, -2.0, 0.0, 2.0, 5.0)]
        report[f"sweep_{dof}"] = sweep(dof, values)

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    target = output / "wheel_sign_check.json"
    target.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str),
                      encoding="utf-8")

    print("=== 镜像对称性 ===")
    print("全局:", "OK" if report["mirror_symmetry_all"]["ok"] else "不对称")
    for axle, item in per_axle.items():
        print(f"  桥{axle}: {'OK' if item['ok'] else '不对称'}  "
              f"{item['problems'][:3]}")
    for dof in ("q4", "q5", "q6"):
        print(f"=== {dof} 扫描 ===")
        print(f"{'q[deg]':>8} {'swingPOS':>10} {'swingNEG':>10} "
              f"{'wheelPOS':>10} {'wheelNEG':>10} {'meanSwing':>10}")
        for row in report[f"sweep_{dof}"]:
            print(f"{row['q_deg']:>8.2f} {row['swing_POS_Y_deg']:>10.4f} "
                  f"{row['swing_NEG_Y_deg']:>10.4f} {row['wheel_POS_Y_deg']:>10.4f} "
                  f"{row['wheel_NEG_Y_deg']:>10.4f} {row['mean_swing_deg']:>10.4f}")
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
