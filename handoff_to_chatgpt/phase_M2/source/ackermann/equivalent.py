"""PHASE M2：``ENGINEERING_EQUIVALENT_ACKERMANN`` 工程等效转向模式。

**为什么需要它。** 甲方四、五、六桥的"摆臂—边拉杆—车轮"四杆机构里，五、六桥
距死点只有 6.6°/9.7°（一、二、四桥为 76~85°）。其直接后果是：五桥**右轮的可达
车轮角范围是 [+0.007°, +13.104°]**，六桥右轮是 [+0.314°, +7.861°]——
两侧都只能单向偏转且方向相反，因此不存在让同桥左右轮同向转动的装配构型。
这是甲方硬点数据本身的性质，不是转录错误，也不允许通过改坐标"修好"。

**本模式做什么。** 在**不冒充**真实闭链精确解的前提下，给出一个方向正确、
有界、单调的等效转向关系，供演示与全工况表使用：

1. 目标角由共同瞬时转向中心计算（:mod:`steering_sim.ackermann.ideal`）；
2. 三桥恒为零；
3. 同桥左右轮遵守低速阿克曼方向（两侧取相同角，符号由反相桥规则决定）；
4. 幅值取自**真实四杆**在真实摆臂行程内的可达车轮角幅值 ``A(|s|)``；
5. 行程取自**真实液压缸几何**（甲方缸安装点），随摆臂角单调、有界；
6. ``A`` 有界，因此大角度下等效行程自然饱和，不会无界外推；
7. 所有引入的假设逐条标注 ``ASSUMED``；
8. 结果一律标记 ``ENGINEERING_EQUIVALENT_ACKERMANN``，与
   ``CUSTOMER_LINKAGE_GEOMETRY`` 分开保存，绝不覆盖。
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Mapping

import numpy as np

from .linkage import LEGACY_SIDE, REAR_AXLES, FourBar, LinkageError

#: 反相桥（相对一桥反向）。决定等效车轮角的符号规则。
REVERSED_AXLES = (4, 5, 6)
FORWARD_AXLES = (1, 2)

#: 等效模式引入的假设，逐条列出，供报告与界面原样转述。
ASSUMPTIONS = (
    "ASSUMED: 等效模式假定同桥左右轮严格同角（真实机构做不到），"
    "转角差由控制器而非机构产生。",
    "ASSUMED: 摆臂角—车轮角幅值关系直接取自真实四杆机构在同一摆臂角下的可达幅值，"
    "但强制为奇函数（真实机构为强非线性非奇函数）。",
    "ASSUMED: 大角度下等效行程按幅值上界自然饱和，不再外推。",
    "ASSUMED: 五、六桥的等效幅值上界分别为真实机构的 13.10° 与 7.86°。",
)

EQUIVALENT_TAG = "ENGINEERING_EQUIVALENT_ACKERMANN"
CUSTOMER_TAG = "CUSTOMER_LINKAGE_GEOMETRY"


@dataclass(frozen=True, slots=True)
class EquivalentChannel:
    """一个机构组的工程等效映射。"""

    key: str
    axle: int
    uses_real_linkage: bool
    swing_max_deg: float
    wheel_amplitude_max_deg: float
    stroke_span_m: float
    direction_sign: float
    tail: tuple[tuple[float, float, float], ...]     # (swing_rad, wheel_rad, stroke_m)
    reasons: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ASSUMPTIONS

    @property
    def tag(self) -> str:
        return CUSTOMER_TAG if self.uses_real_linkage else EQUIVALENT_TAG

    # ---------------------------------------------------------------- 映射
    def _interp(self, index: int, value: float) -> float:
        grid = [row[0] for row in self.tail]
        return float(np.interp(value, grid,
                               [row[index] for row in self.tail]))

    def wheel_rad(self, swing_rad: float) -> float:
        """等效车轮角（同桥两侧相同，符号由方向规则决定）。"""
        magnitude = self._interp(1, abs(swing_rad))
        return self.direction_sign * math.copysign(magnitude, swing_rad)

    def stroke_m(self, swing_rad: float) -> float:
        return self._interp(2, abs(swing_rad)) * math.copysign(1.0, swing_rad)

    def swing_for_stroke(self, stroke_m: float) -> float:
        grid = [row[2] for row in self.tail]
        swings = [row[0] for row in self.tail]
        return float(np.interp(abs(stroke_m), grid, swings)) * \
            math.copysign(1.0, stroke_m)

    def to_dict(self) -> dict:
        return {
            "key": self.key, "axle": self.axle, "tag": self.tag,
            "uses_real_linkage": self.uses_real_linkage,
            "swing_max_deg": self.swing_max_deg,
            "wheel_amplitude_max_deg": self.wheel_amplitude_max_deg,
            "stroke_span_m": self.stroke_span_m,
            "direction_sign": self.direction_sign,
            "reasons": list(self.reasons),
            "assumptions": list(self.assumptions),
        }


def _cylinder_stroke(reference, axle: int, side: str, swing_rad: float) -> float:
    """真实液压缸在该摆臂角下的行程（相对零位，m）。

    甲方表中 ``ACTUATOR_{axle}_A`` 驱动 ``SWING_{axle}_NEG_Y``（右侧），
    ``_B`` 驱动 ``POS_Y``（左侧）。
    """
    legacy = LEGACY_SIDE[side]
    name = f"ACTUATOR_{axle}_{'B' if legacy == 'POS_Y' else 'A'}"
    actuator = reference.actuators[name]
    fixed = np.asarray(reference.points[actuator.frame_point_id].position, dtype=float)
    body = reference.bodies[actuator.moving_body]
    moving_local = np.asarray(body.local_hardpoints[actuator.moving_point_id],
                              dtype=float)
    pivot = np.asarray(body.pivot, dtype=float)
    c, s = math.cos(swing_rad), math.sin(swing_rad)
    moving = pivot + np.array([[c, -s], [s, c]]) @ moving_local
    zero = float(np.linalg.norm(fixed - (pivot + moving_local)))
    return float(np.linalg.norm(fixed - moving)) - zero


def build_equivalent_channel(reference, four_bars: Mapping[str, FourBar],
                             key: str, axle: int, *, step_deg: float = 0.05,
                             swing_limit_deg: float = 40.0) -> EquivalentChannel:
    """由真实四杆幅值与真实缸几何构造一条等效映射。"""
    # 幅值来源：两侧、两个摆动方向共 4 条真实分支，取同一 |摆臂角| 下的最大幅值。
    # 这样 A(|s|) 才与"同桥左右轮同角"的等效假定自洽。
    amplitude: dict[float, float] = {}
    stroke_at: dict[float, float] = {}
    for side in ("left", "right"):
        bar = four_bars[f"axle{axle}_{side}"]
        for direction in (1.0, -1.0):
            s = 0.0
            previous = 0.0
            while abs(s) < math.radians(swing_limit_deg):
                s += direction * math.radians(step_deg)
                try:
                    roots = bar.wheel_angles(s)
                except LinkageError:
                    break
                candidate = min(roots, key=lambda value: abs(value - previous))
                if abs(math.degrees(candidate - previous)) > 5.0:
                    break
                if abs(bar.residual(s, candidate)) > 1.0e-9:
                    break
                previous = candidate
                key = round(abs(s), 9)
                magnitude = abs(candidate)
                if magnitude > amplitude.get(key, -1.0):
                    amplitude[key] = magnitude
                    stroke_at[key] = abs(_cylinder_stroke(reference, axle, side, s))
    if len(amplitude) < 5:
        raise LinkageError(f"axle{axle}: 真实机构可用行程过短，无法构造等效映射")

    # A(|s|) 必须单调不减才能作为映射使用：取累积最大值。
    best: list[tuple[float, float, float]] = [(0.0, 0.0, 0.0)]
    running = 0.0
    running_stroke = 0.0
    for swing in sorted(amplitude):
        running = max(running, amplitude[swing])
        running_stroke = max(running_stroke, stroke_at[swing])
        best.append((swing, running, running_stroke))

    monotone: list[tuple[float, float, float]] = []
    for swing, wheel, stroke in best:
        monotone.append((swing, wheel, stroke))
    # 摆臂角 × 行程都必须严格单调，插值才有意义。
    cleaned: list[tuple[float, float, float]] = []
    stroke_running = 0.0
    for swing, wheel, stroke in monotone:
        stroke_running = max(stroke_running, stroke)
        if not cleaned or swing > cleaned[-1][0] + 1.0e-12:
            cleaned.append((swing, wheel, stroke_running))
    direction = -1.0 if axle in REVERSED_AXLES else 1.0
    return EquivalentChannel(
        key=key, axle=axle, uses_real_linkage=False,
        swing_max_deg=math.degrees(cleaned[-1][0]),
        wheel_amplitude_max_deg=math.degrees(cleaned[-1][1]),
        stroke_span_m=cleaned[-1][2], direction_sign=direction,
        tail=tuple(cleaned))


def build_equivalent_map(reference, four_bars: Mapping[str, FourBar], *,
                         need: Mapping[str, bool] | None = None
                         ) -> dict[str, EquivalentChannel]:
    """按通道构造等效映射。

    ``need`` 指明哪些通道必须使用等效模式（真实机构无法满足阿克曼方向）；
    未列入的通道默认保留真实闭链，仅在其真实机构确实不可用时才生成等效映射。
    """
    plan = {"channel_rear_1": 4, "channel_rear_2": 5, "channel_rear_3": 6}
    result: dict[str, EquivalentChannel] = {}
    for key, axle in plan.items():
        required = bool((need or {}).get(key, False))
        channel = build_equivalent_channel(reference, four_bars, key, axle)
        reasons = []
        if required:
            reasons.append("真实机构同桥左右轮无法同向，必须使用等效模式")
        result[key] = EquivalentChannel(
            key=channel.key, axle=channel.axle,
            uses_real_linkage=not required,
            swing_max_deg=channel.swing_max_deg,
            wheel_amplitude_max_deg=channel.wheel_amplitude_max_deg,
            stroke_span_m=channel.stroke_span_m,
            direction_sign=channel.direction_sign, tail=channel.tail,
            reasons=tuple(reasons))
    return result
