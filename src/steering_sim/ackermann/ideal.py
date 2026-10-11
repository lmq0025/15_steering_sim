"""PHASE M2：低速理想阿克曼角（共同瞬时转向中心）。

本模块**独立实现**几何公式，不调用 ``mechanics_ackermann_v2`` 的任何拟合或查表，
用作对 M1 的交叉校核。

几何约定（与甲方坐标系一致）：

* ``x`` 指向车头，``y`` 指向车辆左侧（右手系，``z`` 向上）；
* 原点在一桥两个轮胎中心连线的中点；
* 左转为正、右转为负；一桥**外侧**轮角作为输入；
* 瞬时转向中心 ICR 固定在三桥车轮中心所在的横线上（多轴车辆定中间桥的
  共同转向中心做法），即 ``x_ICR = x_axle3``。

推导。设车辆以角速度 ω 绕 ICR 转动，令 ``R_i = r_i − r_ICR``，则轮心速度

    v_i = ω ẑ × R_i = ω ( −R_iy , R_ix )

车轮必须沿该方向滚动，故 ``(cos δ_i, sin δ_i) ∝ v_i``。约去 ``|ω|`` 并把
``s = sign(ω) = sign(δ_target)`` 提出来，记 ``R = |y_ICR| = s·y_ICR > 0``：

    cos δ_i ∝ s ( y_ICR − y_i ) = R − s·y_i
    sin δ_i ∝ s ( x_i − x_ICR )

即

    δ_i = atan2( s·(x_i − x_ICR) , R − s·y_i )

这是**带符号的**严格形式，右转时不需要任何角度折叠。三桥自身
``x_i = x_ICR`` 且 Y 向对称，故 δ ≡ 0。

（``mechanics_ackermann_v2`` 对右转采用 ``atan2(x−x_ICR, y_ICR−y)`` 再折叠到
``(−90°, 90°]``，两者在 ±30° 范围内给出相同结果；本模块不复用该折叠，
以保持公式的独立性与可验证性。）

``y_ICR`` 由输入的外侧轮角反解：``y_ICR = y_outer + (x_outer − x_ICR)/tan(δ_outer)``。

参考公开研究：多轴车辆共同瞬时转向中心与固定中间桥；三轴反相阿克曼机构。
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping

WHEEL_ORDER = tuple(f"axle{axle}_{side}" for axle in range(1, 7)
                    for side in ("left", "right"))
AXLE_OF = {wheel: int(wheel[4]) for wheel in WHEEL_ORDER}
SIDE_OF = {wheel: wheel.split("_", 1)[1] for wheel in WHEEL_ORDER}

#: 反相桥（相对一桥反向转动的桥）。三桥锁止，四五六桥反向。
REVERSED_AXLES = (4, 5, 6)
FORWARD_AXLES = (1, 2)
LOCKED_AXLES = (3,)


class IdealAckermannError(ValueError):
    """理想阿克曼几何本身不可解（例如转角过大导致 ICR 落在车体另一侧）。"""


@dataclass(frozen=True, slots=True)
class IdealAckermann:
    target_outer_angle_deg: float
    outer_wheel: str | None
    x_icr_m: float
    y_icr_m: float | None
    turn_radius_m: float | None
    curvature_1pm: float
    angles_deg: Mapping[str, float]
    messages: tuple[str, ...] = ()

    def direction_flags(self) -> tuple[str, ...]:
        """检查左右轮方向是否符合低速共同 ICR 要求。"""
        flags: list[str] = []
        target = self.target_outer_angle_deg
        if abs(target) <= 1.0e-12:
            return ()
        sign = math.copysign(1.0, target)
        for axle in FORWARD_AXLES:
            for side in ("left", "right"):
                if math.copysign(1.0, self.angles_deg[f"axle{axle}_{side}"]) != sign:
                    flags.append(f"axle{axle}_{side}:NOT_FORWARD")
        for axle in REVERSED_AXLES:
            for side in ("left", "right"):
                value = self.angles_deg[f"axle{axle}_{side}"]
                if math.copysign(1.0, value) != -sign:
                    flags.append(f"axle{axle}_{side}:NOT_REVERSED")
        for axle in LOCKED_AXLES:
            for side in ("left", "right"):
                if abs(self.angles_deg[f"axle{axle}_{side}"]) > 1.0e-12:
                    flags.append(f"axle{axle}_{side}:NOT_LOCKED")
        for axle in range(1, 7):
            left = self.angles_deg[f"axle{axle}_left"]
            right = self.angles_deg[f"axle{axle}_right"]
            if abs(left) > 1.0e-12 and abs(right) > 1.0e-12 and \
                    math.copysign(1.0, left) != math.copysign(1.0, right):
                flags.append(f"axle{axle}:LEFT_RIGHT_OPPOSITE")
        return tuple(flags)


def ideal_ackermann(target_outer_angle_deg: float,
                    centers: Mapping[str, tuple[float, float]]) -> IdealAckermann:
    """由共同 ICR 计算十二轮的理想阿克曼角（度）。

    ``centers`` 为甲方给出的十二个车轮中心坐标（m），键为 ``axle{n}_{side}``。
    """
    target = float(target_outer_angle_deg)
    if not math.isfinite(target):
        raise IdealAckermannError("目标转角必须是有限数值")
    if abs(target) > 90.0:
        raise IdealAckermannError("目标转角超出 ±90°")
    missing = [wheel for wheel in WHEEL_ORDER if wheel not in centers]
    if missing:
        raise IdealAckermannError(f"缺少车轮中心坐标：{missing[:4]}")

    x_icr = 0.5 * (centers["axle3_left"][0] + centers["axle3_right"][0])
    if abs(target) <= 1.0e-14:
        return IdealAckermann(
            target_outer_angle_deg=0.0, outer_wheel=None, x_icr_m=x_icr,
            y_icr_m=None, turn_radius_m=None, curvature_1pm=0.0,
            angles_deg={wheel: 0.0 for wheel in WHEEL_ORDER},
            messages=("直行：所有车轮角为 0，ICR 在无穷远。",))

    # 左转时车辆绕左侧的 ICR 转动，外侧轮是右轮；右转镜像。
    outer = "axle1_right" if target > 0.0 else "axle1_left"
    x_outer, y_outer = centers[outer]
    tangent = math.tan(math.radians(target))
    if abs(tangent) < 1.0e-12:
        raise IdealAckermannError("目标转角过小，无法确定 ICR")
    y_icr = y_outer + (x_outer - x_icr) / tangent
    if math.copysign(1.0, y_icr) != math.copysign(1.0, target):
        raise IdealAckermannError(
            f"目标外侧轮角 {target:+.3f}° 给出的 ICR 落在车辆另一侧")

    sign = 1.0 if target > 0.0 else -1.0
    radius = abs(y_icr)
    angles: dict[str, float] = {}
    for wheel in WHEEL_ORDER:
        x, y = centers[wheel]
        if AXLE_OF[wheel] in LOCKED_AXLES:
            angles[wheel] = 0.0
            continue
        angles[wheel] = math.degrees(math.atan2(sign * (x - x_icr),
                                                radius - sign * y))

    radius = abs(y_icr)
    curvature = math.copysign(1.0 / radius, target)
    return IdealAckermann(
        target_outer_angle_deg=target, outer_wheel=outer, x_icr_m=x_icr,
        y_icr_m=y_icr, turn_radius_m=radius, curvature_1pm=curvature,
        angles_deg=angles,
        messages=(f"ICR 位于三桥横线 x={x_icr:.3f} m、y={y_icr:+.3f} m，"
                  f"转弯半径 {radius:.3f} m。",))


def sweep_ideal(targets_deg, centers) -> dict[float, IdealAckermann]:
    """对一串目标角求理想阿克曼角（供校核与出表使用）。"""
    return {float(target): ideal_ackermann(float(target), centers)
            for target in targets_deg}


#: 乙方要求的校核角度。
CHECK_ANGLES_DEG = (0.0, 2.0, -2.0, 5.0, -5.0, 10.0, -10.0, 20.0, -20.0,
                    30.0, -30.0)
