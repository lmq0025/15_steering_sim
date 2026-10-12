"""PHASE J1 第二关：四组液压作动器的工程选型（力 / 行程 / 流量）。

方法（任务书第五节）：

1. 用**优化后的机械传动**算出每组的 ``ds/dδ``（缸行程对车轮角的传动比）；
2. 用最不利正常工作工况的道路负载算出需要的转向力矩 ``M_required``；
3. 虚功关系 ``F_required = M_required / (ds/dδ)`` 得到需要的缸出力；
4. 按设计压力反算需要的有效作用面积（缸径），再留工程余量；
5. 由最大缸速算需要的流量，与泵排量对比。

**所有新尺寸都标 ``ENGINEERING_DESIGN_ASSUMPTION``；旧 Amesim 参数原样存档。**
不通过无限提高压力解决问题。
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

from steering_sim.engineering.model import EngineeringSteeringModel  # noqa: E402
from steering_sim.j0_coupling.config import load_j0_config  # noqa: E402
from steering_sim.j0_coupling.geometry import J0GeometryAdapter  # noqa: E402
from steering_sim.j0_coupling.road_load import road_load  # noqa: E402

SPEC = ROOT / "mechanical_model_input_spec_v1.0.yaml"
ENG_CONFIG = ROOT / "configs" / "j1" / "engineering_config.json"
ENG_DESIGN = ROOT / "configs" / "j1" / "engineering_mechanism.json"
J0_CONFIG = ROOT / "configs" / "j0" / "j0_config.json"

DESIGN_PRESSURE_PA = 17.6e6     # 高压轨设计压力（沿用 L1-Fast 的供压量级）
RETURN_PRESSURE_PA = 0.5e6
SAFETY_FACTOR = 1.25            # 设计载荷余量（任务书允许 20%~30%）
MAX_SPEED_MPS = 0.15            # 设计缸速上限
GEAR_EFFICIENCY = 0.90          # 机械效率假设
WORST_CASE = {"speed_kmh": 10.0, "friction": 0.80, "axle_mass_t": 11.5}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "configs" / "j1"
                                             / "hydraulic_design.json"))
    parser.add_argument("--report", default=str(ROOT / "outputs" / "j1"
                                                / "hydraulic_sizing.csv"))
    args = parser.parse_args()

    config = load_j0_config(J0_CONFIG)
    model = EngineeringSteeringModel(SPEC, ENG_CONFIG, ENG_DESIGN)
    adapter = J0GeometryAdapter(model, config, mechanical_mode="ENGINEERING_STEERING_MODEL")

    rows: list[dict] = []
    for angle in (30.0, 20.0, 10.0):
        geometry = model.solve_geometry(angle)
        q_values = {dof: float(geometry.q_rad[dof]) for dof in adapter.tables}
        road = road_load(adapter, q_values, speed_kmh=WORST_CASE["speed_kmh"],
                         friction_coefficient=WORST_CASE["friction"],
                         axle_mass_t=(WORST_CASE["axle_mass_t"],) * 6,
                         curvature_1pm=float(geometry.curvature_1pm),
                         singular_threshold_m_per_rad=1e-4)
        for channel in config.channels:
            dof = channel.dof
            jac = road.stroke_jacobian_m_per_rad[dof]
            moment = road.generalized_road_moment_nm[dof]
            force = abs(moment) / max(abs(jac), 1e-9) / GEAR_EFFICIENCY
            rows.append({
                "目标角_deg": angle, "通道": channel.channel, "dof": dof,
                "缸行程对轮角传动比_m_per_rad": round(jac, 6),
                "广义道路力矩_Nm": round(moment, 1),
                "需求缸出力_N": round(force, 1),
                "需求缸出力_含余量_N": round(force * SAFETY_FACTOR, 1),
            })

    by_channel: dict[str, float] = {}
    for row in rows:
        by_channel[row["通道"]] = max(by_channel.get(row["通道"], 0.0),
                                      row["需求缸出力_含余量_N"])

    design: dict[str, dict] = {}
    for channel in config.channels:
        required = by_channel[channel.channel]
        # 双向作用缸：有效面积按压力差算
        delta_p = DESIGN_PRESSURE_PA - RETURN_PRESSURE_PA
        area = required / delta_p
        bore = math.sqrt(4.0 * area / math.pi)
        # 行程需求：由该 d o f 在 ±30° 目标下的实际缸行程
        stroke = 0.0
        for angle in (30.0, -30.0):
            geometry = model.solve_geometry(angle)
            state = model.mechanism_state(geometry.q_rad)
            if channel.channel == "channel_front":
                value = abs(state.representative_stroke_m["front"])
            else:
                axle = int(dof_axle(channel.dof))
                value = abs(state.representative_stroke_m[f"axle{axle}"])
            stroke = max(stroke, value)
        design[channel.channel] = {
            "dof": channel.dof,
            "required_force_n": round(required, 1),
            "required_force_no_margin_n": round(required / SAFETY_FACTOR, 1),
            "design_pressure_pa": DESIGN_PRESSURE_PA,
            "required_effective_area_m2": round(area, 8),
            "recommended_bore_mm": round(bore * 1000.0, 2),
            "required_half_stroke_mm": round(stroke * 1000.0 * SAFETY_FACTOR, 2),
            "required_flow_l_per_min": round(area * MAX_SPEED_MPS * 60000.0, 2),
        }

    payload = {
        "schema_version": "J1.0",
        "tag": "ENGINEERING_DESIGN_ASSUMPTION",
        "design_case": WORST_CASE,
        "design_pressure_pa": DESIGN_PRESSURE_PA,
        "return_pressure_pa": RETURN_PRESSURE_PA,
        "safety_factor": SAFETY_FACTOR,
        "gear_efficiency": GEAR_EFFICIENCY,
        "max_cylinder_speed_mps": MAX_SPEED_MPS,
        "method": (
            "虚功 F_required = M_required/(ds/dδ)：M_required 由最不利正常工作工况"
            "（低速大转角）的道路负载给出，ds/dδ 由优化后的机械传动给出。"
            "有效面积按设计压力差反算；行程按 ±30° 目标下的实际机构行程乘安全系数。"),
        "groups": design,
        "notes": (
            "ENGINEERING_DESIGN_ASSUMPTION：这些是**工程选型建议值**，不是甲方设备"
            "实测参数。旧 Amesim/L1-Fast 参数在 configs/j1/hydraulic_design.json 的"
            "legacy_parameters 中原样存档。设计压力沿用 L1-Fast 的供压量级，"
            "没有靠无限提高压力解决问题。"),
        "legacy_parameters": legacy_parameters(),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    report = Path(args.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    import csv
    with report.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps(design, ensure_ascii=False, indent=2))
    print("written:", out, "and", report)
    return 0


def dof_axle(dof: str) -> str:
    return dof[1:] if dof != "q_front" else "1"


def legacy_parameters() -> dict:
    """旧 L1-Fast 参数原样存档（只读，供对照）。"""
    try:
        from steering_sim.hydraulics_lumped.parameters import default_channels
        out = {}
        for channel in default_channels():
            out[channel.name] = {
                "area_a_m2": channel.actuator.area_a,
                "area_b_m2": channel.actuator.area_b,
                "stroke_m": channel.actuator.stroke,
                "pump_displacement_m3_per_rad": channel.pump.displacement,
            }
        return out
    except Exception as exc:                      # pragma: no cover
        return {"error": str(exc)}


if __name__ == "__main__":
    raise SystemExit(main())
