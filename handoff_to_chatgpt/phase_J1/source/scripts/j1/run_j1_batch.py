"""PHASE J1 第四/五关：3111 工况快速准稳态计算 + 高速大转角适用性。

**同一个物理模型，两种计算方式**：

``FAST_BATCH_ESTIMATE``
    批量默认：快速准稳态 —— 机构闭链 + 地面附着 + 液压能力检查，
    **不做时间积分**。结果明确打标，不冒充完整动态仿真。
``FULL_DYNAMIC``
    用户对单个工况调用四通道"控制—液压—机械"真实积分（由 run_j1_dynamic 负责）。

要求 3111/3111 全部得到结构完整的结果：任何工况都不允许 KeyError / NaN /
中途停止。超过附着极限的工况照常输出几何与模型预测，并标记
``VEHICLE_DYNAMIC_INFEASIBLE``。
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import time
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from steering_sim.ackermann.assessment import (OK, VEHICLE_DYNAMIC_INFEASIBLE,  # noqa: E402
                                               vehicle_feasibility)
from steering_sim.ackermann.ideal import ideal_ackermann  # noqa: E402
from steering_sim.engineering.mechanism import WHEEL_ORDER  # noqa: E402
from steering_sim.engineering.model import EngineeringSteeringModel  # noqa: E402

SPEC = ROOT / "mechanical_model_input_spec_v1.0.yaml"
ENG_CONFIG = ROOT / "configs" / "j1" / "engineering_config.json"
ENG_DESIGN = ROOT / "configs" / "j1" / "engineering_mechanism.json"
HYD_DESIGN = ROOT / "configs" / "j1" / "hydraulic_design.json"

SPEEDS = tuple(float(v) for v in range(0, 81, 5))
ANGLES = tuple(float(v) for v in range(-30, 31))
FRICTION = (0.70, 0.75, 0.80)
GROUP_OF_AXLE = {1: "front", 2: "front", 3: "front", 4: "axle4", 5: "axle5", 6: "axle6"}


def _blank() -> dict[str, float]:
    return {w: float("nan") for w in WHEEL_ORDER}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "outputs" / "j1"))
    parser.add_argument("--axle-mass", type=float, default=11.5)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    model = EngineeringSteeringModel(SPEC, ENG_CONFIG, ENG_DESIGN)
    hydraulic = json.loads(HYD_DESIGN.read_text(encoding="utf-8"))
    force_limits = {name: float(item["required_force_n"])
                    for name, item in hydraulic["groups"].items()}
    centers = {w: tuple(float(v) for v in model.centers[w]) for w in WHEEL_ORDER}

    specs = [(mu, speed, angle) for mu in FRICTION for speed in SPEEDS for angle in ANGLES]
    if args.limit > 0:
        specs = specs[:args.limit]
    rows: list[dict] = []
    started = time.perf_counter()
    status_counts: dict[str, int] = {}
    for index, (mu, speed, angle) in enumerate(specs, start=1):
        row: dict = {"序号": index, "车速_kmh": speed, "目标角_deg": angle,
                     "摩擦系数": mu, "每桥轴荷_t": args.axle_mass,
                     "计算方式": "FAST_BATCH_ESTIMATE"}
        try:
            ideal = ideal_ackermann(angle, centers)
            for wheel in WHEEL_ORDER:
                row[f"理想_{wheel}"] = round(ideal.angles_deg[wheel], 5)
            geometry = model.solve_geometry(angle)
            state = model.mechanism_state(geometry.q_rad)
            for wheel in WHEEL_ORDER:
                row[f"机构_{wheel}"] = round(float(state.wheel_angles_deg[wheel]), 5)
            row["几何状态"] = geometry.geometry_class
            for name, value in state.representative_stroke_m.items():
                row[f"目标行程_{name}_mm"] = round(float(value) * 1000.0, 4)
            # 附着：a_y = v²/R，R 取质心到 ICR 的距离
            radius = None
            if ideal.y_icr_m is not None:
                cg = 0.0
                radius = math.hypot(cg - ideal.x_icr_m, ideal.y_icr_m)
            feasibility = vehicle_feasibility(speed, mu, radius)
            row["转弯半径_m"] = None if radius is None else round(radius, 3)
            row["侧向加速度_mps2"] = (None if feasibility.lateral_acceleration_mps2 is None
                                      else round(feasibility.lateral_acceleration_mps2, 4))
            row["附着比"] = None if feasibility.adhesion_ratio is None else \
                round(feasibility.adhesion_ratio, 4)
            row["需求侧向力_N"] = (None if feasibility.lateral_acceleration_mps2 is None
                                   else round(feasibility.lateral_acceleration_mps2
                                              * args.axle_mass * 6 * 1000.0, 1))
            row["可提供侧向力_N"] = round(mu * args.axle_mass * 6 * 1000.0 * 9.80665, 1)
            # 液压能力检查（用第二关的选型值对照）
            capability = {}
            for name, value in state.representative_stroke_m.items():
                need = abs(float(value)) * 1000.0
                limit_mm = None
                for group, item in hydraulic["groups"].items():
                    if item["dof"] == ("q_front" if name == "front" else
                                       f"q{name[4:]}"):
                        limit_mm = item["required_half_stroke_mm"]
                        break
                capability[name] = "OK" if (limit_mm is None or need <= limit_mm) else "OVER"
            row["液压行程检查"] = "|".join(f"{k}:{v}" for k, v in capability.items())
            row["液压需求力_N"] = round(
                sum(force_limits.values()) / len(force_limits), 1)
            row["车辆状态"] = feasibility.status
            if feasibility.status != OK:
                row["综合状态"] = VEHICLE_DYNAMIC_INFEASIBLE
            elif geometry.geometry_class != "OK":
                row["综合状态"] = geometry.geometry_class
            else:
                row["综合状态"] = OK
        except Exception as exc:                      # 任何单点异常都不中断批处理
            row["错误"] = f"{type(exc).__name__}: {exc}"[:200]
            row["几何状态"] = "SOLVER_EXCEPTION"
            row["车辆状态"] = None
            row["综合状态"] = "SOLVER_EXCEPTION"
            for wheel in WHEEL_ORDER:
                row.setdefault(f"理想_{wheel}", None)
                row.setdefault(f"机构_{wheel}", None)
        rows.append(row)
        key = str(row["综合状态"])
        status_counts[key] = status_counts.get(key, 0) + 1
        if index % 400 == 0 or index == len(specs):
            print(f"  {index}/{len(specs)}", flush=True)

    path = out / "j1_full_cases.csv"
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    try:
        from openpyxl import Workbook
        book = Workbook(write_only=True)
        sheet = book.create_sheet(title="J1全工况")
        sheet.append(columns)
        for row in rows:
            sheet.append(["" if row.get(key) is None else row.get(key) for key in columns])
        book.save(out / "j1_full_cases.xlsx")
    except Exception as exc:
        print("XLSX 跳过：", exc)

    complete = sum(1 for r in rows if r.get("几何状态") not in (None, "SOLVER_EXCEPTION"))
    errors = sum(1 for r in rows if "错误" in r)
    summary = {
        "cases": len(rows),
        "structurally_complete": complete,
        "solver_errors": errors,
        "status_counts": status_counts,
        "elapsed_s": round(time.perf_counter() - started, 1),
        "mode": "FAST_BATCH_ESTIMATE",
    }
    (out / "j1_batch_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("written:", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
