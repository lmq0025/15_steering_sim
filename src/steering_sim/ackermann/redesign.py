"""PHASE M3：``REDESIGNED_ACKERMANN_TRANSMISSION`` —— 六桥阿克曼转向重新设计机构。

背景（PHASE M2 已确认的事实）
------------------------------

甲方四、五、六桥的"摆臂—长边拉杆—车轮"四杆机构里，五、六桥距死点只有
9.69°/6.57°（一、二、四桥为 76~85°），零位传动比 −0.034/+0.291。直接后果是
五桥右轮可达角范围只有 [−0.007°, +13.104°]、六桥右轮 [−0.314°, +7.861°]，
**左轮镜像**，因此不存在"同桥左右轮同向"的装配构型，机构无法实现阿克曼反相
转向。根因是长边拉杆（2.49 m / 3.38 m）与转向节摇臂（0.378 m）在零位几乎平行
——四杆处在接近"完全伸展"的死点构型。

本模块做什么
------------

在不改动甲方任何原始铰点坐标、杆长与液压缸安装点的前提下，**增加中间摇臂
（relay rocker）与转向梯形（steering trapezoid）**，重新建立
"液压缸行程 → 摆臂角度 → 车轮转角"的关系：

    ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
    │ 甲方摆臂      │──▶│ 新设计中间摇臂 │──▶│ 甲方转向节    │
    │ (甲方枢轴/缸) │拉杆│ (新机架枢轴)  │拉杆│ (甲方主销)    │
    └──────────────┘   └──────────────┘   └──────┬───────┘
                                                   │ 新设计转向梯形
                                            同桥另一侧转向节

* **保留**：摆臂枢轴与臂长、液压缸机架点与活塞杆点、转向节主销、
  轮胎中心、轴距轮距——全部为甲方原始值；
* **新增**：中间摇臂枢轴、摇臂输入/输出臂端点、转向节转向臂端点，
  以及由这些点定长的新拉杆。这些是**工程新设计点**，逐条标注为
  ``ENGINEERING_REDESIGN_PROPOSAL``，不是甲方实测硬点；
* 转向梯形落在**两个转向节之间**（一桥、二桥各一组），而不是甲方原来的
  摆臂之间横拉杆，因此"同桥左右轮的阿克曼差动关系"真正由机构产生。

零位的定义与甲方一致：所有构件在 ``q = 0`` 时的转角为 0，十二轮转角为 0。
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

import numpy as np

from .planar import (PlanarChainError, PlanarClosedChain, build_bodies,
                     build_link, toggle_margin_deg)

#: 机构模式标签。所有新机构结果一律带此标签，绝不冒充甲方实测结构。
REDESIGN_TAG = "ENGINEERING_REDESIGN_PROPOSAL"
#: 甲方原始结构的标签（用于对照）。
AS_BUILT_TAG = "CUSTOMER_AS_BUILT_LINKAGE"

WHEEL_ORDER = tuple(f"axle{axle}_{side}" for axle in range(1, 7)
                    for side in ("left", "right"))
LEGACY_SIDE = {"left": "POS_Y", "right": "NEG_Y"}
REAR_AXLES = (4, 5, 6)
GROUP_OF_AXLE = {1: "front", 2: "front", 3: "front", 4: "axle4", 5: "axle5",
                 6: "axle6"}
#: 每个机构组对应的 J0 通道。
CHANNEL_OF_GROUP = {"front": "channel_front", "axle4": "channel_rear_1",
                    "axle5": "channel_rear_2", "axle6": "channel_rear_3"}
DOF_OF_GROUP = {"front": "q_front", "axle4": "q4", "axle5": "q5", "axle6": "q6"}
#: 前组等效缸的固定名称（甲方未提供前组缸硬点，接口为占位）。
FRONT_CYLINDER = "front_group_1"

#: 摆臂上用作"新拉杆"端的甲方拾取点（甲方原始边拉杆端，坐标不改）。
DRAG_PICKUP = {
    "front1": "P04", "front2": "P10",
    "axle4": "P26", "axle5": "P34", "axle6": "P42",
}
#: 甲方摆臂上的"横拉杆"拾取点，本次设计中不再使用（保留坐标，仅停用连杆）。
RETIRED_PICKUP = {"axle4": "P25", "axle5": "P33", "axle6": "P41",
                  "front1": "P01", "front2": "P17"}

DESIGN_SCHEMA = "M3.0"


def mirror_body_name(name: str) -> str:
    """左右互换的刚体名（机构按构造严格镜像）。"""
    if name.endswith("_NEG_Y"):
        return name[:-6] + "_POS_Y"
    if name.endswith("_POS_Y"):
        return name[:-6] + "_NEG_Y"
    return name


def mirror_angles(angles: Mapping[str, float]) -> dict[str, float]:
    """把一套构件角镜像到车辆另一侧：刚体左右互换，转角取反。

    机构的所有新设计点都是按 ``(x, −y)`` 镜像给出的，坐标约束又是
    ``mean(θ_SWING_N, θ_SWING_P) = q``，所以镜像后的构型恰好对应 ``−q``。
    这是**恒等式**，可以用来构造负半轴，避免在数值分支跟踪上碰碰运气。
    """
    return {mirror_body_name(name): -float(value)
            for name, value in angles.items()}


class RedesignError(RuntimeError):
    pass


# --------------------------------------------------------------- 设计参数
@dataclass(frozen=True, slots=True)
class RelayDesign:
    """一侧中间摇臂的新设计点（零位全局坐标，单位 m）。"""

    pivot: tuple[float, float]
    input_tip: tuple[float, float]
    output_tip: tuple[float, float]

    def mirrored(self) -> "RelayDesign":
        return RelayDesign((self.pivot[0], -self.pivot[1]),
                           (self.input_tip[0], -self.input_tip[1]),
                           (self.output_tip[0], -self.output_tip[1]))

    def to_dict(self) -> dict:
        return {"pivot": list(self.pivot), "input_tip": list(self.input_tip),
                "output_tip": list(self.output_tip)}

    @staticmethod
    def from_dict(raw: Mapping) -> "RelayDesign":
        return RelayDesign(tuple(map(float, raw["pivot"])),
                           tuple(map(float, raw["input_tip"])),
                           tuple(map(float, raw["output_tip"])))


@dataclass(frozen=True, slots=True)
class GroupDesign:
    """一个机构组的新设计参数（右侧 ``NEG_Y`` 的坐标，左侧镜像）。"""

    key: str
    axles: tuple[int, ...]
    relays: Mapping[int, RelayDesign]
    knuckle_tips: Mapping[int, tuple[float, float]]
    #: 摆臂上的**新设计**拉杆拾取点（右侧零位全局坐标）；缺省时退回甲方原始拾取点。
    swing_pickups: Mapping[int, tuple[float, float]] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "key": self.key, "axles": list(self.axles),
            "relays": {str(axle): design.to_dict()
                       for axle, design in sorted(self.relays.items())},
            "knuckle_tips": {str(axle): list(tip)
                             for axle, tip in sorted(self.knuckle_tips.items())},
            "swing_pickups": {str(axle): list(point)
                              for axle, point in sorted(self.swing_pickups.items())},
            "notes": list(self.notes),
        }

    @staticmethod
    def from_dict(raw: Mapping) -> "GroupDesign":
        return GroupDesign(
            key=str(raw["key"]),
            axles=tuple(int(value) for value in raw["axles"]),
            relays={int(axle): RelayDesign.from_dict(item)
                    for axle, item in raw["relays"].items()},
            knuckle_tips={int(axle): tuple(map(float, tip))
                          for axle, tip in raw["knuckle_tips"].items()},
            swing_pickups={int(axle): tuple(map(float, point))
                           for axle, point in raw.get("swing_pickups", {}).items()},
            notes=tuple(str(value) for value in raw.get("notes", ())),
        )


@dataclass(frozen=True, slots=True)
class RedesignParameters:
    schema_version: str
    tag: str
    groups: Mapping[str, GroupDesign]
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "tag": self.tag,
            "provenance": dict(self.provenance),
            "groups": {key: design.to_dict() for key, design in self.groups.items()},
        }

    @staticmethod
    def from_dict(raw: Mapping) -> "RedesignParameters":
        if str(raw.get("schema_version")) != DESIGN_SCHEMA:
            raise RedesignError("不支持的新机构设计参数版本")
        return RedesignParameters(
            schema_version=DESIGN_SCHEMA, tag=str(raw["tag"]),
            groups={key: GroupDesign.from_dict(item)
                    for key, item in raw["groups"].items()},
            provenance=dict(raw.get("provenance", {})))


def load_redesign_parameters(path: str | Path) -> RedesignParameters:
    return RedesignParameters.from_dict(
        json.loads(Path(path).read_text(encoding="utf-8")))


def save_redesign_parameters(parameters: RedesignParameters, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(parameters.to_dict(), ensure_ascii=False, indent=2),
                      encoding="utf-8")
    return target


# ------------------------------------------------------------- 机构构造
@dataclass(slots=True)
class _GroupBuild:
    chain: PlanarClosedChain
    wheels: Mapping[str, str]          # 刚体名 → 公开轮名
    wheel_owner: Mapping[str, str]     # 公开轮名 → 刚体名
    links: Mapping[str, tuple[tuple[str, str], tuple[str, str]]]


def _customer_point_id(pickup: str, side: str) -> str:
    """甲方硬点编号 → 该侧刚体上的局部硬点编号（右 = ``_SRC``，左 = ``_MIRROR``）。"""
    return f"{pickup}_{'SRC' if side == 'right' else 'MIRROR'}"


def _mirror(point: tuple[float, float]) -> tuple[float, float]:
    return (float(point[0]), -float(point[1]))


def _customer_body_points(reference, body_name: str) -> dict[str, tuple[float, float]]:
    body = reference.bodies[body_name]
    pivot = body.pivot
    return {point_id: (float(pivot[0]) + float(local[0]),
                       float(pivot[1]) + float(local[1]))
            for point_id, local in body.local_hardpoints.items()}


def build_group_chains(reference, parameters: RedesignParameters
                       ) -> dict[str, _GroupBuild]:
    """按新设计参数构造四个 1-DOF 平面闭链组。"""
    builds: dict[str, _GroupBuild] = {}
    for key in ("front", "axle4", "axle5", "axle6"):
        design = parameters.groups.get(key)
        if design is None:
            raise RedesignError(f"缺少机构组设计参数：{key}")
        if key == "front":
            builds[key] = _build_front_group(reference, design)
        else:
            builds[key] = _build_rear_group(reference, design)
    return builds


def _relay_body(name: str, design: RelayDesign) -> tuple[dict, dict]:
    pivots = {name: design.pivot}
    hardpoints = {name: {"IN": design.input_tip, "OUT": design.output_tip}}
    return pivots, hardpoints


def _build_rear_group(reference, design: GroupDesign) -> _GroupBuild:
    if len(design.axles) != 1:
        raise RedesignError(f"{design.key}: 后桥组必须只含一个桥")
    axle = design.axles[0]
    relay = design.relays[axle]
    knuckle_tip = design.knuckle_tips[axle]
    pickup = DRAG_PICKUP[design.key]

    pivots: dict[str, tuple[float, float]] = {}
    hardpoints: dict[str, dict[str, tuple[float, float]]] = {}
    new_pickup = design.swing_pickups.get(axle)
    pickup_id = "SWNEW" if new_pickup is not None else pickup
    for side in ("right", "left"):
        legacy = LEGACY_SIDE[side]
        swing = f"SWING_{axle}_{legacy}"
        wheel = f"WHEEL_{axle}_{legacy}"
        relay_body = f"RELAY_{axle}_{legacy}"
        points = _customer_body_points(reference, swing)
        pivots[swing] = tuple(map(float, reference.bodies[swing].pivot))
        hardpoints[swing] = ({
            f"{pickup_id}_{legacy}": (tuple(new_pickup) if side == "right"
                                      else _mirror(tuple(new_pickup)))
        } if new_pickup is not None
            else {f"{pickup_id}_{legacy}":
                  points[_customer_point_id(pickup, side)]})
        pivots[wheel] = tuple(map(float, reference.bodies[wheel].pivot))
        tip = knuckle_tip if side == "right" else _mirror(knuckle_tip)
        hardpoints[wheel] = {"K": tip}
        relay_design = relay if side == "right" else relay.mirrored()
        relay_points, relay_hp = _relay_body(relay_body, relay_design)
        pivots.update(relay_points)
        hardpoints.update(relay_hp)

    bodies = build_bodies(pivots, hardpoints)
    link_specs = {
        "DRAG_R": ((f"SWING_{axle}_NEG_Y", f"{pickup_id}_NEG_Y"),
                   (f"RELAY_{axle}_NEG_Y", "IN")),
        "DRAG_L": ((f"SWING_{axle}_POS_Y", f"{pickup_id}_POS_Y"),
                   (f"RELAY_{axle}_POS_Y", "IN")),
        # 用输出臂端点作为第一端，使"中间摇臂输出臂"承担摇杆角色，
        # 转向节转向臂承担曲柄角色，便于直接读传动角。
        "SIDE_R": ((f"RELAY_{axle}_NEG_Y", "OUT"), (f"WHEEL_{axle}_NEG_Y", "K")),
        "SIDE_L": ((f"RELAY_{axle}_POS_Y", "OUT"), (f"WHEEL_{axle}_POS_Y", "K")),
        "TRAPEZOID": ((f"WHEEL_{axle}_NEG_Y", "K"), (f"WHEEL_{axle}_POS_Y", "K")),
    }
    links = {name: build_link(name, a, b, bodies) for name, (a, b) in link_specs.items()}
    chain = PlanarClosedChain(
        name=f"{design.key.upper()}", bodies=list(bodies.values()),
        links=list(links.values()),
        coordinate_bodies=(f"SWING_{axle}_NEG_Y", f"SWING_{axle}_POS_Y"))
    wheels = {f"WHEEL_{axle}_{LEGACY_SIDE[side]}": f"axle{axle}_{side}"
              for side in ("left", "right")}
    return _GroupBuild(chain=chain, wheels=wheels,
                       wheel_owner={value: key_ for key_, value in wheels.items()},
                       links=MappingProxyType(dict(link_specs)))


def _build_front_group(reference, design: GroupDesign) -> _GroupBuild:
    """前组：一桥用"中间摇臂 + 转向梯形"，二桥保留甲方长拉杆/边拉杆链。"""
    relay = design.relays[1]
    tip1 = design.knuckle_tips[1]
    tip2 = design.knuckle_tips[2]
    pickup1, pickup2 = DRAG_PICKUP["front1"], DRAG_PICKUP["front2"]

    new1 = design.swing_pickups.get(1)
    new2 = design.swing_pickups.get(2)
    id1 = "SWNEW1" if new1 is not None else pickup1
    id2 = "SWNEW2" if new2 is not None else pickup2

    pivots: dict[str, tuple[float, float]] = {}
    hardpoints: dict[str, dict[str, tuple[float, float]]] = {}
    for side in ("right", "left"):
        legacy = LEGACY_SIDE[side]
        for axle in (1, 2):
            swing = f"SWING_{axle}_{legacy}"
            wheel = f"WHEEL_{axle}_{legacy}"
            pivots[swing] = tuple(map(float, reference.bodies[swing].pivot))
            pivots[wheel] = tuple(map(float, reference.bodies[wheel].pivot))
            customer = _customer_body_points(reference, swing)
            hardpoints[swing] = {}
            if axle == 1:
                if new1 is None:
                    hardpoints[swing][f"{id1}_{legacy}"] =                         customer[_customer_point_id(pickup1, side)]
                elif side == "right":
                    hardpoints[swing][f"{id1}_{legacy}"] = tuple(new1)
                else:
                    hardpoints[swing][f"{id1}_{legacy}"] = _mirror(tuple(new1))
                # 甲方长拉杆 P03 端保留（跨一、二桥的耦合杆）。
                hardpoints[swing][f"P03_{legacy}"] =                     customer[_customer_point_id("P03", side)]
            else:
                if new2 is None:
                    hardpoints[swing][f"{id2}_{legacy}"] =                         customer[_customer_point_id(pickup2, side)]
                elif side == "right":
                    hardpoints[swing][f"{id2}_{legacy}"] = tuple(new2)
                else:
                    hardpoints[swing][f"{id2}_{legacy}"] = _mirror(tuple(new2))
                hardpoints[swing][f"P09_{legacy}"] =                     customer[_customer_point_id("P09", side)]
            tip = (tip1 if axle == 1 else tip2)
            hardpoints[wheel] = {"K": tip if side == "right" else _mirror(tip)}
        relay_points, relay_hp = _relay_body(
            f"RELAY_1_{legacy}", relay if side == "right" else relay.mirrored())
        pivots.update(relay_points)
        hardpoints.update(relay_hp)

    bodies = build_bodies(pivots, hardpoints)
    link_specs = {
        "DRAG_1_R": (("SWING_1_NEG_Y", f"{id1}_NEG_Y"), ("RELAY_1_NEG_Y", "IN")),
        "DRAG_1_L": (("SWING_1_POS_Y", f"{id1}_POS_Y"), ("RELAY_1_POS_Y", "IN")),
        "SIDE_1_R": (("RELAY_1_NEG_Y", "OUT"), ("WHEEL_1_NEG_Y", "K")),
        "SIDE_1_L": (("RELAY_1_POS_Y", "OUT"), ("WHEEL_1_POS_Y", "K")),
        "TRAPEZOID_1": (("WHEEL_1_NEG_Y", "K"), ("WHEEL_1_POS_Y", "K")),
        # 甲方原始长拉杆跨接一、二桥摆臂，坐标与杆长均保持不变。
        "LONG_12_R": (("SWING_1_NEG_Y", "P03_NEG_Y"), ("SWING_2_NEG_Y", "P09_NEG_Y")),
        "LONG_12_L": (("SWING_1_POS_Y", "P03_POS_Y"), ("SWING_2_POS_Y", "P09_POS_Y")),
        "SIDE_2_R": (("SWING_2_NEG_Y", f"{id2}_NEG_Y"), ("WHEEL_2_NEG_Y", "K")),
        "SIDE_2_L": (("SWING_2_POS_Y", f"{id2}_POS_Y"), ("WHEEL_2_POS_Y", "K")),
    }
    links = {name: build_link(name, a, b, bodies) for name, (a, b) in link_specs.items()}
    chain = PlanarClosedChain(
        name="FRONT", bodies=list(bodies.values()), links=list(links.values()),
        coordinate_bodies=("SWING_1_NEG_Y", "SWING_1_POS_Y"))
    wheels = {f"WHEEL_{axle}_{LEGACY_SIDE[side]}": f"axle{axle}_{side}"
              for axle in (1, 2) for side in ("left", "right")}
    return _GroupBuild(chain=chain, wheels=wheels,
                       wheel_owner={value: key_ for key_, value in wheels.items()},
                       links=MappingProxyType(dict(link_specs)))


# ------------------------------------------------------------- 机构求解
#: 连续延拓的最大单步（rad）。必须 ≤ ``PlanarClosedChain`` 的分支跳变判据
#: 生效区间（0.1 rad），否则"跳分支"会被静默放过。
CONTINUATION_STEP_RAD = 0.08


def solve_chain_continuation(chain: PlanarClosedChain, q_rad: float,
                             step_rad: float = CONTINUATION_STEP_RAD):
    """稳健求解：只有热启动**足够近**时才采用，否则从零位连续延拓过去。

    机构表的扫描会把链条的内部状态留在表的末端。若直接用它当热启动，
    ``least_squares``/牛顿可能收敛到**另一个装配分支**并给出一个残差同样合格、
    但物理上完全不同的构型（本阶段实测过：直行工况被解成 −242°）。因此只有
    ``|Δq| ≤ step_rad``（分支跳变判据仍然生效）时才走热启动快路，否则一律
    从零位以小步长走过去，保证任何一次求解都落在同一个装配分支上。
    """
    if abs(q_rad - chain.previous_q) <= step_rad:
        try:
            return chain.solve(q_rad)
        except PlanarChainError:
            pass
    chain.reset()
    chain.solve(0.0)
    count = max(1, int(math.ceil(abs(q_rad) / step_rad)))
    solution = None
    for index in range(1, count + 1):
        solution = chain.solve(q_rad * index / count)
    assert solution is not None
    return solution


@dataclass(frozen=True, slots=True)
class GroupState:
    key: str
    q_rad: float
    body_angles_rad: Mapping[str, float]
    wheel_angles_rad: Mapping[str, float]
    #: 对称双缸"推程缸"代表行程（m，相对零位）；见 :func:`representative_stroke_m`。
    representative_stroke_m: float
    residual_m: float
    condition_number: float
    toggle_margins_deg: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class MechanismState:
    q_rad: Mapping[str, float]
    wheel_angles_rad: Mapping[str, float]
    wheel_angles_deg: Mapping[str, float]
    max_residual_m: float
    max_condition_number: float
    min_toggle_margin_deg: float
    third_axle_max_abs_deg: float
    groups: Mapping[str, GroupState]


class RedesignedMechanism:
    """新设计机构的运动学：``q`` （四个机构坐标） → 十二轮转角。"""

    def __init__(self, reference, parameters: RedesignParameters) -> None:
        self.reference = reference
        self.parameters = parameters
        self.builds = build_group_chains(reference, parameters)
        self.group_order = ("front", "axle4", "axle5", "axle6")

    def reset(self) -> None:
        for build in self.builds.values():
            build.chain.reset()

    def solve(self, q_values: Mapping[str, float]) -> MechanismState:
        wheels: dict[str, float] = {}
        groups: dict[str, GroupState] = {}
        max_residual = 0.0
        max_condition = 0.0
        min_toggle = 180.0
        for key in self.group_order:
            build = self.builds[key]
            dof = DOF_OF_GROUP[key]
            solution = solve_chain_continuation(build.chain, float(q_values[dof]))
            max_residual = max(max_residual, solution.max_residual_m)
            max_condition = max(max_condition, solution.condition_number)
            margins = self._toggle_margins(build, solution)
            if margins:
                min_toggle = min(min_toggle, min(margins.values()))
            for body_name, wheel in build.wheels.items():
                wheels[wheel] = float(solution.angles_rad[body_name])
            representative = math.nan
            if key != "front":
                representative = representative_stroke_m(
                    self.reference, int(key[4:]), float(q_values[dof]),
                    solution.angles_rad)
            groups[key] = GroupState(
                key=key, q_rad=float(q_values[dof]),
                representative_stroke_m=representative,
                body_angles_rad=solution.angles_rad,
                wheel_angles_rad={build.wheels[name]: float(solution.angles_rad[name])
                                  for name in build.wheels},
                residual_m=solution.max_residual_m,
                condition_number=solution.condition_number,
                toggle_margins_deg=margins)
        for axle in (3,):
            wheels[f"axle{axle}_left"] = 0.0
            wheels[f"axle{axle}_right"] = 0.0
        return MechanismState(
            q_rad=dict(q_values), wheel_angles_rad=wheels,
            wheel_angles_deg={wheel: math.degrees(value)
                              for wheel, value in wheels.items()},
            max_residual_m=max_residual, max_condition_number=max_condition,
            min_toggle_margin_deg=min_toggle, third_axle_max_abs_deg=0.0,
            groups=groups)

    def _toggle_margins(self, build: _GroupBuild,
                        solution) -> dict[str, float]:
        """逐连杆给出"距死点"角度（度）。"""
        angles = solution.angles_rad
        margins: dict[str, float] = {}
        for name, (end_a, end_b) in build.links.items():
            if not name.startswith(("DRAG", "SIDE")):
                continue
            body_a, point_a = end_a
            body_b, point_b = end_b
            first = build.chain.bodies[build.chain.body_index[body_a]].world_point(
                point_a, angles[body_a])
            second = build.chain.bodies[build.chain.body_index[body_b]].world_point(
                point_b, angles[body_b])
            # 连杆相对"转动臂"的夹角：两端各取一次，保守地取较小者。
            pivot_a = np.asarray(build.chain.bodies[
                build.chain.body_index[body_a]].pivot, dtype=float)
            pivot_b = np.asarray(build.chain.bodies[
                build.chain.body_index[body_b]].pivot, dtype=float)
            values = []
            for anchor, pivot in ((first, pivot_a), (second, pivot_b)):
                other = second if anchor is first else first
                coupler = other - anchor
                arm = anchor - pivot
                if float(np.linalg.norm(arm)) <= 1.0e-12:
                    continue
                angle = math.degrees(math.atan2(coupler[1], coupler[0])
                                     - math.atan2(arm[1], arm[0]))
                values.append((angle + 180.0) % 360.0 - 180.0)
            if values:
                margins[name] = min(toggle_margin_deg(value) for value in values)
        return margins


# --------------------------------------------------------- 液压缸行程
def cylinder_stroke_m(reference, axle: int, side: str, swing_rad: float) -> float:
    """甲方液压缸在该摆臂角下的行程（相对零位，m）。

    甲方表中 ``ACTUATOR_{axle}_A`` 驱动 ``SWING_{axle}_NEG_Y``（右侧），
    ``_B`` 驱动 ``POS_Y``（左侧）。液压缸安装点、杆长、机架点全部为甲方原始值。
    """
    legacy = LEGACY_SIDE[side]
    name = f"ACTUATOR_{axle}_{'B' if legacy == 'POS_Y' else 'A'}"
    actuator = reference.actuators[name]
    fixed = np.asarray(reference.points[actuator.frame_point_id].position, dtype=float)
    body = reference.bodies[actuator.moving_body]
    moving_local = np.asarray(body.local_hardpoints[actuator.moving_point_id], dtype=float)
    pivot = np.asarray(body.pivot, dtype=float)
    c, s = math.cos(swing_rad), math.sin(swing_rad)
    moving = pivot + np.array([[c, -s], [s, c]]) @ moving_local
    zero = float(np.linalg.norm(fixed - (pivot + moving_local)))
    return float(np.linalg.norm(fixed - moving)) - zero


def representative_stroke_m(reference, axle: int, q_rad: float,
                            angles: Mapping[str, float]) -> float:
    """机构组的**代表行程**：对称双缸的"推程缸"位移（m，相对零位）。

    甲方每桥有 A、B 两只缸。左转（``q ≥ 0``）时 A 缸推程，右转（``q < 0``）时
    B 缸推程——这是对称双缸转向机构的常规做法，两只缸在同一液压回路中由同一
    通道驱动。这样定义出来的代表行程是**奇函数**：

        x(−q) = −stroke_B(−q) = −stroke_A(q)

    因此只要 A 缸行程在 ``q ≥ 0`` 上单调，代表行程就在整个区间上单调、连续、
    且关于零位对称。**若只用 A 缸**，实测它在 q≈−9° 处就到达了自己的运动极限
    （行程折返），会使六桥的右转向范围被腰斩——那是把"两只缸"当成"一只缸"用
    造成的假限制，不是机构本身的限制。

    两只缸的**真实几何行程**仍然逐只如实输出（七个物理缸接口不变），
    本函数只定义 J0 单通道用的等效坐标。
    """
    legacy = LEGACY_SIDE["right"]
    if q_rad >= 0.0:
        return cylinder_stroke_m(reference, axle, "right",
                                 float(angles[f"SWING_{axle}_{legacy}"]))
    return -cylinder_stroke_m(reference, axle, "left",
                              float(angles[f"SWING_{axle}_{LEGACY_SIDE['left']}"]))


def swing_angle_for_stroke(reference, axle: int, side: str, stroke_m: float) -> float:
    """行程反解摆臂角（二分法；摆臂角在有效区间内单调）。"""
    legacy = LEGACY_SIDE[side]
    name = f"ACTUATOR_{axle}_{'B' if legacy == 'POS_Y' else 'A'}"
    actuator = reference.actuators[name]
    fixed = np.asarray(reference.points[actuator.frame_point_id].position, dtype=float)
    body = reference.bodies[actuator.moving_body]
    moving_local = np.asarray(body.local_hardpoints[actuator.moving_point_id], dtype=float)
    pivot = np.asarray(body.pivot, dtype=float)
    zero = float(np.linalg.norm(fixed - (pivot + moving_local)))

    def value(angle: float) -> float:
        c, s = math.cos(angle), math.sin(angle)
        moving = pivot + np.array([[c, -s], [s, c]]) @ moving_local
        return float(np.linalg.norm(fixed - moving)) - zero - float(stroke_m)

    low, high = -math.pi, math.pi
    f_low, f_high = value(low), value(high)
    if f_low * f_high > 0.0:
        raise RedesignError(f"axle{axle}_{side}: 该行程不在摆臂可达范围内")
    for _ in range(200):
        mid = 0.5 * (low + high)
        f_mid = value(mid)
        if f_low * f_mid <= 0.0:
            high, f_high = mid, f_mid
        else:
            low, f_low = mid, f_mid
    return 0.5 * (low + high)
