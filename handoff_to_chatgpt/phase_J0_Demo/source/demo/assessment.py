"""PHASE J0-DEMO 演示前工程检查。

三个检查各自独立、可追溯到具体代码行：

1. **机械轮角方向检查** — 同一转向桥左右轮是否朝同一侧偏转；左右镜像角度的
   定义是否正确；M1 刚体闭链在当前甲方硬点下究竟给出什么结果。检查结果是
   "真实机构结果"时保留结果并标记 ``ACKERMANN_GEOMETRY_DEVIATION``，
   绝不把明显违反理想阿克曼关系的角度宣称为理想阿克曼精确结果。
2. **供油能力检查** — 用实际阀口流量核算高压轨取流量与泵供量，给出余量。
   余量不足时给出黄色工程适用范围警告；确实不足时标记
   ``SUPPLY_CAPACITY_OUT_OF_RANGE``，不显示"供油能力完全正常"。
3. **结果一致性检查** — 图、结果摘要与时间序列必须来自同一次仿真，
   单位与名称一致。

本模块只读，不修改任何被控对象参数，也不引入人工限压。
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Mapping, Sequence

import numpy as np

from steering_sim.hydraulics_lumped.pump import pump_flow

from .scenario import DemoScenario, RangeCheck, check_ranges

WHEEL_ORDER = tuple(f"axle{axle}_{side}" for axle in range(1, 7)
                    for side in ("left", "right"))
AXLE_OF_WHEEL = {wheel: int(wheel[4]) for wheel in WHEEL_ORDER}
SIDE_OF_WHEEL = {wheel: wheel.split("_", 1)[1] for wheel in WHEEL_ORDER}

# 小于该角度视为"基本在中位"，不参与左右同向判定（避免用数值噪声判符号）。
SIGN_TOLERANCE_DEG = 1.0e-4

# 供油余量低于该比例时给出"接近供油上限"的黄色警告。
NEAR_LIMIT_MARGIN_FRACTION = 0.10


def _grade(flags: Sequence[str], ok: str = "OK") -> str:
    return flags[0] if flags else ok


# ===================================================================== 机械
@dataclass(frozen=True, slots=True)
class AxleMechanism:
    axle: int
    ideal_left_deg: float
    ideal_right_deg: float
    mechanism_left_deg: float
    mechanism_right_deg: float
    deviation_left_deg: float
    deviation_right_deg: float
    left_right_opposite: bool
    q_rad: float
    q_boundary_limited: bool

    @property
    def max_abs_deviation_deg(self) -> float:
        return max(abs(self.deviation_left_deg), abs(self.deviation_right_deg))


@dataclass(frozen=True, slots=True)
class MechanismAssessment:
    status: str
    flags: tuple[str, ...]
    axles: tuple[AxleMechanism, ...]
    max_abs_deviation_deg: float
    max_abs_deviation_wheel: str
    opposite_sign_wheels: tuple[str, ...]
    geometry_status: str
    geometry_reachable: bool
    messages: tuple[str, ...]

    @property
    def has_ackermann_deviation(self) -> bool:
        return "ACKERMANN_GEOMETRY_DEVIATION" in self.flags


def assess_mechanism(target: Mapping[str, Any], model) -> MechanismAssessment:
    """用 M1 自己的几何解评估目标转角下的可见性。

    ``target`` 是 ``J0Runner.target(case)`` 的返回值。此处**不重新实现**任何
    闭链几何，只解读 M1 的输出。
    """
    ideal = target["ideal_deg"]
    mechanism = target["mechanism_deg"]
    geometry = target["geometry"]
    q_rad = dict(target["q_ref"])
    boundary = dict(getattr(geometry, "q_boundary_limited", {}) or {})
    dof_of_axle = {1: "q_front", 2: "q_front", 3: "q3", 4: "q4", 5: "q5", 6: "q6"}

    axles: list[AxleMechanism] = []
    opposite: list[str] = []
    for axle in range(1, 7):
        left, right = f"axle{axle}_left", f"axle{axle}_right"
        dev_left = float(mechanism[left] - ideal[left])
        dev_right = float(mechanism[right] - ideal[right])
        is_opposite = (abs(mechanism[left]) > SIGN_TOLERANCE_DEG
                       and abs(mechanism[right]) > SIGN_TOLERANCE_DEG
                       and math.copysign(1.0, mechanism[left])
                       != math.copysign(1.0, mechanism[right]))
        if is_opposite:
            opposite.extend((left, right))
        dof = dof_of_axle[axle]
        axles.append(AxleMechanism(
            axle=axle,
            ideal_left_deg=float(ideal[left]), ideal_right_deg=float(ideal[right]),
            mechanism_left_deg=float(mechanism[left]),
            mechanism_right_deg=float(mechanism[right]),
            deviation_left_deg=dev_left, deviation_right_deg=dev_right,
            left_right_opposite=is_opposite,
            q_rad=float(q_rad.get(dof, 0.0)),
            q_boundary_limited=bool(boundary.get(dof, False)),
        ))
    worst = max(axles, key=lambda item: item.max_abs_deviation_deg)
    worst_wheel = (f"axle{worst.axle}_left"
                   if abs(worst.deviation_left_deg) >= abs(worst.deviation_right_deg)
                   else f"axle{worst.axle}_right")
    deviations = {f"axle{item.axle}_left": abs(item.deviation_left_deg) for item in axles}
    deviations.update({f"axle{item.axle}_right": abs(item.deviation_right_deg)
                       for item in axles})
    worst_wheel = max(deviations, key=deviations.get)

    flags: list[str] = []
    messages: list[str] = []
    # PHASE M2：改用五类状态，不再把"能运动但配不上/左右反号"当成"不可达"。
    geometry_class = str(getattr(geometry, "geometry_class", "OK"))
    if geometry_class == "KINEMATIC_SOLVER_FAILURE":
        flags.append("KINEMATIC_SOLVER_FAILURE")
        messages.append(f"M1 运动学求解失败：{geometry.geometry_status}")
    elif geometry_class == "PHYSICAL_LINKAGE_LIMIT" and opposite:
        flags.append("PHYSICAL_LINKAGE_LIMIT")
        messages.append(
            "同桥左右轮的可达角范围本身是单向的，机构无法使两轮同向"
            "（甲方硬点的几何硬约束）。")
    elif geometry_class == "NUMERICAL_ENVELOPE_LIMIT":
        flags.append("NUMERICAL_ENVELOPE_LIMIT")
        messages.append(f"机构坐标触及数值搜索包络：{geometry.geometry_status}")
    elif boundary and any(boundary.values()):
        flags.append("MECHANISM_ENVELOPE_LIMITED")
        limited = [name for name, value in boundary.items() if value]
        messages.append(f"机构坐标触及数值延拓包络：{', '.join(limited)}")
    if opposite:
        flags.append("ACKERMANN_GEOMETRY_DEVIATION")
        pairs = sorted({f"{w[4]}桥" for w in opposite})
        messages.append(
            "同一转向桥左右轮朝相反方向偏转：" + "、".join(pairs)
            + "。这是 M1 刚体闭链在甲方硬点下的真实解，不是角度映射或符号换算"
              "错误；但它违反低速共同瞬时中心下的同向要求，不能作为理想阿克曼"
              "结果使用。")
    if deviations[worst_wheel] > 0.5:
        if "ACKERMANN_GEOMETRY_DEVIATION" not in flags:
            flags.append("ACKERMANN_GEOMETRY_DEVIATION")
        messages.append(
            f"机构可达角与理想阿克曼角最大偏差 {deviations[worst_wheel]:.3f}°"
            f"（{worst_wheel}），属于 M1 机构拓扑固有属性。")

    for candidate in ("KINEMATIC_SOLVER_FAILURE", "PHYSICAL_LINKAGE_LIMIT",
                      "NUMERICAL_ENVELOPE_LIMIT", "ACKERMANN_GEOMETRY_DEVIATION"):
        if candidate in flags:
            status = candidate
            break
    else:
        status = "OK"
    if not opposite and not messages:
        messages.append("六桥左右轮同向偏转，未检出左右反号。")
    return MechanismAssessment(
        status=status, flags=tuple(flags), axles=tuple(axles),
        max_abs_deviation_deg=deviations[worst_wheel],
        max_abs_deviation_wheel=worst_wheel,
        opposite_sign_wheels=tuple(opposite),
        geometry_status=str(getattr(geometry, "geometry_status", "OK")),
        geometry_reachable=bool(getattr(geometry, "geometry_reachable", True)),
        messages=tuple(messages),
    )


# ===================================================================== 供油
@dataclass(frozen=True, slots=True)
class SupplyGroup:
    name: str
    label: str
    q_pump_m3_s: float
    high_rail_demand_m3_s: float
    auxiliary_flow_m3_s: float
    margin_m3_s: float
    insufficient: bool

    @property
    def margin_fraction(self) -> float:
        if self.q_pump_m3_s <= 0.0:
            return 0.0
        return self.margin_m3_s / self.q_pump_m3_s

    @property
    def near_limit(self) -> bool:
        return (not self.insufficient) and self.margin_fraction < NEAR_LIMIT_MARGIN_FRACTION

    def to_dict(self) -> dict[str, float | str | bool]:
        return {
            "label": self.label,
            "q_pump_l_per_min": self.q_pump_m3_s * 60_000.0,
            "high_rail_demand_l_per_min": self.high_rail_demand_m3_s * 60_000.0,
            "auxiliary_flow_l_per_min": self.auxiliary_flow_m3_s * 60_000.0,
            "margin_l_per_min": self.margin_m3_s * 60_000.0,
            "margin_fraction": self.margin_fraction,
            "insufficient": self.insufficient,
            "near_limit": self.near_limit,
        }


@dataclass(frozen=True, slots=True)
class SupplyAssessment:
    status: str
    flags: tuple[str, ...]
    groups: tuple[SupplyGroup, ...]
    messages: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "flags": list(self.flags),
                "groups": {group.name: group.to_dict() for group in self.groups},
                "messages": list(self.messages)}


def assess_supply(hydraulic, commands: Sequence[float], state: np.ndarray
                  ) -> SupplyAssessment:
    """在给定液压状态上核算高压轨取流量与泵供量。

    直接调用被控对象自己的 ``evaluate``，因此读到的就是仿真内部使用的同一
    份余量核算，不做第二套流量公式。
    """
    from steering_sim.hydraulics_lumped import HydraulicInput, evaluate_hydraulic

    speeds = tuple(channel.pump.nominal_speed for channel in hydraulic.channels)
    loads = tuple(0.0 for _ in hydraulic.channels)
    _, outputs = evaluate_hydraulic(hydraulic, 0.0, state,
                                    HydraulicInput(tuple(commands), speeds, loads))
    groups: list[SupplyGroup] = []
    specs = (("front", "前组（一、二桥）", hydraulic.channels[0]),
             ("rear", "后组（四、五、六桥）", hydraulic.channels[1]))
    for position, (name, label, channel) in enumerate(specs):
        q_pump = pump_flow(channel.pump.nominal_speed, 0.0,
                           channel.supply.tank_pressure, channel.pump) * \
            max(1, len(channel.pump_aliases))
        margin = float(outputs.pump_capacity_margin_m3_s[position])
        groups.append(SupplyGroup(
            name=name, label=label, q_pump_m3_s=q_pump,
            high_rail_demand_m3_s=q_pump - margin - float(channel.supply.auxiliary_flow),
            auxiliary_flow_m3_s=float(channel.supply.auxiliary_flow),
            margin_m3_s=margin,
            insufficient=bool(outputs.pump_capacity_insufficient[position]),
        ))

    flags: list[str] = []
    messages: list[str] = []
    if any(group.insufficient for group in groups):
        flags.append("SUPPLY_CAPACITY_OUT_OF_RANGE")
        for group in groups:
            if group.insufficient:
                messages.append(
                    f"{group.label}：高压轨取流量 "
                    f"{group.high_rail_demand_m3_s * 60000:.2f} L/min 已超过泵供量 "
                    f"{group.q_pump_m3_s * 60000:.2f} L/min，出现供油不足。"
                    f"该工况下的腔压力与流量不再代表真实泵能力，只能作工程演示。")
    elif any(group.near_limit for group in groups):
        flags.append("SUPPLY_CAPACITY_NEAR_LIMIT")
        for group in groups:
            if group.near_limit:
                messages.append(
                    f"{group.label}：供油余量仅 {group.margin_m3_s * 60000:.2f} L/min"
                    f"（{group.margin_fraction * 100:.1f}%），接近泵供量上限。"
                    f"该组是当前的流量瓶颈支路。")
    else:
        messages.append("各供油组余量充足。")

    status = _grade(flags)
    return SupplyAssessment(status=status, flags=tuple(flags), groups=tuple(groups),
                            messages=tuple(messages))


# =============================================================== 综合判定
@dataclass(frozen=True, slots=True)
class PreflightAssessment:
    scenario: DemoScenario
    ranges: tuple[RangeCheck, ...]
    mechanism: MechanismAssessment
    supply: SupplyAssessment
    flags: tuple[str, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    summary_lines: tuple[str, ...]

    @property
    def runnable(self) -> bool:
        return not self.blockers

    @property
    def exact_preset(self) -> bool:
        return not any(item.outside_verified for item in self.ranges)


def assess_preflight(scenario: DemoScenario, runner) -> PreflightAssessment:
    """运行前的三项检查 + 范围校验。不做数值仿真积分。"""
    ranges = check_ranges(scenario)
    case = _as_case(scenario)
    target = runner.target(case)
    mechanism = assess_mechanism(target, runner.geometry.model)
    supply = assess_supply(runner.hydraulic, list(runner.neutral_commands), runner.state0)

    flags: list[str] = []
    blockers: list[str] = []
    warnings: list[str] = []

    for item in ranges:
        if item.outside_customer:
            flags.append(f"INPUT_OUT_OF_TASK_RANGE:{item.field}")
            blockers.append(item.message())
        elif item.outside_verified:
            flags.append(f"EXTRAPOLATION:{item.field}")
            warnings.append(item.message())

    # PHASE M2：五类状态必须分开处理。只有"真实求解不出来"或"所需机构坐标超出
    # 已验证的真实可解范围"才拒绝运行；"能动但配不上阿克曼"（含五六桥左右反号）
    # 属于要如实展示的物理结果，只能警告，不能拒绝。
    geometry_class = str(getattr(target["geometry"], "geometry_class", "OK"))
    q_values = dict(target["q_ref"])
    envelopes = _dof_envelopes(runner)
    boundary = dict(getattr(target["geometry"], "q_boundary_limited", {}) or {})
    over = []
    for dof, bounds in envelopes.items():
        value = float(q_values.get(dof, 0.0))
        low, high = float(bounds[0]), float(bounds[1])
        # 撞上包络边界同样算"超出"：拟合停在了边界上，目标其实没达到。
        if value < low - 1.0e-9 or value > high + 1.0e-9 or boundary.get(dof):
            over.append(f"{dof}={math.degrees(value):+.2f}° 超出 "
                        f"[{math.degrees(low):+.2f}°, {math.degrees(high):+.2f}°]")
    if geometry_class == "KINEMATIC_SOLVER_FAILURE":
        flags.append("KINEMATIC_SOLVER_FAILURE")
        blockers.append("M1 运动学求解失败，拒绝运行。")
    elif over:
        flags.append("BEYOND_VERIFIED_MECHANISM_RANGE")
        blockers.append(
            "目标转角所需的机构坐标超出程序已验证的真实可解范围（连续延拓确认），"
            "拒绝运行：" + "；".join(over))
    if geometry_class == "PHYSICAL_LINKAGE_LIMIT":
        flags.append("PHYSICAL_LINKAGE_LIMIT")
        warnings.append(
            "五、六桥四杆机构为单向可达（距死点仅 6.6°/9.7°），同桥左右轮无法同向。"
            "这是甲方硬点的几何硬约束，不是程序错误；演示将如实展示真实闭链结果。")
    elif geometry_class == "ACKERMANN_TARGET_MISMATCH":
        flags.append("ACKERMANN_TARGET_MISMATCH")
        warnings.append("机构可运动，但左右轮角无法匹配理想阿克曼角。")
    elif geometry_class == "NUMERICAL_ENVELOPE_LIMIT":
        flags.append("NUMERICAL_ENVELOPE_LIMIT")
        warnings.append("机构坐标触及数值搜索包络，结果只能作为工程趋势。")
    if "MECHANISM_ENVELOPE_LIMITED" in mechanism.flags and \
            "NUMERICAL_ENVELOPE_LIMIT" not in flags:
        flags.append("MECHANISM_ENVELOPE_LIMITED")
        warnings.append("机构坐标触及数值延拓包络，结果只能作为工程趋势。")
    warnings.extend(mechanism.messages)
    if mechanism.has_ackermann_deviation:
        flags.append("ACKERMANN_GEOMETRY_DEVIATION")

    flags.extend(supply.flags)
    if "SUPPLY_CAPACITY_OUT_OF_RANGE" in supply.flags:
        warnings.append("供油能力不足，结果不能标记为真实泵能力下验证通过。")
    if "SUPPLY_CAPACITY_NEAR_LIMIT" in supply.flags:
        warnings.append("供油余量接近上限，属于黄色工程适用范围。")

    summary_lines = [
        f"工况：{scenario.describe()}",
        f"已证实范围：{'是（与 J0-R1 已验证工况一致）' if not any(i.outside_verified for i in ranges) else '否，属于外推'}",
        f"机械检查：{mechanism.status}（最大偏差 {mechanism.max_abs_deviation_deg:.3f}°）",
        f"供油检查：{supply.status}",
    ]
    return PreflightAssessment(
        scenario=scenario, ranges=ranges, mechanism=mechanism, supply=supply,
        flags=tuple(dict.fromkeys(flags)), blockers=tuple(blockers),
        warnings=tuple(warnings), summary_lines=tuple(summary_lines),
    )


def _dof_envelopes(runner) -> dict[str, tuple[float, float]]:
    """机构坐标的真实可解范围（rad），取自 M1 配置中经连续延拓验证的包络。"""
    raw = dict(getattr(runner.geometry, "_envelopes", {}) or {})
    if not raw:
        raw = runner.geometry.model.config["geometry"]["q_envelopes_rad"]
    return {dof: (float(bounds[0]), float(bounds[1])) for dof, bounds in raw.items()}


def _as_case(scenario: DemoScenario):
    from steering_sim.j0_coupling.config import J0CaseConfig
    return J0CaseConfig(id=scenario.case_id,
                        target_outer_angle_deg=scenario.target_outer_angle_deg,
                        speed_kmh=scenario.speed_kmh,
                        duration_s=scenario.duration_s)


# =========================================================== 运行后一致性
@dataclass(frozen=True, slots=True)
class ConsistencyReport:
    ok: bool
    flags: tuple[str, ...]
    messages: tuple[str, ...]
    metrics: dict[str, float]


def check_run_consistency(samples: Mapping[str, np.ndarray], summary: Mapping[str, Any],
                          figures: Sequence[str], csv_path: str | None,
                          scenario: DemoScenario) -> ConsistencyReport:
    """图 / 摘要 / 时间序列必须同源，单位一致，且无 NaN/Inf 或异常高压。"""
    flags: list[str] = []
    messages: list[str] = []
    metrics: dict[str, float] = {}

    time = np.asarray(samples.get("time_s", []), dtype=float)
    if time.size == 0:
        return ConsistencyReport(False, ("NO_SAMPLES",), ("没有记录到任何采样点。",), {})
    duration = float(time[-1])
    metrics["time_first_s"] = float(time[0])
    metrics["time_last_s"] = duration
    metrics["sample_count"] = float(time.size)
    # 图、摘要与 CSV 都从同一个 samples 字典生成，时间轴必须覆盖整个仿真时长。
    if abs(duration - scenario.duration_s) > max(1.0e-6, 0.02 * scenario.duration_s):
        flags.append("TIME_AXIS_SHORTER_THAN_REQUESTED")
        messages.append(
            f"时间序列末点 {duration:.3f} s 与请求时长 {scenario.duration_s:.3f} s 不一致，"
            f"图像与摘要不可混用。")

    non_finite = [name for name, values in samples.items()
                  if np.size(values) and not np.all(np.isfinite(np.asarray(values, dtype=float)))]
    if non_finite:
        flags.append("NON_FINITE_SAMPLE")
        messages.append("出现 NaN/Inf 的列：" + "、".join(sorted(non_finite)[:8]))

    max_pressure = float(np.max(np.abs(np.asarray(
        [samples[f"{tag}_pA_mpa_g"] for tag in ("channel_front", "channel_rear_1",
                                                "channel_rear_2", "channel_rear_3")]
        + [samples[f"{tag}_pB_mpa_g"] for tag in ("channel_front", "channel_rear_1",
                                                  "channel_rear_2", "channel_rear_3")],
        dtype=float))))
    metrics["max_chamber_pressure_mpa_g"] = max_pressure
    high_rail = float(np.max(np.abs(np.asarray(
        [samples["supply_pressure_front_mpa_g"], samples["supply_pressure_rear_mpa_g"]],
        dtype=float))))
    metrics["max_supply_pressure_mpa_g"] = high_rail
    if max_pressure > 100.0:
        flags.append("PRESSURE_UNPHYSICAL")
        messages.append(f"腔压力峰值 {max_pressure:.2f} MPa 超过 100 MPa 物理上限。")
    elif max_pressure > 1.35 * max(high_rail, 1.0):
        flags.append("PRESSURE_ABOVE_SUPPLY_ENVELOPE")
        messages.append(
            f"腔压力峰值 {max_pressure:.2f} MPa 超过高压轨的 1.35 倍，需人工复核。")

    third = float(np.max(np.abs(np.asarray(samples["third_axle_max_abs_deg"], dtype=float))))
    metrics["third_axle_max_abs_deg"] = third
    if third > 1.0e-9:
        flags.append("THIRD_AXLE_NOT_LOCKED")
        messages.append(f"三桥未保持 0°，最大 {third:.3e}°。")

    residual = float(np.nanmax(np.asarray(samples["max_link_residual_m"], dtype=float)))
    metrics["max_link_residual_m"] = residual
    if not math.isfinite(residual) or residual > 1.0e-9:
        flags.append("LINK_RESIDUAL_TOO_LARGE")
        messages.append(f"闭链杆长残差 {residual:.3e} m 超限。")

    # 十二轮角必须由真实缸位移经闭链反求。若某轮在**第一个采样点**就已经等于
    # 目标角，说明它是被直接写入而不是积分得到的（初始液压状态为零）。
    copied = []
    for wheel in WHEEL_ORDER:
        target0 = float(np.asarray(samples[f"wheel_{wheel}_target_mechanism_deg"])[0])
        actual0 = float(np.asarray(samples[f"wheel_{wheel}_actual_deg"])[0])
        if abs(target0) > 1.0e-6 and abs(actual0 - target0) < 1.0e-12:
            copied.append(wheel)
    if copied:
        flags.append("WHEEL_ANGLE_COPIED_FROM_TARGET")
        messages.append("首采样点即等于目标角（疑似复制而非闭链反求）："
                        + "、".join(copied[:4]))
    unsolved = [tag for tag in ("channel_front", "channel_rear_1",
                                "channel_rear_2", "channel_rear_3")
                if abs(float(np.asarray(samples[f"{tag}_x_ref_m"])[0])) > 1.0e-6
                and abs(float(np.asarray(samples[f"{tag}_x_m"])[0])) > 1.0e-12]
    if unsolved:
        flags.append("STROKE_STATE_NOT_FROM_INTEGRATION")
        messages.append("首采样点行程已非零（疑似直接写入而非积分）："
                        + "、".join(unsolved))

    if not figures:
        flags.append("NO_FIGURES")
        messages.append("未生成任何图像。")
    if csv_path is None:
        flags.append("NO_CSV")
        messages.append("未导出时间序列 CSV。")

    summary_status = str(summary.get("status", ""))
    metrics["summary_status_is_set"] = 1.0 if summary_status else 0.0
    if not summary_status:
        flags.append("SUMMARY_STATUS_MISSING")
        messages.append("结果摘要缺少状态字段。")

    if not messages:
        messages.append(f"图、摘要与 CSV 同源；时间轴覆盖 0–{duration:.2f} s；无 NaN/Inf；"
                        f"腔压力峰值 {max_pressure:.2f} MPa。")
    return ConsistencyReport(ok=not flags, flags=tuple(flags),
                             messages=tuple(messages), metrics=metrics)
