"""PHASE M2：五类状态分离与整车动力学适用性。

任务书要求把过去混在一起的几种"不可用"彻底分开：

``NUMERICAL_ENVELOPE_LIMIT``
    程序搜索范围不够——只是没算到，不是机构不行。
``KINEMATIC_SOLVER_FAILURE``
    运动学求解没有成功（不收敛、残差超限、分支跳变）。
``PHYSICAL_LINKAGE_LIMIT``
    由真实杆件干涉、缸行程或机械止挡确认的物理不可达。
``ACKERMANN_TARGET_MISMATCH``
    机构能运动，但左右轮角无法匹配理想阿克曼（含方向相反）。
``VEHICLE_DYNAMIC_INFEASIBLE``
    机构几何允许，但车速与地面附着不允许该转弯。

另外把四类角度严格分开，禁止互相替代：

``ideal_ackermann_angle_deg``        共同 ICR 的理想几何角
``theoretical_mechanical_angle_deg`` 真实闭链在目标机构坐标上的角（无载）
``equivalent_ackermann_angle_deg``   工程等效模式的角（有明确假设）
``actual_hydraulic_driven_angle_deg`` J0 动态闭环中由真实缸位移反求的角
``actual_loaded_angle_deg``          静态柔度修正后的受载估计角
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Mapping

from .ideal import IdealAckermann, ideal_ackermann
from .linkage import REAR_AXLES

WHEEL_ORDER = tuple(f"axle{axle}_{side}" for axle in range(1, 7)
                    for side in ("left", "right"))
AXLE_OF = {wheel: int(wheel[4]) for wheel in WHEEL_ORDER}

# ---------------------------------------------------------------- 状态枚举
OK = "OK"
NUMERICAL_ENVELOPE_LIMIT = "NUMERICAL_ENVELOPE_LIMIT"
KINEMATIC_SOLVER_FAILURE = "KINEMATIC_SOLVER_FAILURE"
PHYSICAL_LINKAGE_LIMIT = "PHYSICAL_LINKAGE_LIMIT"
ACKERMANN_TARGET_MISMATCH = "ACKERMANN_TARGET_MISMATCH"
VEHICLE_DYNAMIC_INFEASIBLE = "VEHICLE_DYNAMIC_INFEASIBLE"

GEOMETRY_STATUSES = (OK, NUMERICAL_ENVELOPE_LIMIT, KINEMATIC_SOLVER_FAILURE,
                     PHYSICAL_LINKAGE_LIMIT, ACKERMANN_TARGET_MISMATCH)
VEHICLE_STATUSES = (OK, VEHICLE_DYNAMIC_INFEASIBLE)

#: 状态严重程度，用于把多个通道的状态归并成整工况状态。
SEVERITY = {OK: 0, NUMERICAL_ENVELOPE_LIMIT: 1, ACKERMANN_TARGET_MISMATCH: 2,
            KINEMATIC_SOLVER_FAILURE: 3, PHYSICAL_LINKAGE_LIMIT: 4}

DRIVING_DIRECTION = {1: 1, 2: 1, 3: 0, 4: -1, 5: -1, 6: -1}


def worst(statuses) -> str:
    items = [item for item in statuses if item]
    if not items:
        return OK
    return max(items, key=lambda item: SEVERITY.get(item, 0))


@dataclass(frozen=True, slots=True)
class VehicleFeasibility:
    speed_kmh: float
    friction_coefficient: float
    turn_radius_m: float | None
    lateral_acceleration_mps2: float | None
    adhesion_limit_mps2: float
    adhesion_ratio: float | None
    feasible: bool
    status: str
    message: str

    def to_dict(self) -> dict:
        return {
            "speed_kmh": self.speed_kmh,
            "friction_coefficient": self.friction_coefficient,
            "turn_radius_m": self.turn_radius_m,
            "lateral_acceleration_mps2": self.lateral_acceleration_mps2,
            "adhesion_limit_mps2": self.adhesion_limit_mps2,
            "adhesion_ratio": self.adhesion_ratio,
            "feasible": self.feasible,
            "status": self.status,
            "message": self.message,
        }


GRAVITY = 9.80665


def vehicle_feasibility(speed_kmh: float, friction_coefficient: float,
                        turn_radius_m: float | None) -> VehicleFeasibility:
    """稳态转向的附着条件 ``a_y = v²/R ≤ μ g``。"""
    limit = float(friction_coefficient) * GRAVITY
    if turn_radius_m is None or not math.isfinite(turn_radius_m) or \
            turn_radius_m <= 0.0:
        return VehicleFeasibility(
            speed_kmh=float(speed_kmh), friction_coefficient=float(friction_coefficient),
            turn_radius_m=None, lateral_acceleration_mps2=0.0,
            adhesion_limit_mps2=limit, adhesion_ratio=0.0, feasible=True,
            status=OK, message="直行：无侧向加速度要求。")
    speed = float(speed_kmh) / 3.6
    a_y = speed * speed / float(turn_radius_m)
    ratio = a_y / limit if limit > 0.0 else math.inf
    feasible = ratio <= 1.0
    return VehicleFeasibility(
        speed_kmh=float(speed_kmh), friction_coefficient=float(friction_coefficient),
        turn_radius_m=float(turn_radius_m), lateral_acceleration_mps2=a_y,
        adhesion_limit_mps2=limit, adhesion_ratio=ratio, feasible=feasible,
        status=OK if feasible else VEHICLE_DYNAMIC_INFEASIBLE,
        message=(f"a_y = {a_y:.3f} m/s² ≤ μ g = {limit:.3f} m/s²，附着满足。"
                 if feasible else
                 f"a_y = {a_y:.3f} m/s² > μ g = {limit:.3f} m/s²，附着不足，"
                 f"该车速与转角组合动力学不可行。"))


@dataclass(frozen=True, slots=True)
class WheelAngleSet:
    """同一工况下四种角度的完整集合，互不替代。"""

    ideal_deg: Mapping[str, float]
    theoretical_mechanical_deg: Mapping[str, float] | None = None
    equivalent_ackermann_deg: Mapping[str, float] | None = None
    actual_hydraulic_driven_deg: Mapping[str, float] | None = None
    actual_loaded_deg: Mapping[str, float] | None = None

    def ackermann_deviation_deg(self, source: str = "theoretical_mechanical") -> dict:
        values = getattr(self, f"{source}_deg")
        if values is None:
            return {}
        return {wheel: float(values[wheel] - self.ideal_deg[wheel])
                for wheel in WHEEL_ORDER if wheel in values}


def direction_violations(angles_deg: Mapping[str, float],
                         target_deg: float) -> tuple[str, ...]:
    """检查一组车轮角是否满足低速共同 ICR 的方向要求。"""
    if abs(target_deg) <= 1.0e-12:
        return ()
    sign = math.copysign(1.0, target_deg)
    violations: list[str] = []
    for wheel in WHEEL_ORDER:
        if wheel not in angles_deg:
            continue
        axle = AXLE_OF[wheel]
        expected = DRIVING_DIRECTION[axle]
        if expected == 0:
            if abs(angles_deg[wheel]) > 1.0e-6:
                violations.append(f"{wheel}:THIRD_AXLE_NOT_LOCKED")
            continue
        value = angles_deg[wheel]
        if abs(value) < 1.0e-6:
            continue
        if math.copysign(1.0, value) != sign * expected:
            violations.append(f"{wheel}:WRONG_DIRECTION")
    for axle in range(1, 7):
        left, right = f"axle{axle}_left", f"axle{axle}_right"
        if left not in angles_deg or right not in angles_deg:
            continue
        if abs(angles_deg[left]) > 1.0e-6 and abs(angles_deg[right]) > 1.0e-6 and \
                math.copysign(1.0, angles_deg[left]) != \
                math.copysign(1.0, angles_deg[right]):
            violations.append(f"axle{axle}:LEFT_RIGHT_OPPOSITE")
    return tuple(violations)


@dataclass(frozen=True, slots=True)
class CaseAssessment:
    target_outer_angle_deg: float
    speed_kmh: float
    friction_coefficient: float
    axle_loads_t: tuple[float, ...]
    geometry_status: str
    vehicle_status: str
    angles: WheelAngleSet
    per_axle_status: Mapping[int, str]
    vehicle: VehicleFeasibility
    flags: tuple[str, ...]
    messages: tuple[str, ...]
    envelope_notes: tuple[str, ...] = ()

    @property
    def status(self) -> str:
        if self.geometry_status == OK and self.vehicle_status == OK:
            return OK
        return self.geometry_status if self.geometry_status != OK \
            else self.vehicle_status

    @property
    def drivable(self) -> bool:
        return (self.geometry_status in (OK, ACKERMANN_TARGET_MISMATCH)
                and self.vehicle_status == OK)

    def to_dict(self) -> dict:
        return {
            "target_outer_angle_deg": self.target_outer_angle_deg,
            "speed_kmh": self.speed_kmh,
            "friction_coefficient": self.friction_coefficient,
            "axle_loads_t": list(self.axle_loads_t),
            "geometry_status": self.geometry_status,
            "vehicle_status": self.vehicle_status,
            "status": self.status,
            "ideal_ackermann_angle_deg": dict(self.angles.ideal_deg),
            "theoretical_mechanical_angle_deg": (
                dict(self.angles.theoretical_mechanical_deg)
                if self.angles.theoretical_mechanical_deg else None),
            "equivalent_ackermann_angle_deg": (
                dict(self.angles.equivalent_ackermann_deg)
                if self.angles.equivalent_ackermann_deg else None),
            "actual_loaded_angle_deg": (
                dict(self.angles.actual_loaded_deg)
                if self.angles.actual_loaded_deg else None),
            "ackermann_deviation_deg": self.angles.ackermann_deviation_deg(),
            "per_axle_status": {str(k): v for k, v in self.per_axle_status.items()},
            "vehicle": self.vehicle.to_dict(),
            "flags": list(self.flags),
            "messages": list(self.messages),
        }


def assess_wheel_set(angles_deg: Mapping[str, float], target_deg: float,
                     mechanism_direction_ok: Mapping[int, bool] | None = None,
                     envelope_status: Mapping[int, str] | None = None,
                     ) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    """把一组机构角归类到五类状态之一。"""
    violations = direction_violations(angles_deg, target_deg)
    messages: list[str] = []
    flags = list(violations)
    status = OK
    if any(item.endswith("LEFT_RIGHT_OPPOSITE") for item in violations):
        status = worst((status, ACKERMANN_TARGET_MISMATCH))
        messages.append(
            "同一转向桥左右轮方向相反，机构无法满足低速阿克曼方向要求。")
    if any(item.endswith("WRONG_DIRECTION") for item in violations):
        status = worst((status, ACKERMANN_TARGET_MISMATCH))
        messages.append("存在与低速阿克曼方向要求相反的车轮。")
    if mechanism_direction_ok is not None:
        stuck = [axle for axle, ok in mechanism_direction_ok.items() if not ok]
        if stuck:
            status = worst((status, PHYSICAL_LINKAGE_LIMIT))
            messages.append(
                "四杆机构在甲方硬点下为单向可达（" +
                "、".join(f"{axle}桥" for axle in sorted(stuck)) +
                "），属几何硬约束。")
    if envelope_status:
        for axle, value in envelope_status.items():
            if value == NUMERICAL_ENVELOPE_LIMIT:
                status = worst((status, NUMERICAL_ENVELOPE_LIMIT))
                messages.append(f"{axle}桥：机构坐标触及数值搜索包络。")
            elif value == KINEMATIC_SOLVER_FAILURE:
                status = worst((status, KINEMATIC_SOLVER_FAILURE))
                messages.append(f"{axle}桥：运动学求解失败。")
            elif value == PHYSICAL_LINKAGE_LIMIT:
                status = worst((status, PHYSICAL_LINKAGE_LIMIT))
                messages.append(f"{axle}桥：真实机构确认物理不可达。")
    return status, tuple(flags), tuple(messages)


def ideal_for(target_deg: float, centers) -> IdealAckermann:
    return ideal_ackermann(float(target_deg), centers)
