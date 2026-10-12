"""PHASE J1：由甲方硬点解析地生成 ``ENGINEERING_STEERING_MODEL`` 设计参数。

不做结构搜索。齿条式 + 转向梯形的几何由几条明确的工程规则直接定出：

1. **转向臂长度** ``arm_length``（与甲方原始摇臂同量级）；
2. **转向臂方向 = 指向该桥的共同瞬时转向中心**（经典阿克曼梯形做法）。
   这一条同时保证机构雅可比在零位非奇异 —— 若转向臂正好横向，梯形横拉杆在零位
   对"左右轮反向转动"的一阶灵敏度为零，机构退化（PHASE M3 实测过）。
3. **齿条纵向位置** = 转向臂端点平均 x 后退 ``rack_offset``；
4. **齿条端球头 y** 由边拉杆长度 ``link_length`` 反推（Δx 固定为 ``rack_offset``）：
   ``e = K_y − sign(K_y)·√(L² − offset²)``，取靠车内侧的根；
5. **齿条驱动点** = 齿条上离摆臂最远的那个端球头；
6. **摆臂拾取点方向** 按 2° 扫一遍取传动角最大的方向（只解一个标量方向）。

每个机构组各有一套尺寸（各桥转向臂指向 ICR 的角度不同），逐组用一个小网格
（4×4×4×3 = 192 组）选出使"工作区间内最小传动角余量"最大的那一套。这是标量
尺寸选型，不是机械结构搜索。

生成后做全范围校核：有效工作区间（该桥轮角 ±35°）内的传动角、可达性、传动比、
齿条行程；任何一项不达标就不写配置。
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

from steering_sim.engineering.mechanism import (ASSUMPTION_TAG, EngineeringDesign,
                                                EngineeringMechanism, GroupDesign,
                                                LEGACY_SIDE, MechanismError,
                                                SideDesign, TAG, save_design)
from steering_sim.mechanics import reference_geometry_from_file  # noqa: E402

SPEC = ROOT / "mechanical_model_input_spec_v1.0.yaml"
GROUPS = ("front", "axle4", "axle5", "axle6")
GROUP_AXLES = {"front": (1, 2), "axle4": (4,), "axle5": (5,), "axle6": (6,)}
GROUP_DRIVEN = {"front": 1, "axle4": 4, "axle5": 5, "axle6": 6}

TARGET_RANGE_DEG = 35.0        # 需要覆盖的转向节转角（目标角 ±30° 留余量）
MIN_TOGGLE_MARGIN_DEG = 25.0   # 工作区间内的传动角下限（距死点）

#: 每组的设计尺寸（m）。由 ``--scan`` 逐组选出，全部为
#: ``ENGINEERING_DESIGN_ASSUMPTION``（甲方未提供这些尺寸）。
PARAMS: dict[str, dict[str, float]] = {
    "front": {
        "arm_length": 0.22,
        "rack_offset": 0.03,
        "link_length": 0.64,
        "swing_radius": 0.16
    },
    "axle4": {
        "arm_length": 0.22,
        "rack_offset": 0.2,
        "link_length": 0.36,
        "swing_radius": 0.32
    },
    "axle5": {
        "arm_length": 0.34,
        "rack_offset": 0.12,
        "link_length": 0.48,
        "swing_radius": 0.32
    },
    "axle6": {
        "arm_length": 0.34,
        "rack_offset": 0.07,
        "link_length": 0.36,
        "swing_radius": 0.24
    }
}


def _unit(angle: float) -> np.ndarray:
    return np.array([math.cos(angle), math.sin(angle)])


def _rot(vector: np.ndarray, angle: float) -> np.ndarray:
    c, s = math.cos(angle), math.sin(angle)
    return np.array([c * vector[0] - s * vector[1], s * vector[0] + c * vector[1]])


def _margin(relative_deg: float) -> float:
    wrapped = (relative_deg + 180.0) % 360.0 - 180.0
    return min(abs(wrapped), 180.0 - abs(wrapped))


def _icr_x(reference) -> float:
    return 0.5 * (float(reference.bodies["WHEEL_3_NEG_Y"].pivot[0])
                  + float(reference.bodies["WHEEL_3_POS_Y"].pivot[0]))


def arm_points(reference, axle: int, arm_length: float) -> dict:
    x_icr = _icr_x(reference)
    out = {}
    for side in ("left", "right"):
        pivot = np.asarray(reference.bodies[f"WHEEL_{axle}_{LEGACY_SIDE[side]}"].pivot,
                           dtype=float)
        direction = _unit(math.atan2(-pivot[1], x_icr - pivot[0]))
        out[side] = {"pivot": pivot, "direction": direction,
                     "arm_tip": pivot + arm_length * direction}
    return out


def rack_layout(points, rack_offset: float, link_length: float):
    rack_x = float(np.mean([points[s]["arm_tip"][0] for s in ("left", "right")])) \
        - rack_offset
    offset = math.sqrt(max(0.0, link_length ** 2 - rack_offset ** 2))
    ends = {s: float(points[s]["arm_tip"][1])
            - math.copysign(offset, float(points[s]["arm_tip"][1]))
            for s in ("left", "right")}
    return rack_x, ends


def choose_swing_pickup(pivot: np.ndarray, drive_point: np.ndarray, radius: float):
    best = None
    for step in range(180):
        psi = math.radians(-180.0 + 2.0 * step)
        pickup = pivot + radius * _unit(psi)
        delta = drive_point - pickup
        length = float(np.linalg.norm(delta))
        if length < 0.15:
            continue
        margin = _margin(math.degrees(math.atan2(delta[1], delta[0]) - psi))
        if best is None or margin > best[0]:
            best = (margin, pickup, length)
    return best


def build(reference, params: dict[str, dict[str, float]] | None = None
          ) -> EngineeringDesign:
    values = params or PARAMS
    groups: dict[str, GroupDesign] = {}
    for key in GROUPS:
        cfg = values[key]
        axles = GROUP_AXLES[key]
        driven = GROUP_DRIVEN[key]
        points = {axle: arm_points(reference, axle, cfg["arm_length"])
                  for axle in axles}
        racks, ends = {}, {}
        for axle in axles:
            rack_x, rack_ends = rack_layout(points[axle], cfg["rack_offset"],
                                            cfg["link_length"])
            racks[axle] = rack_x
            ends[axle] = rack_ends
        pivot = np.asarray(reference.bodies[f"SWING_{driven}_NEG_Y"].pivot, dtype=float)
        far_side = "left" if abs(ends[driven]["left"] - pivot[1]) >= \
            abs(ends[driven]["right"] - pivot[1]) else "right"
        drive_point = np.array([racks[driven], ends[driven][far_side]])
        margin, pickup, drive_length = choose_swing_pickup(
            pivot, drive_point, cfg["swing_radius"])
        sides: dict[str, SideDesign] = {}
        for axle in axles:
            for side in ("left", "right"):
                name = f"axle{axle}_{side}"
                swing_pickup = tuple(float(v) for v in pickup) \
                    if (axle == driven and side == "right") else (0.0, 0.0)
                sides[name] = SideDesign(
                    arm_tip=tuple(float(v) for v in points[axle][side]["arm_tip"]),
                    swing_pickup=swing_pickup,
                    rack_end=(float(racks[axle]), float(ends[axle][side])))
        relay = None
        if len(axles) == 2:
            relay = ((float(racks[axles[0]]), float(ends[axles[0]]["left"])),
                     (float(racks[axles[1]]), float(ends[axles[1]]["left"])))
        groups[key] = GroupDesign(
            key=key, axles=tuple(axles), driven_axle=driven,
            rack_drive_point=tuple(float(v) for v in drive_point),
            racks=dict(racks), sides=sides, relay=relay,
            notes=(f"驱动连杆长 {drive_length:.4f} m，摆臂拾取点传动角 {margin:.1f}°",
                   f"尺寸 arm={cfg['arm_length']} offset={cfg['rack_offset']} "
                   f"link={cfg['link_length']} radius={cfg['swing_radius']}"))
    return EngineeringDesign(
        schema_version="J1.0", tag=TAG, groups=groups,
        assumptions=(
            f"{ASSUMPTION_TAG}: 转向臂长度 / 齿条后移量 / 边拉杆长度 / 摆臂拾取半径"
            " 逐组取值见各组 notes（甲方未提供这些尺寸）",
            "CUSTOMER_GEOMETRY: 转向节主销（车轮中心）、摆臂枢轴、液压缸机架点与"
            "活塞杆安装点全部沿用甲方原值，未做任何修改。",
            "机械传动原理：液压缸 → 甲方摆臂 → 驱动连杆 → 齿条（沿 y 平动）→ "
            "两根边拉杆 → 左右转向节；左右转向臂指向共同瞬时转向中心，"
            "阿克曼差动由转向梯形本身产生，不是显示层做差。",
            "前组：一桥齿条由摆臂驱动，二桥齿条由中间拉杆与一桥齿条 1:1 耦合"
            "（一桥主动、二桥随动）。",
        ),
        provenance={"source": SPEC.name, "icr_reference_axle": "3",
                    "third_axle_locked": "true"})


# ------------------------------------------------------------------ 校核
def _solve(mechanism, key: str, q: float, *, continuous: bool = True):
    """求解一个构型。

    ``continuous=True`` 时从零位以小步长走过去，保证始终跟在同一个装配分支上 ——
    直接跳到远处的 q 会让"取最近根"相对零位而不是相对相邻构型，可能跳到另一个
    残差同样合格、物理上完全不同的构型（PHASE M3 实测过：直行被解成 −242°）。
    """
    q = float(q)
    if not continuous or abs(q) < 1.0e-9:
        try:
            mechanism.reset_group(key, q)
            return mechanism.solve_swing(key, q)
        except MechanismError:
            return None
    step = math.radians(1.0) * (1.0 if q > 0 else -1.0)
    mechanism.reset_group(key, 0.0)
    mechanism.solve_swing(key, 0.0)
    count = max(1, int(math.ceil(abs(q) / abs(step))))
    state = None
    for index in range(1, count + 1):
        try:
            state = mechanism.solve_swing(key, q * index / count)
        except MechanismError:
            return None
    return state


def _reachable_limit(mechanism, key: str, direction: float, limit_deg: float = 120.0):
    """从零位连续外扩，返回最后一个可解构型（rad，带符号）。"""
    step = math.radians(1.0)
    limit = math.radians(limit_deg)
    mechanism.reset_group(key, 0.0)
    mechanism.solve_swing(key, 0.0)
    q = last = 0.0
    while abs(q) < limit:
        nxt = q + direction * step
        try:
            mechanism.solve_swing(key, nxt)
        except MechanismError:
            break
        last, q = nxt, nxt
    return last


def _swing_for_wheel(mechanism, key: str, axle: int, target_rad: float):
    wheel = f"axle{axle}_right"
    direction = 1.0 if target_rad > 0 else -1.0
    bound = _reachable_limit(mechanism, key, direction)
    if abs(bound) < 1.0e-9:
        return None
    state = _solve(mechanism, key, bound)
    if state is None or abs(state.wheel_angles_rad[wheel]) < abs(target_rad):
        return None
    lo, hi = 0.0, abs(bound)
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        probe = _solve(mechanism, key, direction * mid)
        if probe is None:
            hi = mid
        elif abs(probe.wheel_angles_rad[wheel]) >= abs(target_rad):
            hi = mid
        else:
            lo = mid
    return direction * hi


def verify_group(reference, design: EngineeringDesign, key: str) -> dict:
    mechanism = EngineeringMechanism(reference, design)
    group = design.groups[key]
    axle = group.driven_axle
    wheel = f"axle{axle}_right"
    q_pos = _swing_for_wheel(mechanism, key, axle, math.radians(TARGET_RANGE_DEG))
    q_neg = _swing_for_wheel(mechanism, key, axle, -math.radians(TARGET_RANGE_DEG))
    entry: dict = {"driven_axle": axle,
                   "q_plus_deg": None if q_pos is None else math.degrees(q_pos),
                   "q_minus_deg": None if q_neg is None else math.degrees(q_neg)}
    if q_pos is None or q_neg is None:
        entry.update(min_toggle_margin_deg=0.0, gain_rad_per_rad=0.0,
                     max_rack_slide_m=0.0)
        return entry
    mechanism.reset()
    eps = 1.0e-4
    plus = _solve(mechanism, key, eps)
    minus = _solve(mechanism, key, -eps)
    mechanism.reset()
    entry["gain_rad_per_rad"] = (
        (plus.wheel_angles_rad[wheel] - minus.wheel_angles_rad[wheel]) / (2 * eps))
    margins: list[float] = []
    slides: list[float] = []
    for q in np.linspace(q_neg, q_pos, 61):
        state = _solve(mechanism, key, float(q))
        if state is None:
            return dict(entry, min_toggle_margin_deg=0.0, max_rack_slide_m=0.0)
        slides.append(abs(state.rack_slide_m[group.axles[0]]))
        pickup = np.asarray(group.sides[f"axle{axle}_right"].swing_pickup, dtype=float)
        pivot = np.asarray(reference.bodies[f"SWING_{axle}_NEG_Y"].pivot, dtype=float)
        arm_dir = pickup - pivot
        swing_point = pivot + _rot(arm_dir, float(q))
        link = np.asarray(group.rack_drive_point, dtype=float) - swing_point
        margins.append(_margin(math.degrees(
            math.atan2(link[1], link[0])
            - (math.atan2(arm_dir[1], arm_dir[0]) + float(q)))))
        for axle_i in group.axles:
            for side in ("left", "right"):
                name = f"axle{axle_i}_{side}"
                side_design = group.sides[name]
                wheel_pivot = np.asarray(reference.bodies[
                    f"WHEEL_{axle_i}_{LEGACY_SIDE[side]}"].pivot, dtype=float)
                arm_local = np.asarray(side_design.arm_tip, dtype=float) - wheel_pivot
                theta = state.wheel_angles_rad[name]
                tip = wheel_pivot + _rot(arm_local, theta)
                end = np.array([group.racks[axle_i],
                                side_design.rack_end[1] + state.rack_slide_m[axle_i]])
                delta = end - tip
                margins.append(_margin(math.degrees(
                    math.atan2(delta[1], delta[0])
                    - (math.atan2(arm_local[1], arm_local[0]) + theta))))
    entry["min_toggle_margin_deg"] = float(min(margins))
    entry["max_rack_slide_m"] = float(max(slides))
    return entry


def verify(reference, design: EngineeringDesign) -> dict:
    return {key: verify_group(reference, design, key) for key in GROUPS}


def _problems(entry: dict) -> list[str]:
    out = []
    if entry.get("q_plus_deg") is None or entry.get("q_minus_deg") is None:
        out.append("无法覆盖 ±35° 车轮转角")
    gain = abs(entry.get("gain_rad_per_rad") or 0.0)
    if not 0.4 <= gain <= 3.5:
        out.append(f"传动比 {gain:.3f} 超出 [0.4, 3.5]")
    if (entry.get("min_toggle_margin_deg") or 0.0) < MIN_TOGGLE_MARGIN_DEG:
        out.append(f"传动角余量 {entry.get('min_toggle_margin_deg', 0.0):.1f}° "
                   f"< {MIN_TOGGLE_MARGIN_DEG}°")
    return out


def scan(reference) -> int:
    for key in GROUPS:
        best = None
        for arm in (0.22, 0.28, 0.34, 0.42):
            for offset in (0.03, 0.07, 0.12, 0.20):
                for link in (0.26, 0.36, 0.48, 0.64):
                    for radius in (0.16, 0.24, 0.32):
                        trial = {k: dict(PARAMS[k]) for k in GROUPS}
                        trial[key] = {"arm_length": arm, "rack_offset": offset,
                                      "link_length": link, "swing_radius": radius}
                        try:
                            entry = verify_group(reference, build(reference, trial), key)
                        except Exception:
                            continue
                        problems = _problems(entry)
                        score = float(entry.get("min_toggle_margin_deg") or 0.0)
                        if entry.get("q_plus_deg") is None or                                 entry.get("q_minus_deg") is None:
                            score -= 500.0
                        gain = abs(entry.get("gain_rad_per_rad") or 0.0)
                        if not 0.4 <= gain <= 3.5:
                            score -= 100.0
                        if best is None or score > best[0]:
                            best = (score, trial[key], entry, problems)
        if best is None or best[3]:
            print(f"{key}: 未找到合格尺寸；最好 {best}")
        else:
            PARAMS[key] = best[1]
            entry = best[2]
            print(f"{key}: {best[1]}  传动角余量 {best[0]:.2f}度  "
                  f"摆臂角 [{entry['q_minus_deg']:.1f}, {entry['q_plus_deg']:.1f}]度  "
                  f"传动比 {entry['gain_rad_per_rad']:.3f}  "
                  f"齿条行程 {entry['max_rack_slide_m'] * 1000:.1f} mm")
    print("PARAMS =", json.dumps(PARAMS, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "configs" / "j1"
                                             / "engineering_mechanism.json"))
    parser.add_argument("--scan", action="store_true")
    args = parser.parse_args()
    reference = reference_geometry_from_file(SPEC)
    if args.scan:
        return scan(reference)
    design = build(reference)
    report = verify(reference, design)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    bad = {key: value for key, value in
           ((k, _problems(v)) for k, v in report.items()) if value}
    if bad:
        print("设计不合格：", json.dumps(bad, ensure_ascii=False))
        return 1
    save_design(design, args.out)
    print("written:", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
