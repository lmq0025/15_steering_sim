"""PHASE J1：``ENGINEERING_STEERING_MODEL`` 机械传动（齿条式 + 转向梯形）。

唯一正式机械模型的运动学内核。**每个机构组都是闭式可解的**（没有最小二乘、
没有数值优化、没有装配分支搜索），因此快、连续、可逆，也不会出现 M3 那种
"目标角 21°→22° 车轮跳几十度"。

传动原理（每组一套，四组同构）
------------------------------

    ┌────────────┐   甲方液压缸    ┌────────────┐
    │ 甲方摆臂    │◀──────────────│ 甲方机架点  │
    │ (甲方枢轴)  │                └────────────┘
    └─────┬──────┘
          │ 新设计拉杆
          ▼
    ┌────────────┐   新设计齿条（沿 y 平动）
    │  齿条 RACK  │
    └──┬──────┬──┘
       │      │  两根新设计边拉杆
       ▼      ▼
    ┌──────┐ ┌──────┐
    │左转向节│ │右转向节│   ← 甲方主销坐标不动
    └──────┘ └──────┘

* **甲方几何全部保留**：转向节主销（车轮中心）、摆臂枢轴、液压缸机架点与活塞
  杆安装点，一个都没有改。
* **新增**：摆臂上的拉杆拾取点、齿条（一个沿 y 平动的刚体，带若干球头点）、
  转向节上的转向臂端点 —— 全部是 ``ENGINEERING_DESIGN_ASSUMPTION``。
* **阿克曼差动由转向梯形本身产生**：左右转向臂指向共同瞬时转向中心，
  齿条平动时左右转向节转角自然不同（内侧轮多转），不是显示层做差。
* 前组（一、二桥）两桥各有一根齿条，用一根**中间拉杆**把两根齿条耦合成
  1:1 同步；一桥主动、二桥随动。

闭式求解
--------

给定摆臂角 θ_s：

1. 齿条位移 s 由「摆臂拾取点 ↔ 齿条驱动点」定长约束给出 —— 一元二次；
2. 每个转向节角 θ 由「齿条端 ↔ 转向臂端点」定长约束给出 —— 一元三角方程
   ``cos(θ + φ_v − φ_u) = c/|v|``，两个装配根，从零位连续跟随最近根。

所有角度都是相对零位的转角增量（rad，+Z 逆时针为正）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from pathlib import Path
from typing import Mapping

import numpy as np

WHEEL_ORDER = tuple(f"axle{axle}_{side}" for axle in range(1, 7)
                    for side in ("left", "right"))
LEGACY_SIDE = {"left": "POS_Y", "right": "NEG_Y"}
REAR_AXLES = (4, 5, 6)
GROUPS = ("front", "axle4", "axle5", "axle6")
DOF_OF_GROUP = {"front": "q_front", "axle4": "q4", "axle5": "q5", "axle6": "q6"}
GROUP_OF_AXLE = {1: "front", 2: "front", 3: "front", 4: "axle4", 5: "axle5",
                 6: "axle6"}
DOF_ORDER = ("q_front", "q4", "q5", "q6")
FRONT_CYLINDER = "front_group_1"

TAG = "ENGINEERING_STEERING_MODEL"
ASSUMPTION_TAG = "ENGINEERING_DESIGN_ASSUMPTION"


class MechanismError(RuntimeError):
    """机构在该构型下无解（超出可达范围）。"""


def _rot(angle: float) -> np.ndarray:
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[c, -s], [s, c]])


def _unit(angle: float) -> np.ndarray:
    return np.array([math.cos(angle), math.sin(angle)])


# ------------------------------------------------------------------ 设计参数
@dataclass(frozen=True, slots=True)
class SideDesign:
    """一侧的新设计点（零位全局坐标 m）。"""

    arm_tip: tuple[float, float]        # 转向节转向臂端点 K
    swing_pickup: tuple[float, float]   # 摆臂上的拉杆拾取点（前组/各后桥）
    rack_end: tuple[float, float]       # 齿条端球头点（零位）

    def to_dict(self) -> dict:
        return {"arm_tip": list(self.arm_tip),
                "swing_pickup": list(self.swing_pickup),
                "rack_end": list(self.rack_end)}


@dataclass(frozen=True, slots=True)
class GroupDesign:
    key: str
    axles: tuple[int, ...]
    #: 主动摆臂所在的桥（前组 = 一桥）。
    driven_axle: int
    #: 摆臂角 → 齿条位移的驱动连杆（摆臂拾取点 ↔ 齿条驱动点）。
    rack_drive_point: tuple[float, float]
    racks: Mapping[int, float]          # 桥 → 该桥齿条的 x（平动沿 +y）
    sides: Mapping[str, SideDesign]     # "axle{桥}_{side}" → 设计点
    relay: tuple[tuple[float, float], tuple[float, float]] | None = None
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "key": self.key, "axles": list(self.axles),
            "driven_axle": self.driven_axle,
            "rack_drive_point": list(self.rack_drive_point),
            "racks": {str(axle): float(x) for axle, x in sorted(self.racks.items())},
            "sides": {name: design.to_dict() for name, design in sorted(self.sides.items())},
            "relay": None if self.relay is None
            else [list(self.relay[0]), list(self.relay[1])],
            "notes": list(self.notes),
        }


@dataclass(frozen=True, slots=True)
class EngineeringDesign:
    schema_version: str
    tag: str
    groups: Mapping[str, GroupDesign]
    assumptions: tuple[str, ...] = ()
    provenance: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"schema_version": self.schema_version, "tag": self.tag,
                "assumptions": list(self.assumptions),
                "provenance": dict(self.provenance),
                "groups": {key: design.to_dict() for key, design in self.groups.items()}}


def load_design(path: str | Path) -> EngineeringDesign:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if raw.get("schema_version") != "J1.0":
        raise MechanismError("不支持的 J1 机构设计文件版本")
    groups: dict[str, GroupDesign] = {}
    for key, item in raw["groups"].items():
        sides = {name: SideDesign(tuple(map(float, s["arm_tip"])),
                                  tuple(map(float, s["swing_pickup"])),
                                  tuple(map(float, s["rack_end"])))
                 for name, s in item["sides"].items()}
        relay = item.get("relay")
        groups[key] = GroupDesign(
            key=key, axles=tuple(int(v) for v in item["axles"]),
            driven_axle=int(item["driven_axle"]),
            rack_drive_point=tuple(map(float, item["rack_drive_point"])),
            racks={int(k): float(v) for k, v in item["racks"].items()},
            sides=sides,
            relay=None if relay is None else (tuple(map(float, relay[0])),
                                              tuple(map(float, relay[1]))),
            notes=tuple(item.get("notes", ())))
    return EngineeringDesign(schema_version="J1.0", tag=str(raw["tag"]),
                             groups=groups,
                             assumptions=tuple(raw.get("assumptions", ())),
                             provenance=dict(raw.get("provenance", {})))


def save_design(design: EngineeringDesign, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(design.to_dict(), ensure_ascii=False, indent=2),
                      encoding="utf-8")
    return target


# ------------------------------------------------------------------ 机构求解
@dataclass(frozen=True, slots=True)
class GroupState:
    key: str
    swing_angle_rad: float
    rack_slide_m: Mapping[int, float]
    wheel_angles_rad: Mapping[str, float]
    residual_m: float


def _knuckle_angle(pivot: np.ndarray, arm_local: np.ndarray, target_point: np.ndarray,
                   link_length: float, previous: float) -> float:
    """由 |pivot + R(θ)·arm_local − target| = link_length 解 θ（闭式，两解取近根）。"""
    norm = float(np.linalg.norm(arm_local))
    if norm <= 1.0e-12:
        raise MechanismError("转向臂长度为零")
    v = target_point - pivot
    v_norm = float(np.linalg.norm(v))
    if v_norm <= 1.0e-12:
        raise MechanismError("齿条端与主销重合")
    cos_value = (norm * norm + v_norm * v_norm - link_length * link_length) / \
        (2.0 * norm * v_norm)
    if abs(cos_value) > 1.0 + 1.0e-12:
        raise MechanismError(
            f"连杆长度不可达（cos={cos_value:.6f}）；该构型超出机构可达范围")
    cos_value = max(-1.0, min(1.0, cos_value))
    phi_u = math.atan2(arm_local[1], arm_local[0])
    phi_v = math.atan2(v[1], v[0])
    delta = math.acos(cos_value)
    # |R(θ)u − v|² = |u|² + |v|² − 2|u||v|cos(φ_u + θ − φ_v) = L²
    #   ⇒ θ = φ_v − φ_u ± acos(...)
    base = phi_v - phi_u
    return _nearest_branch(base + delta, base - delta, previous)


def _nearest_branch(a: float, b: float, previous: float) -> float:
    def wrap(value: float) -> float:
        return (value + math.pi) % (2.0 * math.pi) - math.pi

    return wrap(a) if abs(wrap(a) - previous) <= abs(wrap(b) - previous) else wrap(b)


class EngineeringMechanism:
    """四组齿条式转向机构：摆臂角 → 十二轮转角。"""

    def __init__(self, reference, design: EngineeringDesign) -> None:
        self.reference = reference
        self.design = design
        self.centers = {}
        for axle in range(1, 7):
            for side, legacy in LEGACY_SIDE.items():
                pivot = reference.bodies[f"WHEEL_{axle}_{legacy}"].pivot
                self.centers[f"axle{axle}_{side}"] = (float(pivot[0]), float(pivot[1]))
        self._link_lengths: dict[str, dict[str, float]] = {}
        self._prepare()
        self._previous = {key: 0.0 for key in GROUPS}
        self._previous_swing = {key: 0.0 for key in GROUPS}
        self._previous_rack = {key: {axle: 0.0 for axle in self.design.groups[key].axles}
                               for key in GROUPS}

    # ------------------------------------------------------------- 预计算
    def _prepare(self) -> None:
        for key in GROUPS:
            group = self.design.groups[key]
            lengths: dict[str, float] = {}
            # 驱动连杆：摆臂拾取点（零位）↔ 齿条驱动点
            pickup = group.sides[self._side_name(group.driven_axle, "right")].swing_pickup
            lengths["drive"] = float(np.linalg.norm(
                np.asarray(group.rack_drive_point, dtype=float)
                - np.asarray(pickup, dtype=float)))
            # 每根边拉杆
            for axle in group.axles:
                for side in ("left", "right"):
                    name = self._side_name(axle, side)
                    design = group.sides[name]
                    lengths[name] = float(np.linalg.norm(
                        np.asarray(design.rack_end, dtype=float)
                        - np.asarray(design.arm_tip, dtype=float)))
            if group.relay is not None:
                a = np.asarray(group.relay[0], dtype=float)
                b = np.asarray(group.relay[1], dtype=float)
                lengths["relay"] = float(np.linalg.norm(b - a))
            self._link_lengths[key] = lengths

    @staticmethod
    def _side_name(axle: int, side: str) -> str:
        return f"axle{axle}_{side}"

    # ------------------------------------------------------------- 正解
    def solve_swing(self, key: str, swing_angle_rad: float) -> GroupState:
        group = self.design.groups[key]
        lengths = self._link_lengths[key]
        # 1) 齿条位移由驱动连杆给出
        axle0 = group.driven_axle
        pickup0 = np.asarray(group.sides[self._side_name(axle0, "right")].swing_pickup,
                             dtype=float)
        pivot0 = np.asarray(self.reference.bodies[
            f"SWING_{axle0}_NEG_Y"].pivot, dtype=float)
        arm0 = pickup0 - pivot0
        swing_point = pivot0 + _rot(swing_angle_rad) @ arm0
        drive_point = np.asarray(group.rack_drive_point, dtype=float)
        dx = drive_point[0] - swing_point[0]
        dy = drive_point[1] - swing_point[1]
        radicand = lengths["drive"] ** 2 - dx * dx
        if radicand < -1.0e-12:
            raise MechanismError(
                f"{key}: 摆臂转角 {math.degrees(swing_angle_rad):.3f}° 超出驱动连杆可达范围")
        root = math.sqrt(max(0.0, radicand))
        previous = self._previous_rack[key].get(axle0, 0.0)
        # |(x_r, y_d + s) − S| = L  ⇒  s = (S_y − y_d) ± root
        slide = _nearest_branch_free(-dy + root, -dy - root, previous)
        slides = {axle: slide for axle in group.axles}
        if group.relay is not None:
            # 两根齿条都用中间拉杆耦合（一桥主动、二桥随动）：
            # (x_b − x_a)² + (D + s_b − s_a)² = L²，D = y_b0 − y_a0
            axle_a, axle_b = group.axles[0], group.axles[1]
            a_r = np.asarray(group.relay[0], dtype=float)
            b_r = np.asarray(group.relay[1], dtype=float)
            radicand_relay = lengths["relay"] ** 2 - (b_r[0] - a_r[0]) ** 2
            if radicand_relay < -1.0e-12:
                raise MechanismError(f"{key}: 中间拉杆不可达")
            root_relay = math.sqrt(max(0.0, radicand_relay))
            base = slides[axle_a] + (a_r[1] - b_r[1])
            slides[axle_b] = _nearest_branch_free(
                base + root_relay, base - root_relay,
                self._previous_rack[key].get(axle_b, 0.0))
        # 2) 每个转向节由各自边拉杆给出
        angles: dict[str, float] = {}
        residual = 0.0
        for axle in group.axles:
            for side in ("left", "right"):
                name = self._side_name(axle, side)
                design = group.sides[name]
                pivot = np.asarray(self.reference.bodies[
                    f"WHEEL_{axle}_{LEGACY_SIDE[side]}"].pivot, dtype=float)
                arm_local = np.asarray(design.arm_tip, dtype=float) - pivot
                rack_x = group.racks[axle]
                end = np.array([rack_x, design.rack_end[1] + slides[axle]])
                theta = _knuckle_angle(pivot, arm_local, end, lengths[name],
                                       self._previous.get(name, 0.0))
                angles[f"axle{axle}_{side}"] = theta
                tip = pivot + _rot(theta) @ arm_local
                residual = max(residual, abs(float(np.linalg.norm(tip - end))
                                             - lengths[name]))
        for axle in (3,):
            angles[f"axle{axle}_left"] = 0.0
            angles[f"axle{axle}_right"] = 0.0
        self._previous.update(angles)
        self._previous_swing[key] = float(swing_angle_rad)
        self._previous_rack[key] = dict(slides)
        return GroupState(key=key, swing_angle_rad=float(swing_angle_rad),
                          rack_slide_m=dict(slides), wheel_angles_rad=angles,
                          residual_m=residual)

    def solve_continuous(self, key: str, q_rad: float,
                         step_rad: float = math.radians(1.0)) -> GroupState:
        """连续求解：与上一次构型相差不大时直接解，否则从零位小步走过去。

        ``solve_swing`` 的装配根是"离上一步最近"的那个；若上一步停留在别的构型
        （例如刚扫完机构表），直接跳过去可能选到另一个残差同样合格、物理上完全
        不同的构型。这里保证任何一次求解都跟在**从零位连续延展出来的同一分支**上。
        """
        q_rad = float(q_rad)
        if abs(q_rad - self._previous_swing.get(key, 0.0)) <= step_rad:
            return self.solve_swing(key, q_rad)
        self.reset_group(key, 0.0)
        self.solve_swing(key, 0.0)
        count = max(1, int(math.ceil(abs(q_rad) / step_rad)))
        state = None
        for index in range(1, count + 1):
            state = self.solve_swing(key, q_rad * index / count)
        assert state is not None
        return state

    def solve(self, q_values: Mapping[str, float]) -> dict[str, GroupState]:
        return {key: self.solve_continuous(key, float(q_values[DOF_OF_GROUP[key]]))
                for key in GROUPS}

    def reset(self) -> None:
        self._previous = {key: 0.0 for key in GROUPS}
        self._previous_swing = {key: 0.0 for key in GROUPS}
        self._previous_rack = {key: {axle: 0.0 for axle in self.design.groups[key].axles}
                               for key in GROUPS}

    # ------------------------------------------------------- 组的传动比
    def rack_jacobian(self, key: str, swing_angle_rad: float,
                      delta: float = 1.0e-5) -> dict[int, float]:
        group = self.design.groups[key]
        up = self.solve_swing(key, swing_angle_rad + delta)
        self.reset_group(key, swing_angle_rad)
        down = self.solve_swing(key, swing_angle_rad - delta)
        self.reset_group(key, swing_angle_rad)
        return {axle: (up.rack_slide_m[axle] - down.rack_slide_m[axle]) / (2 * delta)
                for axle in group.axles}

    def reset_group(self, key: str, swing_angle_rad: float) -> None:
        """把该组的装配分支状态复位到指定构型（避免连续差分被上一状态污染）。"""
        self._previous = {k: 0.0 for k in GROUPS}
        self._previous_rack[key] = {axle: 0.0 for axle in self.design.groups[key].axles}
        self.solve_swing(key, swing_angle_rad)


def _nearest_branch_free(a: float, b: float, previous: float) -> float:
    """两个候选标量解，取离上一步最近的那个（无角度回绕）。"""
    return a if abs(a - previous) <= abs(b - previous) else b
