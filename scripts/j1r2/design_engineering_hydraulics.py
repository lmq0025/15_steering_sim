"""PHASE J1-R2：按虚功与流量需求重新设计四组工程液压执行器。

执行顺序（每一步都在本文件里可追溯）：

1. **机构行程包络** —— 从 ``ENGINEERING_STEERING_MODEL`` 的连续延拓包络取出每组
   代表行程的双向极值，乘余量得到缸全行程。
2. **最不利正常工作负载** —— 在 61 个目标角 × 低速档 × 高附着系数上按机构的
   **真实可达构型** 求道路负载，经行程雅可比折成缸力 ``F = Q / (dx/dq)``，
   取各组双向峰值。
3. **有效面积** —— ``A = F_design / p_load``，``F_design`` 含机械效率与安全系数，
   ``p_load`` 取设计负载压力（保证阀还有控制余量），再向上取标准缸径。
4. **折算质量** —— 由转向轴绕主销转动惯量经 ``(dδ/dx)²`` 折算到活塞杆。
5. **阀口面积** —— 使设计速度在满命令、设计负载下仍有节流余量。
6. **流量与泵** —— 单通道峰值流量 × 同一供油轨上同时动作的通道数 × 流量余量。
7. **控制增益** —— 由阀的速度增益 ``Kv`` 给出速度前馈与 P/PI 初值。

输出：``configs/j1r2/engineering_hydraulics.json``（全部标 ``ENGINEERING_DESIGN_ASSUMPTION``）
以及 ``outputs/j1r2/hydraulic_sizing.json`` 选型核算表。

用法::

    python scripts/j1r2/design_engineering_hydraulics.py
    python scripts/j1r2/design_engineering_hydraulics.py --report   # 打印核算表
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

from steering_sim.engineering.model import EngineeringSteeringModel       # noqa: E402
from steering_sim.j0_coupling.config import load_j0_config                # noqa: E402
from steering_sim.j0_coupling.geometry import J0GeometryAdapter           # noqa: E402
from steering_sim.j0_coupling.road_load import road_load                  # noqa: E402

SPEC = ROOT / "mechanical_model_input_spec_v1.0.yaml"
ENGINEERING_CONFIG = ROOT / "configs" / "j1" / "engineering_config.json"
ENGINEERING_DESIGN = ROOT / "configs" / "j1" / "engineering_mechanism.json"
J0_CONFIG = ROOT / "configs" / "j0" / "j0_config.json"
OUT_CONFIG = ROOT / "configs" / "j1r2" / "engineering_hydraulics.json"
OUT_SIZING = ROOT / "outputs" / "j1r2" / "hydraulic_sizing.json"

ASSUMPTION = "ENGINEERING_DESIGN_ASSUMPTION"
DOF_ORDER = ("q_front", "q4", "q5", "q6")
CHANNEL_OF_DOF = {"q_front": "channel_front", "q4": "channel_rear_1",
                  "q5": "channel_rear_2", "q6": "channel_rear_3"}
SUPPLY_OF_CHANNEL = {"channel_front": "front", "channel_rear_1": "rear",
                     "channel_rear_2": "rear", "channel_rear_3": "rear"}
AXLES_OF_DOF = {"q_front": (1, 2), "q4": (4,), "q5": (5,), "q6": (6,)}

# ---------------------------------------------------------------- 设计假设
#: 供油压力上限（溢流阀设定，Pa 表压）。取 21 MPa，与任务书建议的 18~21 MPa 一致。
RELIEF_PRESSURE_PA = 21.0e6
#: 设计负载压力占供压的比例。取 0.7 是为了让阀在设计负载下**仍有节流余量**
#: （Δp_valve = 供压 − 负载压），不是"刚好够用"。
LOAD_PRESSURE_FRACTION = 0.70
#: 机械效率（齿条/梯形/球头/密封折算）。
GEAR_EFFICIENCY = 0.90
#: 安全系数：设计载荷保留约 30% 余量。
SAFETY_FACTOR = 1.30
#: 活塞杆速度上限：由指令斜坡的峰值速度再乘该系数确定阀口面积。
VELOCITY_MARGIN = 1.55
#: 单通道峰值流量的流量余量。
FLOW_MARGIN = 1.25
#: 标准缸径序列（mm）。
STANDARD_BORES_MM = (25.0, 32.0, 40.0, 50.0, 63.0, 80.0, 100.0)
#: 缸死容积 = 该系数 × 满行程容积（含阀到缸的管路）。
DEAD_VOLUME_FRACTION = 0.16
#: 转向轴绕主销的转动惯量假设（kg·m²，每根转向轴：两轮 + 转向节 + 横拉杆）。
#: 由 ``J ≈ 2 × (0.25·m_wheel·r_wheel²) + J_knuckle`` 估得：
#: 单轮 65 kg、滚动半径 0.53 m ⇒ 4.6 kg·m²/轮；转向节与横拉杆约 5 kg·m²。
STEERING_INERTIA_PER_AXLE_KG_M2 = 20.0
#: 油液参数。
FLUID_BULK_MODULUS_PA = 1.0e9
FLUID_DENSITY_KG_M3 = 850.0
TANK_PRESSURE_PA = 5.0e5
PRECHARGE_PRESSURE_PA = 2.0e6
ORIFICE_REGULARISATION_PA = 1.0e5
DISCHARGE_COEFFICIENT = 0.62
VALVE_LAG_TIME_S = 2.0e-3
#: 供油轨蓄能器容积与泵转速。
PLENUM_VOLUME_M3 = 2.0e-3
SUPPLY_BULK_MODULUS_PA = 1.0e9
RELIEF_AREA_M2 = 1.2e-5
PUMP_SPEED_RAD_S = 157.08        # 1500 r/min
#: 指令斜坡：额定转向速率（°/s）与最短斜坡时间（s）。
REFERENCE_RATE_DEG_PER_S = 12.0
REFERENCE_MINIMUM_TIME_S = 0.40
#: 控制器闭环时间常数与积分时间（由 Kv 推出具体增益）。
CLOSED_LOOP_TAU_S = 0.04
INTEGRAL_TIME_S = 0.08
#: 设计扫描用的工况（最不利正常工作工况）。
DESIGN_SPEEDS_KMH = (0.0, 5.0, 10.0, 20.0)
DESIGN_FRICTION = 0.80
DESIGN_ANGLES_DEG = tuple(float(a) for a in range(-30, 31))


def build() -> tuple[EngineeringSteeringModel, J0GeometryAdapter]:
    model = EngineeringSteeringModel(SPEC, ENGINEERING_CONFIG, ENGINEERING_DESIGN)
    adapter = J0GeometryAdapter(model, load_j0_config(J0_CONFIG),
                                mechanical_mode="ENGINEERING_STEERING_MODEL")
    return model, adapter


def stroke_envelope(adapter: J0GeometryAdapter) -> dict[str, tuple[float, float]]:
    """每组代表行程在机构**单调包络**上的双向极值（m，已排序）。

    PHASE J1-R2：缸的全行程就取这个区间，中位偏置取区间中点。也就是说
    **缸的机械限位与机构包络端点重合** —— 缸走到头时机构正好到包络边，
    不会出现"表里查不到、但缸还能走"的空档。机构行程区间一般不对称
    （由甲方缸几何决定），所以必须带偏置，不能强行对称居中。
    """
    result: dict[str, tuple[float, float]] = {}
    for dof in DOF_ORDER:
        table = adapter.tables[dof]
        values = sorted((float(table.stroke(table.q_min)),
                         float(table.stroke(table.q_max))))
        result[dof] = (values[0], values[1])
    return result


def peak_road_force(adapter: J0GeometryAdapter, model: EngineeringSteeringModel,
                    axle_mass_t: float) -> dict[str, dict[str, float]]:
    """最不利工况下各组的需求缸力峰值（正负两个方向分别取峰）。"""
    peaks = {dof: {"positive_n": 0.0, "negative_n": 0.0, "case": "",
                   "by_speed_n": {f"{speed:.0f}": 0.0 for speed in DESIGN_SPEEDS_KMH}}
             for dof in DOF_ORDER}
    singular = float(adapter.config.mapping["singular_jacobian_threshold_m_per_rad"])
    for angle in DESIGN_ANGLES_DEG:
        geometry = adapter.target(angle)
        q_values = {dof: float(geometry.q_rad[dof]) for dof in DOF_ORDER}
        curvature = float(geometry.curvature_1pm)
        for speed in DESIGN_SPEEDS_KMH:
            road = road_load(adapter, q_values, speed_kmh=speed,
                             friction_coefficient=DESIGN_FRICTION,
                             axle_mass_t=(axle_mass_t,) * 6,
                             curvature_1pm=curvature,
                             singular_threshold_m_per_rad=singular,
                             use_actual_curvature=False)
            for dof in DOF_ORDER:
                force = float(road.hydraulic_load_force_n[dof])
                if not math.isfinite(force):
                    continue
                key = "positive_n" if force >= 0.0 else "negative_n"
                if abs(force) > abs(peaks[dof][key]):
                    peaks[dof][key] = force
                    peaks[dof]["case"] = (f"目标角 {angle:+.0f}°, "
                                          f"车速 {speed:.0f} km/h, "
                                          f"μ={DESIGN_FRICTION}")
                bucket = peaks[dof]["by_speed_n"][f"{speed:.0f}"]
                if abs(force) > abs(bucket):
                    peaks[dof]["by_speed_n"][f"{speed:.0f}"] = force
    for dof in DOF_ORDER:
        peaks[dof]["largest_abs_n"] = max(abs(peaks[dof]["positive_n"]),
                                          abs(peaks[dof]["negative_n"]))
    return peaks


def reflected_mass(adapter: J0GeometryAdapter, dof: str) -> dict[str, float]:
    """折算到活塞杆的等效质量：``m = J_轴·(dδ/dq)² / (dx/dq)²``。"""
    table = adapter.tables[dof]
    delta_jacobian = float(np.mean([
        abs(table.angle_jacobian(wheel, 0.0))
        for wheels in [tuple(f"axle{a}_{s}" for s in ("left", "right"))
                       for a in AXLES_OF_DOF[dof]]
        for wheel in wheels]))
    stroke_jacobian = abs(table.stroke_jacobian(0.0))
    inertia = STEERING_INERTIA_PER_AXLE_KG_M2 * len(AXLES_OF_DOF[dof])
    mass = inertia * delta_jacobian ** 2 / stroke_jacobian ** 2
    return {"axles": float(len(AXLES_OF_DOF[dof])),
            "steering_inertia_kg_m2": inertia,
            "d_delta_d_q_rad_per_rad": delta_jacobian,
            "dx_dq_m_per_rad": stroke_jacobian,
            "d_delta_dx_rad_per_m": delta_jacobian / stroke_jacobian,
            "equivalent_mass_kg": mass}


def reference_peak_velocity(target_deg: float, stroke_half_m: float,
                            rate_deg_per_s: float = REFERENCE_RATE_DEG_PER_S,
                            minimum_time_s: float = REFERENCE_MINIMUM_TIME_S
                            ) -> dict[str, float]:
    """指令斜坡的峰值行程速率（S 曲线，峰值 = 1.5 × 平均值）。"""
    ramp = max(minimum_time_s, abs(target_deg) / rate_deg_per_s)
    stroke = stroke_half_m * min(1.0, abs(target_deg) / 30.0)
    average = stroke / ramp
    return {"ramp_time_s": ramp, "stroke_m": stroke,
            "average_velocity_m_s": average, "peak_velocity_m_s": 1.5 * average}


def standard_bore(area_m2: float) -> float:
    diameter_mm = math.degrees(0.0) + 1000.0 * math.sqrt(4.0 * area_m2 / math.pi)
    for bore in STANDARD_BORES_MM:
        if bore >= diameter_mm - 1.0e-9:
            return bore
    return STANDARD_BORES_MM[-1]


def design() -> dict:
    model, adapter = build()
    envelopes = stroke_envelope(adapter)
    peaks = peak_road_force(adapter, model, axle_mass_t=11.5)
    # 设计用 30° 工况确定指令斜坡峰值速度。
    reference = reference_peak_velocity(30.0, 0.18)
    loads_per_supply: dict[str, float] = {}

    channels: list[dict] = []
    supply_flow: dict[str, float] = {name: 0.0 for name in ("front", "rear")}
    for dof in DOF_ORDER:
        channel = CHANNEL_OF_DOF[dof]
        supply = SUPPLY_OF_CHANNEL[channel]
        peak = peaks[dof]
        force_required = float(peak["largest_abs_n"])
        force_design = force_required / GEAR_EFFICIENCY * SAFETY_FACTOR
        load_pressure = LOAD_PRESSURE_FRACTION * RELIEF_PRESSURE_PA
        area_required = force_design / load_pressure
        bore = standard_bore(area_required)
        area = math.pi / 4.0 * (bore / 1000.0) ** 2
        low, high = envelopes[dof]
        stroke = high - low
        half_stroke = 0.5 * stroke
        #: 活塞中位对应的机构行程坐标：区间不对称，必须偏置。
        stroke_offset = 0.5 * (high + low)
        dead_volume = DEAD_VOLUME_FRACTION * area * stroke
        mass = reflected_mass(adapter, dof)
        # 峰值速度用 **±30° 目标下的真实机构行程**（不是包络行程）：任务书的
        # 最大指令就是 ±30°，流量应当按它算，否则会把泵选大。
        q_plus = float(adapter.target(30.0).q_rad[dof])
        q_minus = float(adapter.target(-30.0).q_rad[dof])
        travel_plus = float(adapter.tables[dof].stroke(q_plus))
        travel_minus = float(adapter.tables[dof].stroke(q_minus))
        stroke_at_30 = max(abs(travel_plus), abs(travel_minus))
        velocity = reference_peak_velocity(30.0, stroke_at_30)["peak_velocity_m_s"]
        flow_peak = area * velocity
        supply_flow[supply] += flow_peak
        # 阀口：设计负载下每边可用压差
        valve_delta_p = (RELIEF_PRESSURE_PA - load_pressure) / 2.0
        velocity_target = velocity * VELOCITY_MARGIN
        flow_gain_per_area = (DISCHARGE_COEFFICIENT
                              * math.sqrt(2.0 / FLUID_DENSITY_KG_M3)
                              * math.sqrt(valve_delta_p))
        valve_area = area * velocity_target / flow_gain_per_area
        velocity_per_command = flow_gain_per_area * valve_area / area
        channels.append({
            "dof": dof, "channel": channel, "supply": supply,
            "required_force_n": force_required,
            "design_force_n": force_design,
            "design_load_pressure_pa": load_pressure,
            "required_area_m2": area_required,
            "bore_mm": bore, "area_m2": area,
            "envelope_low_m": low, "envelope_high_m": high,
            "half_stroke_m": half_stroke, "stroke_m": stroke,
            "stroke_offset_m": stroke_offset,
            "stroke_at_30_deg_m": stroke_at_30,
            "travel_at_plus30_m": travel_plus,
            "travel_at_minus30_m": travel_minus,
            "dead_volume_m3": dead_volume,
            "peak_velocity_m_s": velocity, "peak_flow_m3_s": flow_peak,
            "valve_delta_p_pa": valve_delta_p, "valve_area_m2": valve_area,
            "velocity_per_command_m_s": velocity_per_command,
            "reflected_mass": mass,
            "force_at_relief_n": (RELIEF_PRESSURE_PA - TANK_PRESSURE_PA) * area,
            "peak_case": peak["case"],
        })

    # 折算质量给出刚度与自然频率（用于确认积分步长足够细）。
    for item in channels:
        area = item["area_m2"]
        volume = item["dead_volume_m3"] + area * item["half_stroke_m"]
        stiffness = FLUID_BULK_MODULUS_PA * area ** 2 / volume
        item["hydraulic_stiffness_n_per_m"] = stiffness
        item["natural_frequency_hz"] = (math.sqrt(stiffness /
                                                  item["reflected_mass"]["equivalent_mass_kg"])
                                        / (2.0 * math.pi))
        item["critical_damping_n_s_per_m"] = 2.0 * math.sqrt(
            stiffness * item["reflected_mass"]["equivalent_mass_kg"])
        # 密封黏性阻尼取临界阻尼的 45%（工程经验量级），库仑摩擦取额定力的 2%。
        # 主阻尼来自阀口压力-流量特性（由模型自身产生，量级约 1e5 N·s/m）；
        # 这里只补一项**密封黏性摩擦**，取临界阻尼的 3%，避免小信号下出现
        # 无阻尼高频模态。取 0.45 那种量级会把物理阻尼算重几十倍。
        item["viscous_damping_n_s_per_m"] = 0.03 * item["critical_damping_n_s_per_m"]
        item["coulomb_friction_n"] = 0.02 * item["design_force_n"]

    supplies = {}
    for name, flow in supply_flow.items():
        target = flow * FLOW_MARGIN
        displacement = target / PUMP_SPEED_RAD_S
        supplies[name] = {
            "displacement_m3_per_rad": displacement,
            "nominal_speed_rad_s": PUMP_SPEED_RAD_S,
            "relief_pressure_pa": RELIEF_PRESSURE_PA,
            "plenum_volume_m3": PLENUM_VOLUME_M3,
            "bulk_modulus_pa": SUPPLY_BULK_MODULUS_PA,
            "relief_area_m2": RELIEF_AREA_M2,
            "simultaneous_peak_flow_m3_s": flow,
        }

    return {"channels": channels, "supplies": supplies,
            "reference": reference, "envelopes": envelopes, "peaks": peaks}


def control_gains(item: dict) -> dict[str, float]:
    velocity_per_command = float(item["velocity_per_command_m_s"])
    kff = 1.0 / velocity_per_command
    kp = 1.0 / (velocity_per_command * CLOSED_LOOP_TAU_S)
    ki = kp / INTEGRAL_TIME_S
    return {"kp": kp, "ki": ki, "kd": 0.0, "kff": kff}


def build_config(result: dict) -> dict:
    channels = []
    for item in result["channels"]:
        gains = control_gains(item)
        cylinder = item["reflected_mass"]
        channels.append({
            "name": item["channel"],
            "dof": item["dof"],
            "supply": item["supply"],
            "polarity": 1.0,
            "kp": round(gains["kp"], 4),
            "ki": round(gains["ki"], 4),
            "kd": 0.0,
            "kff": round(gains["kff"], 6),
            "command_limit": 1.0,
            "reference_peak_velocity_m_s": round(item["peak_velocity_m_s"], 6),
            "cylinder": {
                "area_a_m2": item["area_m2"],
                "area_b_m2": item["area_m2"],
                "bore_mm": item["bore_mm"],
                "stroke_m": round(item["stroke_m"], 6),
                "stroke_offset_m": round(item["stroke_offset_m"], 6),
                "dead_volume_m3": item["dead_volume_m3"],
                "mass_kg": round(cylinder["equivalent_mass_kg"], 2),
                "viscous_damping_n_s_per_m": round(item["viscous_damping_n_s_per_m"], 2),
                "coulomb_friction_n": round(item["coulomb_friction_n"], 2),
                "end_stop_stiffness_n_per_m": round(
                    15.0 * item["hydraulic_stiffness_n_per_m"], 1),
                "end_stop_damping_n_s_per_m": round(
                    1.5 * item["critical_damping_n_s_per_m"], 1),
                "mass_source": (
                    f"{ASSUMPTION}：J_轴={cylinder['steering_inertia_kg_m2']:.0f} kg·m²"
                    f"（{cylinder['axles']:.0f} 根转向轴）经 (dδ/dx)² 折算，"
                    f"dδ/dx={cylinder['d_delta_dx_rad_per_m']:.4f} rad/m"),
            },
            "valve": {
                "maximum_area_m2": item["valve_area_m2"],
                "discharge_coefficient": DISCHARGE_COEFFICIENT,
                "lag_time_s": VALVE_LAG_TIME_S,
                "deadband": 0.0,
                "velocity_per_unit_command_m_s": round(
                    item["velocity_per_command_m_s"], 6),
            },
            "notes": (
                f"{ASSUMPTION}：对称双出杆缸（双腔有效面积相等），保证左右转向"
                f"力与速度对称。需求缸力 {item['required_force_n']:.0f} N 来自最不利"
                f"工况（{item['peak_case']}）；安全系数 {SAFETY_FACTOR}、机械效率"
                f" {GEAR_EFFICIENCY}；设计负载压力 "
                f"{item['design_load_pressure_pa'] / 1e6:.1f} MPa。"),
        })
    return {
        "schema_version": "J1R2.0",
        "tag": "ENGINEERING_HYDRAULIC_V1",
        "fluid_bulk_modulus_pa": FLUID_BULK_MODULUS_PA,
        "fluid_density_kg_m3": FLUID_DENSITY_KG_M3,
        "tank_pressure_pa": TANK_PRESSURE_PA,
        "precharge_pressure_pa": PRECHARGE_PRESSURE_PA,
        "orifice_pressure_regularisation_pa": ORIFICE_REGULARISATION_PA,
        "supplies": {name: {
            "displacement_m3_per_rad": item["displacement_m3_per_rad"],
            "nominal_speed_rad_s": item["nominal_speed_rad_s"],
            "relief_pressure_pa": item["relief_pressure_pa"],
            "plenum_volume_m3": item["plenum_volume_m3"],
            "bulk_modulus_pa": item["bulk_modulus_pa"],
            "relief_area_m2": item["relief_area_m2"],
        } for name, item in result["supplies"].items()},
        "channels": channels,
        "degradation": {
            "pump_volumetric_efficiency": 1.0,
            "pump_internal_leakage_m3_s_per_pa": 0.0,
            "valve_flow_coefficient_scale": 1.0,
            "valve_lag_scale": 1.0,
            "cylinder_internal_leakage_m3_s_per_pa": 0.0,
            "cylinder_friction_scale": 1.0,
            "supply_pressure_scale": 1.0,
        },
        "reference": {
            "rate_deg_per_s": REFERENCE_RATE_DEG_PER_S,
            "minimum_time_s": REFERENCE_MINIMUM_TIME_S,
            "note": "一桥外侧轮目标角的指令斜坡速率与最短斜坡时间。",
        },
        "assumptions": [
            f"{ASSUMPTION}：本文件所有液压参数（缸径、面积、行程、容积、阻尼、"
            f"摩擦、阀口面积、泵排量、供压、控制器增益）都是 J1-R2 的工程选型值，"
            f"不是甲方设备实测参数，也不继承旧 Amesim/L1-Fast 数值。",
            f"{ASSUMPTION}：每个等效作动通道用一只**对称双出杆缸**代表，"
            f"保证左右转向的力与速度对称；这等价于甲方对置单杆缸对的工程等效。",
            f"{ASSUMPTION}：折算质量由转向轴绕主销转动惯量 "
            f"{STEERING_INERTIA_PER_AXLE_KG_M2:.0f} kg·m²/轴经 (dδ/dx)² 得到。",
        ],
        "provenance": {
            "method": "虚功 F = M/(ds/dδ) + 流量法 + 折算惯量",
            "design_case": (f"{DESIGN_SPEEDS_KMH} km/h × ±30° × μ={DESIGN_FRICTION} "
                            f"× 11.5 t/轴，取双向峰值"),
            "safety_factor": str(SAFETY_FACTOR),
            "gear_efficiency": str(GEAR_EFFICIENCY),
            "flow_margin": str(FLOW_MARGIN),
            "velocity_margin": str(VELOCITY_MARGIN),
        },
        "notes": ("PHASE J1-R2 唯一正式液压模型 ``ENGINEERING_HYDRAULIC_V1`` 的参数。"
                  "旧 L1-Fast 参数作为历史证据保留在 configs/j1/hydraulic_design.json。"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(OUT_CONFIG))
    parser.add_argument("--sizing", default=str(OUT_SIZING))
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()

    result = design()
    config = build_config(result)
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(config, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    sizing = {
        "schema_version": "J1R2.0",
        "provenance": config["provenance"],
        "groups": {item["channel"]: {
            "dof": item["dof"],
            "supply": item["supply"],
            "required_force_n": item["required_force_n"],
            "design_force_n": item["design_force_n"],
            "force_at_relief_n": item["force_at_relief_n"],
            "static_margin": item["force_at_relief_n"] / item["required_force_n"],
            "design_load_pressure_pa": item["design_load_pressure_pa"],
            "required_area_m2": item["required_area_m2"],
            "bore_mm": item["bore_mm"], "area_m2": item["area_m2"],
            "half_stroke_m": item["half_stroke_m"], "stroke_m": item["stroke_m"],
            "stroke_offset_m": item["stroke_offset_m"],
            "stroke_at_30_deg_m": item["stroke_at_30_deg_m"],
            # 行程余量必须用**有符号**的 ±30° 实际行程算：机构行程区间不对称，
            # 拿绝对值去比上下限会在其中一侧算出假的负余量。
            "operating_margin_at_30_mm": {
                "minus": round((item["travel_at_minus30_m"]
                                - item["envelope_low_m"]) * 1000, 3),
                "plus": round((item["envelope_high_m"]
                               - item["travel_at_plus30_m"]) * 1000, 3)},
            "travel_at_30_deg_m": {"minus": item["travel_at_minus30_m"],
                                   "plus": item["travel_at_plus30_m"]},
            "peak_velocity_m_s": item["peak_velocity_m_s"],
            "peak_flow_l_per_min": item["peak_flow_m3_s"] * 60000.0,
            "valve_area_m2": item["valve_area_m2"],
            "valve_delta_p_pa": item["valve_delta_p_pa"],
            "velocity_per_command_m_s": item["velocity_per_command_m_s"],
            "equivalent_mass_kg": item["reflected_mass"]["equivalent_mass_kg"],
            "natural_frequency_hz": item["natural_frequency_hz"],
            "viscous_damping_n_s_per_m": item["viscous_damping_n_s_per_m"],
            "coulomb_friction_n": item["coulomb_friction_n"],
            "peak_case": item["peak_case"],
            "peak_force_by_speed_n": result["peaks"][item["dof"]]["by_speed_n"],
        } for item in result["channels"]},
        "supplies": {name: {
            "simultaneous_peak_flow_l_per_min": item["simultaneous_peak_flow_m3_s"] * 60000.0,
            "pump_flow_l_per_min": (item["displacement_m3_per_rad"]
                                    * item["nominal_speed_rad_s"] * 60000.0),
            "relief_pressure_mpa": item["relief_pressure_pa"] / 1e6,
        } for name, item in result["supplies"].items()},
        "reference": result["reference"],
    }
    sizing_path = Path(args.sizing)
    sizing_path.parent.mkdir(parents=True, exist_ok=True)
    sizing_path.write_text(json.dumps(sizing, ensure_ascii=False, indent=2),
                           encoding="utf-8")

    if args.report:
        for name, item in sizing["groups"].items():
            print(f"{name:18s} F需{item['required_force_n']:8.0f} N  "
                  f"缸径{item['bore_mm']:5.1f} mm  "
                  f"行程±{item['half_stroke_m'] * 1000:7.1f} mm  "
                  f"峰值流{item['peak_flow_l_per_min']:5.2f} L/min  "
                  f"静力裕度{item['static_margin']:5.2f}  "
                  f"fn{item['natural_frequency_hz']:5.1f} Hz  "
                  f"m{item['equivalent_mass_kg']:7.1f} kg")
        for name, item in sizing["supplies"].items():
            print(f"泵[{name}] 峰值需求 {item['simultaneous_peak_flow_l_per_min']:6.2f} "
                  f"L/min，泵流量 {item['pump_flow_l_per_min']:6.2f} L/min，"
                  f"溢流 {item['relief_pressure_mpa']:.1f} MPa")

    print("written:", target)
    print("written:", sizing_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
