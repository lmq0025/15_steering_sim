"""PHASE M3：优化设计机构的全工况表与 61 转角几何/行程表。

沿用 PHASE M2 的工况网格（车速 0–80 每 5 → 17 档；目标角 −30~+30 每 1 →
61 档；摩擦系数 0.70/0.75/0.80 → 3 档；基础 1037 组、合计 3111 组），但机构列
改为**优化设计机构**（``REDESIGNED_ACKERMANN``），并可同时给出甲方原始机构的
对照列。

三条硬规则：

1. **缺失数据一律留空**，绝不填 0°。求解失败时给出失败原因。
2. **工况可计算 ≠ 物理可行**。超过轮胎附着的工况照常输出几何与模型预测结果，
   同时标记 ``VEHICLE_DYNAMIC_INFEASIBLE``，绝不说"高速 30° 转向已验证通过"。
3. 批量**只跑快速机械几何 + 地面载荷 + 适用性**，不对 3111 组强制运行
   耗时的电液 PID 动态仿真。
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from .assessment import (ACKERMANN_TARGET_MISMATCH, KINEMATIC_SOLVER_FAILURE,
                         NUMERICAL_ENVELOPE_LIMIT, OK, PHYSICAL_LINKAGE_LIMIT,
                         VEHICLE_DYNAMIC_INFEASIBLE, vehicle_feasibility)
from .cases import (DEFAULT_ANGLES_DEG, DEFAULT_AXLE_LOAD_T, DEFAULT_FRICTION,
                    DEFAULT_SPEEDS_KMH, CaseSpec, build_case_grid, grid_size,
                    write_csv, write_template, write_xlsx)   # noqa: F401
from .ideal import ideal_ackermann
from .redesign import (AS_BUILT_TAG, REDESIGN_TAG, WHEEL_ORDER)
from .transmission import REPRESENTATIVE, RedesignedTransmission, TransmissionError

AXLES = tuple(range(1, 7))
REAR_AXLES = (4, 5, 6)
CYLINDER_NAMES = ("front_group_1", "axle4_A", "axle4_B", "axle5_A", "axle5_B",
                  "axle6_A", "axle6_B")


#: 左右互换的车轮名（镜像对称的正确比较方式）。
FLIP_SIDE = {}
for _wheel in tuple(f"axle{a}_{s}" for a in range(1, 7) for s in ("left", "right")):
    _axle, _side = _wheel.split("_", 1)
    FLIP_SIDE[_wheel] = f"{_axle}_{'right' if _side == 'left' else 'left'}"


def flip_side(wheel: str) -> str:
    return FLIP_SIDE[wheel]


def _blank() -> dict[str, float]:
    return {wheel: float("nan") for wheel in WHEEL_ORDER}


def _cg_x(model, loads_t: Sequence[float]) -> float:
    weights = [float(value) for value in loads_t]
    total = sum(weights)
    if total <= 0.0:
        return 0.0
    xs = [model.centers[f"axle{axle}_left"][0] for axle in AXLES]
    return float(sum(w * x for w, x in zip(weights, xs)) / total)


def _round(value: float | None, digits: int = 6) -> float | None:
    if value is None:
        return None
    value = float(value)
    if not math.isfinite(value):
        return None
    return round(value, digits)


def evaluate_case_m3(spec: CaseSpec, model, transmission: RedesignedTransmission,
                     as_built_model=None, *, with_loaded: bool = True) -> dict[str, Any]:
    """评估一个工况；返回一行扁平记录。缺失量一律 ``None``，不填 0。"""
    centers = {wheel: tuple(float(v) for v in model.centers[wheel])
               for wheel in WHEEL_ORDER}
    target = spec.target_outer_angle_deg
    row: dict[str, Any] = {
        "序号": spec.index,
        "车速_kmh": spec.speed_kmh,
        "目标角_deg": target,
        "摩擦系数": spec.friction_coefficient,
        "每桥轴荷_t": spec.axle_loads_t[0],
        "机械模式": str(getattr(model, "tag", REDESIGN_TAG)),
    }

    # 1) 理想阿克曼角（永远可算）
    ideal = ideal_ackermann(target, centers)
    for wheel in WHEEL_ORDER:
        row[f"理想_{wheel}"] = round(ideal.angles_deg[wheel], 6)

    # 2) 整车动力学适用性 a_y = v²/R
    radius = None
    if ideal.y_icr_m is not None:
        cg = _cg_x(model, spec.axle_loads_t)
        radius = math.hypot(cg - ideal.x_icr_m, ideal.y_icr_m)
    vehicle = vehicle_feasibility(spec.speed_kmh, spec.friction_coefficient, radius)
    row["转弯半径_m"] = _round(radius, 4)
    row["侧向加速度_mps2"] = _round(vehicle.lateral_acceleration_mps2, 4)
    row["附着比"] = _round(vehicle.adhesion_ratio, 4)
    row["附着限值_mu_g_mps2"] = _round(vehicle.adhesion_limit_mps2, 4)

    # 3) 优化设计机构（可解时给出真实机构角与目标行程）
    geometry = None
    solver_error = ""
    try:
        geometry = model.solve_geometry(target)
    except Exception as exc:
        solver_error = f"{type(exc).__name__}: {exc}"
    mechanism = _blank()
    if geometry is not None:
        for wheel in WHEEL_ORDER:
            mechanism[wheel] = float(geometry.theoretical_angle_deg[wheel])
    for wheel in WHEEL_ORDER:
        row[f"机构_{wheel}"] = _round(mechanism[wheel])

    # 4) 目标行程（七个物理缸）与行程超限判定
    strokes: dict[str, float] = {}
    out_of_travel: tuple[str, ...] = ()
    if geometry is not None:
        try:
            solution = transmission.target_angle_to_strokes(target)
            strokes = dict(solution.strokes_m)
            out_of_travel = solution.out_of_travel
        except TransmissionError:
            strokes = {}
    for name in CYLINDER_NAMES:
        row[f"目标行程_{name}_mm"] = (None if name not in strokes
                                      else _round(strokes[name] * 1000.0, 4))
    row["行程超限"] = ("是：" + "、".join(out_of_travel)) if out_of_travel else (
        "否" if strokes else None)
    toggle = None
    if geometry is not None:
        try:
            toggle = float(model.mechanism_state(
                geometry.q_rad).min_toggle_margin_deg)
        except Exception:
            toggle = None
        if toggle is not None and not math.isfinite(toggle):
            toggle = None
    row["死点最小余量_deg"] = _round(toggle, 3)

    # 5) 受载估计角（静态柔度估计，非 J0 液压驱动角）
    loaded = _blank()
    if with_loaded and geometry is not None:
        try:
            from mechanics_ackermann_v2.model import CaseInput
            case = CaseInput(speed_kmh=spec.speed_kmh,
                             first_axle_outer_angle_deg=target,
                             friction_coefficient=spec.friction_coefficient,
                             axle_mass_t=tuple(spec.axle_loads_t))
            loaded_result = model.solve_loaded_case(case, geometry)
            for wheel in WHEEL_ORDER:
                loaded[wheel] = float(loaded_result.actual_loaded_angle_deg[wheel])
        except Exception:
            loaded = _blank()
    for wheel in WHEEL_ORDER:
        row[f"受载_{wheel}"] = _round(loaded[wheel])

    # 6) 甲方原始机构对照（AS_BUILT_REFERENCE，可解时给出）
    if as_built_model is not None:
        try:
            original = as_built_model.solve_geometry(target)
            for wheel in WHEEL_ORDER:
                row[f"原始机构_{wheel}"] = _round(
                    float(original.theoretical_angle_deg[wheel]))
            row["原始机构几何状态"] = str(
                getattr(original, "geometry_class", "OK"))
        except Exception as exc:
            row["原始机构几何状态"] = f"求解失败：{type(exc).__name__}"

    # 7) 状态分类
    flags: list[str] = []
    messages: list[str] = []
    if geometry is None:
        geometry_status = KINEMATIC_SOLVER_FAILURE
        flags.append(KINEMATIC_SOLVER_FAILURE)
        messages.append(f"机构求解失败：{solver_error}")
    else:
        geometry_status = str(getattr(geometry, "geometry_class", OK))
        if geometry_status == PHYSICAL_LINKAGE_LIMIT:
            flags.append("LEFT_RIGHT_OPPOSITE")
            messages.append("同桥左右轮机构可达角反号（结构限制）。")
        elif geometry_status == ACKERMANN_TARGET_MISMATCH:
            flags.append(ACKERMANN_TARGET_MISMATCH)
        elif geometry_status == NUMERICAL_ENVELOPE_LIMIT:
            flags.append(NUMERICAL_ENVELOPE_LIMIT)
            messages.append("机构坐标触及数值延拓包络，结果只能作工程趋势。")
        worst_rms, worst_axle = 0.0, 0
        for axle in REAR_AXLES:
            values = [mechanism[f"axle{axle}_{side}"]
                      - ideal.angles_deg[f"axle{axle}_{side}"]
                      for side in ("left", "right")]
            if any(not math.isfinite(value) for value in values):
                continue
            rms = math.sqrt(sum(v * v for v in values) / len(values))
            if rms > worst_rms:
                worst_rms, worst_axle = rms, axle
        row["阿克曼匹配最大RMS_deg"] = round(worst_rms, 4)
        row["阿克曼匹配最差桥"] = worst_axle
        if worst_rms > 0.25:
            flags.append(ACKERMANN_TARGET_MISMATCH)
            messages.append(f"{worst_axle}桥左右轮对理想阿克曼角的 RMS 偏差 "
                            f"{worst_rms:.3f}°（限值 0.25°）。")
        for axle in REAR_AXLES:
            left = mechanism[f"axle{axle}_left"]
            right = mechanism[f"axle{axle}_right"]
            row[f"{axle}桥方向"] = ("同向" if math.copysign(1.0, left)
                                    == math.copysign(1.0, right) else "反号")
        if not geometry.outer_target_reached:
            flags.append("OUTER_TARGET_NOT_REACHED")
            messages.append("一桥外侧轮未达到目标转角。")
        if out_of_travel:
            flags.append("CYLINDER_STROKE_OUT_OF_TRAVEL")
            messages.append("目标行程超出真实液压缸有效行程：" + "、".join(out_of_travel))

    row["几何状态"] = geometry_status
    row["车辆状态"] = vehicle.status
    if geometry_status != OK and vehicle.status != OK:
        row["综合状态"] = f"{geometry_status}+{VEHICLE_DYNAMIC_INFEASIBLE}"
    elif geometry_status != OK:
        row["综合状态"] = geometry_status
    else:
        row["综合状态"] = vehicle.status
    if not vehicle.feasible:
        flags.append(VEHICLE_DYNAMIC_INFEASIBLE)
        messages.append(vehicle.message)
    row["说明"] = "；".join(messages)
    row["标记"] = ";".join(flags)
    return row


# ------------------------------------------------------------- 61 转角表
@dataclass(frozen=True, slots=True)
class AngleCoverage:
    angle_deg: float
    solved: bool
    direction_ok: bool
    left_right_ok: bool
    mirror_ok: bool
    third_axle_locked: bool
    max_abs_wheel_deg: float | None
    strokes_mm: Mapping[str, float | None]
    strokes_within_travel: bool
    ackermann_rms_deg: float | None
    message: str

    def to_dict(self) -> dict:
        return {
            "目标角_deg": self.angle_deg, "可解": self.solved,
            "方向正确": self.direction_ok, "同桥左右同向": self.left_right_ok,
            "左右转镜像": self.mirror_ok, "三桥锁止": self.third_axle_locked,
            "最大轮角_deg": self.max_abs_wheel_deg,
            "阿克曼RMS_deg": self.ackermann_rms_deg,
            "行程未超限": self.strokes_within_travel,
            "说明": self.message,
            **{f"行程_{name}_mm": value for name, value in self.strokes_mm.items()},
        }


def angle_coverage(model, transmission: RedesignedTransmission,
                   angles=DEFAULT_ANGLES_DEG) -> list[AngleCoverage]:
    """对 ±30° 的每一档做几何、方向、镜像与行程覆盖检查。"""
    centers = {wheel: tuple(float(v) for v in model.centers[wheel])
               for wheel in WHEEL_ORDER}
    rows: list[AngleCoverage] = []
    for angle in angles:
        ideal = ideal_ackermann(angle, centers)
        try:
            geometry = model.solve_geometry(angle)
        except Exception as exc:
            rows.append(AngleCoverage(
                angle, False, False, False, False, True, None,
                {name: None for name in CYLINDER_NAMES}, False, None,
                f"求解失败：{type(exc).__name__}: {exc}"))
            continue
        mechanism = {wheel: float(geometry.theoretical_angle_deg[wheel])
                     for wheel in WHEEL_ORDER}
        sign = math.copysign(1.0, angle) if abs(angle) > 1.0e-12 else 0.0
        direction_ok = True
        left_right_ok = True
        mirror_ok = True
        for axle in range(1, 7):
            left, right = mechanism[f"axle{axle}_left"], mechanism[f"axle{axle}_right"]
            if axle == 3:
                if abs(left) > 1.0e-9 or abs(right) > 1.0e-9:
                    direction_ok = False
                continue
            want = sign if axle in (1, 2) else -sign
            for value in (left, right):
                if abs(value) < 0.05:
                    if abs(ideal.angles_deg[f"axle{axle}_left"]) > 0.5:
                        direction_ok = False
                    continue
                if sign and math.copysign(1.0, value) != want:
                    direction_ok = False
            if abs(left) > 1.0e-6 and abs(right) > 1.0e-6 and \
                    math.copysign(1.0, left) != math.copysign(1.0, right):
                left_right_ok = False
        # 左右转镜像：镜像把车辆左右互换，所以正确的关系是
        #   δ(轮, −t) = −δ(左右互换的轮, +t)
        # 而不是同一个轮名自己取反（同一只轮不在车辆中线上，那样比较是错的）。
        if abs(angle) > 1.0e-12:
            try:
                mirrored = model.solve_geometry(-angle)
                for wheel in WHEEL_ORDER:
                    other = flip_side(wheel)
                    if abs(mechanism[wheel] + float(
                            mirrored.theoretical_angle_deg[other])) > 0.05:
                        mirror_ok = False
                        break
            except Exception:
                mirror_ok = False
        rms_values = [mechanism[f"axle{axle}_{side}"]
                      - ideal.angles_deg[f"axle{axle}_{side}"]
                      for axle in REAR_AXLES for side in ("left", "right")]
        rms = math.sqrt(sum(v * v for v in rms_values) / len(rms_values))
        strokes: dict[str, float | None] = {name: None for name in CYLINDER_NAMES}
        within = False
        message = ""
        try:
            solution = transmission.target_angle_to_strokes(angle)
            for name, value in solution.strokes_m.items():
                strokes[name] = round(value * 1000.0, 4)
            within = solution.strokes_within_travel
            if solution.out_of_travel:
                message = "行程超限：" + "、".join(solution.out_of_travel)
        except TransmissionError as exc:
            message = str(exc)
        rows.append(AngleCoverage(
            angle_deg=float(angle), solved=True, direction_ok=direction_ok,
            left_right_ok=left_right_ok, mirror_ok=mirror_ok,
            third_axle_locked=abs(mechanism["axle3_left"]) < 1.0e-9
            and abs(mechanism["axle3_right"]) < 1.0e-9,
            max_abs_wheel_deg=round(max(abs(v) for v in mechanism.values()), 4),
            strokes_mm=strokes, strokes_within_travel=within,
            ackermann_rms_deg=round(rms, 4), message=message))
    return rows


# --------------------------------------------------------------- 批量驱动
@dataclass(frozen=True, slots=True)
class BatchSummaryM3:
    total: int
    mechanism_solved: int
    vehicle_infeasible: int
    stroke_out_of_travel: int
    status_counts: Mapping[str, int]

    def to_dict(self) -> dict:
        return {"total": self.total, "mechanism_solved": self.mechanism_solved,
                "vehicle_infeasible": self.vehicle_infeasible,
                "stroke_out_of_travel": self.stroke_out_of_travel,
                "status_counts": dict(self.status_counts)}


def run_batch_m3(model, transmission: RedesignedTransmission,
                 specs: Sequence[CaseSpec], *, as_built_model=None,
                 progress=None, with_loaded: bool = True
                 ) -> tuple[list[dict], BatchSummaryM3]:
    report = progress or (lambda _done, _total: None)
    rows: list[dict] = []
    counters: dict[str, int] = {}
    solved = vehicle_bad = stroke_bad = 0
    for position, spec in enumerate(specs, start=1):
        row = evaluate_case_m3(spec, model, transmission,
                               as_built_model=as_built_model,
                               with_loaded=with_loaded)
        rows.append(row)
        status = str(row["综合状态"])
        counters[status] = counters.get(status, 0) + 1
        if row.get("机构_axle1_left") is not None:
            solved += 1
        if row["车辆状态"] != OK:
            vehicle_bad += 1
        if "CYLINDER_STROKE_OUT_OF_TRAVEL" in str(row.get("标记", "")):
            stroke_bad += 1
        if position % 200 == 0 or position == len(specs):
            report(position, len(specs))
    return rows, BatchSummaryM3(
        total=len(rows), mechanism_solved=solved, vehicle_infeasible=vehicle_bad,
        stroke_out_of_travel=stroke_bad,
        status_counts=dict(sorted(counters.items(), key=lambda item: -item[1])))


def write_angle_coverage(rows: Sequence[AngleCoverage], path: Path) -> Path:
    return write_csv([row.to_dict() for row in rows], path)
