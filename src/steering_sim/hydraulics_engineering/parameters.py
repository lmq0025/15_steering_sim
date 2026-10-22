"""PHASE J1-R2 工程液压参数：结构化、可配置、可退化。

**所有数值都是工程选型值，逐项标记 ``ENGINEERING_DESIGN_ASSUMPTION``**，不是甲方
设备实测参数。旧 Amesim / L1-Fast 参数在 ``configs/j1/hydraulic_design.json`` 的
``legacy_parameters`` 中原样存档，本模块不读、不改、不继承它们。

选型方法（由 ``scripts/j1r2/design_engineering_hydraulics.py`` 执行）：

1. 在最不利正常工作工况（低速大转角、高附着）下，由机构行程雅可比按虚功
   ``F_required = M_required / (ds/dδ)`` 求各组需求推力；
2. 按机械效率与安全系数放大，再由设计负载压力反算有效面积，向上取标准缸径；
3. 行程由机构包络的实测行程乘余量给出；
4. 最大速度由指令斜坡给出，据此求单通道峰值流量；
5. 泵排量按**同一条供油轨上多通道同时动作**的峰值总流量乘流量余量确定。

退化接口（任务书第九节）在 :class:`DegradationParameters` 中统一预留，默认全部为
新件取值；以后调整泵容积效率/内泄漏、阀流量系数/死区/响应迟滞、缸内泄漏/摩擦时
只需改配置，不需要改模型代码。
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from functools import lru_cache
import json
import math
from pathlib import Path
from typing import Any, Mapping

#: 本模型的标识（写进每一份结果与报告）。
TAG = "ENGINEERING_HYDRAULIC_V1"
#: 所有设计参数的证据等级。
ASSUMPTION_TAG = "ENGINEERING_DESIGN_ASSUMPTION"

SUPPLY_ORDER = ("front", "rear")


class ParameterError(ValueError):
    """参数不合法（缺失、非正、互相矛盾）。"""


# --------------------------------------------------------------------- 元件
@dataclass(frozen=True, slots=True)
class CylinderParameters:
    """阀控**对称双腔**液压缸（双出杆等价）参数。

    选对称缸的理由：转向作动必须在左右两个方向给出对称的力与速度，双出杆（或
    一对对置单杆缸等效成的一只对称缸）是转向执行器的标准做法。这样阀控方程的
    两个方向完全对称，命令极性与运动方向的关系唯一，不需要额外的方向补偿。
    """

    area_a_m2: float
    area_b_m2: float
    #: 全行程（总行程，m）。
    stroke_m: float
    #: 单侧死容积（m³）—— 含阀到缸的管路容积。
    dead_volume_m3: float
    bore_mm: float
    #: 折算到活塞杆上的等效运动质量（kg）：由转向轴绕主销的转动惯量经
    #: ``(dδ/dx)²`` 折算得到，是真实的多体折算，不是随手取的数。
    mass_kg: float
    viscous_damping_n_s_per_m: float
    coulomb_friction_n: float
    end_stop_stiffness_n_per_m: float
    end_stop_damping_n_s_per_m: float
    #: 折算惯量的来源说明（转动惯量假设 + 折算比）。
    mass_source: str = ASSUMPTION_TAG
    #: 活塞中位对应的**机构行程坐标**（m）。机构行程曲线的可用区间一般不对称
    #: （由甲方缸几何决定），所以缸中位要偏置，全行程才能刚好覆盖机构包络：
    #: 活塞相对中位的位移 ``xc = x − stroke_offset_m`` 才是腔容积与限位用的量。
    stroke_offset_m: float = 0.0

    def __post_init__(self) -> None:
        for name in ("area_a_m2", "area_b_m2", "stroke_m", "mass_kg"):
            if getattr(self, name) <= 0.0:
                raise ParameterError(f"cylinder.{name} 必须为正")
        if self.dead_volume_m3 <= 0.0:
            raise ParameterError("cylinder.dead_volume_m3 必须为正（否则腔容积会非正）")

    @property
    def half_stroke_m(self) -> float:
        return 0.5 * self.stroke_m

    @property
    def stroke_min_m(self) -> float:
        """机构行程坐标下活塞能到达的下限。"""
        return self.stroke_offset_m - self.half_stroke_m

    @property
    def stroke_max_m(self) -> float:
        """机构行程坐标下活塞能到达的上限。"""
        return self.stroke_offset_m + self.half_stroke_m

    @property
    def symmetric(self) -> bool:
        return abs(self.area_a_m2 - self.area_b_m2) <= 1.0e-12 * self.area_a_m2


@dataclass(frozen=True, slots=True)
class ValveParameters:
    """四通比例/伺服阀等效节流口。"""

    #: 满命令时的等效节流面积（m²）。
    maximum_area_m2: float
    discharge_coefficient: float = 0.62
    #: 阀芯一阶响应时间常数（s）。伺服阀阶跃响应量级，不能取 0（那等于理想阀）。
    lag_time_s: float = 2.0e-3
    #: 中位死区（归一化命令）。新件取 0，退化/磨损后增大。
    deadband: float = 0.0
    #: 折算到活塞上的速度-命令增益（m/s 每单位命令），由选型脚本按设计点算出，
    #: 供控制器做速度前馈，不是被控对象本构的一部分。
    velocity_per_unit_command_m_s: float = 0.0

    def __post_init__(self) -> None:
        if self.maximum_area_m2 <= 0.0:
            raise ParameterError("valve.maximum_area_m2 必须为正")
        if not 0.0 < self.discharge_coefficient <= 1.0:
            raise ParameterError("valve.discharge_coefficient 必须在 (0, 1]")
        if self.lag_time_s < 1.0e-4:
            raise ParameterError(
                "valve.lag_time_s 不得小于 0.1 ms：理想阀会让流量阶跃激励未建模的"
                "高频模态，必须保留真实伺服阀的有限带宽")


@dataclass(frozen=True, slots=True)
class PumpParameters:
    """定量泵 + 溢流阀 + 蓄能器容积组成的等效恒压油源。

    ``displacement_m3_per_rad * nominal_speed_rad_s`` 给出泵的理论流量；实际流量
    再乘容积效率。蓄能器容积与油液体积弹性模量一起给出供油压力的动态 —— 需求流量
    超过泵能力时供压会真实下跌，**不是无限流量**。
    """

    displacement_m3_per_rad: float
    nominal_speed_rad_s: float
    #: 溢流阀开启压力（Pa，表压）—— 也是供油压力的上限。
    relief_pressure_pa: float
    plenum_volume_m3: float
    bulk_modulus_pa: float
    relief_area_m2: float

    def __post_init__(self) -> None:
        for name in ("displacement_m3_per_rad", "nominal_speed_rad_s",
                     "relief_pressure_pa", "plenum_volume_m3", "bulk_modulus_pa",
                     "relief_area_m2"):
            if getattr(self, name) <= 0.0:
                raise ParameterError(f"pump.{name} 必须为正")

    @property
    def ideal_flow_m3_s(self) -> float:
        return self.displacement_m3_per_rad * self.nominal_speed_rad_s


@dataclass(frozen=True, slots=True)
class PumpDegradationParameters:
    """单条供油轨的退化参数。

    D1 的齿轮泵磨损以 ``internal_leakage_m3_s_per_pa`` 作为唯一流量损失作用量；
    ``volumetric_efficiency`` 可供历史/外部标定路径使用。预测器不会同时用两者描述
    同一份磨损，避免重复扣除流量。
    """

    volumetric_efficiency: float = 1.0
    internal_leakage_m3_s_per_pa: float = 0.0
    # D3 second mode.  Mechanical efficiency changes shaft power/torque, not
    # displacement flow.  A zero limit disables the optional prime-mover
    # constraint and therefore preserves the J1-R2/D1/D2 healthy baseline.
    mechanical_efficiency: float = 1.0
    rated_drive_power_w: float = 0.0

    def __post_init__(self) -> None:
        if not 0.0 < self.volumetric_efficiency <= 1.0:
            raise ParameterError("泵容积效率必须在 (0, 1]")
        if self.internal_leakage_m3_s_per_pa < 0.0:
            raise ParameterError("泵内泄漏系数不得为负")
        if not 0.0 < self.mechanical_efficiency <= 1.0:
            raise ParameterError("泵机械效率必须在 (0, 1]")
        if self.rated_drive_power_w < 0.0:
            raise ParameterError("泵驱动功率上限不得为负")

    def to_dict(self) -> dict[str, float]:
        return {"volumetric_efficiency": self.volumetric_efficiency,
                "internal_leakage_m3_s_per_pa":
                    self.internal_leakage_m3_s_per_pa,
                "mechanical_efficiency": self.mechanical_efficiency,
                "rated_drive_power_w": self.rated_drive_power_w}


@dataclass(frozen=True, slots=True)
class ValveDegradationParameters:
    """单个等效作动通道的转向阀退化参数。"""

    internal_leakage_m3_s_per_pa: float = 0.0
    flow_coefficient_scale: float = 1.0
    lag_scale: float = 1.0

    def __post_init__(self) -> None:
        if self.internal_leakage_m3_s_per_pa < 0.0:
            raise ParameterError("阀内泄漏系数不得为负")
        if not 0.0 < self.flow_coefficient_scale <= 2.0:
            raise ParameterError("阀流量系数缩放必须在 (0, 2]")
        if self.lag_scale < 1.0:
            raise ParameterError("阀响应时间缩放不得小于 1")

    def to_dict(self) -> dict[str, float]:
        return {"internal_leakage_m3_s_per_pa":
                    self.internal_leakage_m3_s_per_pa,
                "flow_coefficient_scale": self.flow_coefficient_scale,
                "lag_scale": self.lag_scale}


@dataclass(frozen=True, slots=True)
class CylinderDegradationParameters:
    """单个等效对称缸的退化参数。"""

    internal_leakage_m3_s_per_pa: float = 0.0
    friction_scale: float = 1.0

    def __post_init__(self) -> None:
        if self.internal_leakage_m3_s_per_pa < 0.0:
            raise ParameterError("缸内泄漏系数不得为负")
        if self.friction_scale < 1.0:
            raise ParameterError("缸摩擦缩放不得小于 1")

    def to_dict(self) -> dict[str, float]:
        return {"internal_leakage_m3_s_per_pa":
                    self.internal_leakage_m3_s_per_pa,
                "friction_scale": self.friction_scale}


_HEALTHY_PUMP = PumpDegradationParameters()
_HEALTHY_VALVE = ValveDegradationParameters()
_HEALTHY_CYLINDER = CylinderDegradationParameters()


@lru_cache(maxsize=256)
def _combined_pump(efficiency, leakage, local):
    return PumpDegradationParameters(efficiency*local.volumetric_efficiency,
        leakage+local.internal_leakage_m3_s_per_pa, local.mechanical_efficiency,
        local.rated_drive_power_w)


@lru_cache(maxsize=256)
def _combined_valve(flow_scale, lag_scale, local):
    return ValveDegradationParameters(local.internal_leakage_m3_s_per_pa,
        flow_scale*local.flow_coefficient_scale, lag_scale*local.lag_scale)


@lru_cache(maxsize=256)
def _combined_cylinder(leakage, friction, local):
    return CylinderDegradationParameters(leakage+local.internal_leakage_m3_s_per_pa,
        friction*local.friction_scale)


@dataclass(frozen=True, slots=True)
class DegradationParameters:
    """退化接口（统一入口，本轮全部为新件取值）。

    以后实现退化/寿命/质量预测时，只需按时间或循环数改写这些量并重新运行同一
    模型，**不需要改模型代码**。
    """

    #: 泵容积效率（<1 表示流量损失）。
    pump_volumetric_efficiency: float = 1.0
    #: 泵内泄漏（m³/s/Pa）：压差驱动的附加泄漏。
    pump_internal_leakage_m3_s_per_pa: float = 0.0
    #: 阀流量系数缩放（磨损后节流面积有效值变化）。
    valve_flow_coefficient_scale: float = 1.0
    #: 阀响应时间放大倍数（迟滞/变慢）。
    valve_lag_scale: float = 1.0
    #: 缸内泄漏（m³/s/Pa）：两腔之间的窜漏。
    cylinder_internal_leakage_m3_s_per_pa: float = 0.0
    #: 缸摩擦力放大倍数。
    cylinder_friction_scale: float = 1.0
    #: 供油压力上限缩放（泵磨损后压力上不去）。1.0 = 新件。
    supply_pressure_scale: float = 1.0
    #: D1 部件级正式入口。空映射表示健康；上面的 7 个字段仅保留历史兼容。
    pumps: Mapping[str, PumpDegradationParameters] = field(default_factory=dict)
    valves: Mapping[str, ValveDegradationParameters] = field(default_factory=dict)
    cylinders: Mapping[str, CylinderDegradationParameters] = field(default_factory=dict)
    # 旧 demo GUI 的只读兼容字段。它们不再连接 L1-Fast，且仅允许健康值 1.0；
    # 正式退化必须使用上面的工程物理字段或 pumps/valves/cylinders 映射。
    valve_discharge_coefficient: float = 1.0
    cylinder_internal_leakage: float = 1.0
    cylinder_friction: float = 1.0
    cylinder_damping: float = 1.0
    controller_proportional_gain: float = 1.0

    def __post_init__(self) -> None:
        if not 0.0 < self.pump_volumetric_efficiency <= 1.0:
            raise ParameterError("全局泵容积效率必须在 (0, 1]")
        if self.pump_internal_leakage_m3_s_per_pa < 0.0:
            raise ParameterError("全局泵内泄漏不得为负")
        if self.cylinder_internal_leakage_m3_s_per_pa < 0.0:
            raise ParameterError("全局缸内泄漏不得为负")
        legacy = (self.valve_discharge_coefficient,
                  self.cylinder_internal_leakage, self.cylinder_friction,
                  self.cylinder_damping, self.controller_proportional_gain)
        if any(value != 1.0 for value in legacy):
            raise ParameterError("旧 demo 乘性占位字段只允许健康值 1.0；请使用正式工程退化参数")

    def pump(self, name: str) -> PumpDegradationParameters:
        # Key includes every global factor and the current immutable local
        # value. Even replacing an entry in a caller-owned mapping is observed.
        return _combined_pump(self.pump_volumetric_efficiency,
            self.pump_internal_leakage_m3_s_per_pa, self.pumps.get(name, _HEALTHY_PUMP))

    def valve(self, name: str) -> ValveDegradationParameters:
        return _combined_valve(self.valve_flow_coefficient_scale,
            self.valve_lag_scale, self.valves.get(name, _HEALTHY_VALVE))

    def cylinder(self, name: str) -> CylinderDegradationParameters:
        return _combined_cylinder(self.cylinder_internal_leakage_m3_s_per_pa,
            self.cylinder_friction_scale, self.cylinders.get(name, _HEALTHY_CYLINDER))

    @property
    def is_new_unit(self) -> bool:
        return (self.pump_volumetric_efficiency == 1.0
                and self.pump_internal_leakage_m3_s_per_pa == 0.0
                and self.valve_flow_coefficient_scale == 1.0
                and self.valve_lag_scale == 1.0
                and self.cylinder_internal_leakage_m3_s_per_pa == 0.0
                and self.cylinder_friction_scale == 1.0
                and self.supply_pressure_scale == 1.0
                and not self.pumps and not self.valves and not self.cylinders)

    @property
    def is_healthy(self) -> bool:
        """旧 GUI/测试名称；与正式 ``is_new_unit`` 完全等价。"""
        return self.is_new_unit

    def to_dict(self) -> dict[str, float]:
        result: dict[str, Any] = {
            "pump_volumetric_efficiency": self.pump_volumetric_efficiency,
            "pump_internal_leakage_m3_s_per_pa": self.pump_internal_leakage_m3_s_per_pa,
            "valve_flow_coefficient_scale": self.valve_flow_coefficient_scale,
            "valve_lag_scale": self.valve_lag_scale,
            "cylinder_internal_leakage_m3_s_per_pa": self.cylinder_internal_leakage_m3_s_per_pa,
            "cylinder_friction_scale": self.cylinder_friction_scale,
            "supply_pressure_scale": self.supply_pressure_scale,
        }
        if self.pumps:
            result["pumps"] = {name: item.to_dict()
                               for name, item in self.pumps.items()}
        if self.valves:
            result["valves"] = {name: item.to_dict()
                                for name, item in self.valves.items()}
        if self.cylinders:
            result["cylinders"] = {name: item.to_dict()
                                   for name, item in self.cylinders.items()}
        return result


@dataclass(frozen=True, slots=True)
class ChannelParameters:
    """一个等效作动通道（= 一个机构组）。"""

    name: str
    dof: str
    cylinder: CylinderParameters
    valve: ValveParameters
    #: 该通道挂在哪条供油轨上（``front`` 或 ``rear``）。
    supply: str
    #: 命令 → 正位移的极性。由 ``probe_engineering_authority`` 实测校验，
    #: 不允许只按设计意图填写。
    polarity: float
    kp: float = 0.0
    ki: float = 0.0
    kd: float = 0.0
    kff: float = 0.0
    command_limit: float = 1.0
    #: 该通道在 ±30° 指令下的**参考峰值行程速度**（m/s），由选型脚本按额定转向
    #: 速率算出。供油能力检查必须用它，不能用阀的极限速度（后者含速度余量，
    #: 拿它核算会把泵说成不够用）。
    reference_peak_velocity_m_s: float = 0.0
    notes: str = ""

    def __post_init__(self) -> None:
        if self.supply not in SUPPLY_ORDER:
            raise ParameterError(f"{self.name}: 未知供油轨 {self.supply!r}")
        if self.polarity not in (1.0, -1.0):
            raise ParameterError(f"{self.name}: polarity 必须是 +1 或 -1")
        if self.command_limit <= 0.0:
            raise ParameterError(f"{self.name}: command_limit 必须为正")


@dataclass(frozen=True, slots=True)
class EngineeringHydraulicParameters:
    schema_version: str
    tag: str
    #: 油液体积弹性模量（含气量折减后的等效值，Pa）。
    fluid_bulk_modulus_pa: float
    fluid_density_kg_m3: float
    tank_pressure_pa: float
    #: 两腔预充压力（表压，Pa）。两腔相等 ⇒ 零位无净力，t=0 是真正的平衡点。
    precharge_pressure_pa: float
    #: 节流口压差正则化尺度（Pa）：避免 dP→0 时 sqrt 导数无穷大。
    orifice_pressure_regularisation_pa: float
    supplies: Mapping[str, PumpParameters]
    channels: tuple[ChannelParameters, ...]
    degradation: DegradationParameters = field(default_factory=DegradationParameters)
    assumptions: tuple[str, ...] = ()
    provenance: Mapping[str, str] = field(default_factory=dict)
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.channels:
            raise ParameterError("至少需要一个作动通道")
        for supply in {channel.supply for channel in self.channels}:
            if supply not in self.supplies:
                raise ParameterError(f"通道引用了未定义的供油轨 {supply!r}")
        if self.fluid_bulk_modulus_pa <= 0.0 or self.fluid_density_kg_m3 <= 0.0:
            raise ParameterError("油液参数必须为正")
        unknown_pumps = set(self.degradation.pumps) - set(self.supplies)
        unknown_channels = ((set(self.degradation.valves)
                             | set(self.degradation.cylinders))
                            - set(self.channel_names))
        if unknown_pumps or unknown_channels:
            raise ParameterError(
                f"部件级退化引用未知实例：pumps={sorted(unknown_pumps)}, "
                f"channels={sorted(unknown_channels)}")

    @property
    def supply_names(self) -> tuple[str, ...]:
        ordered = [name for name in SUPPLY_ORDER if name in self.supplies]
        ordered.extend(name for name in self.supplies if name not in ordered)
        return tuple(ordered)

    @property
    def channel_names(self) -> tuple[str, ...]:
        return tuple(channel.name for channel in self.channels)

    def channel(self, name: str) -> ChannelParameters:
        for item in self.channels:
            if item.name == name:
                return item
        raise KeyError(name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "tag": self.tag,
            "fluid_bulk_modulus_pa": self.fluid_bulk_modulus_pa,
            "fluid_density_kg_m3": self.fluid_density_kg_m3,
            "tank_pressure_pa": self.tank_pressure_pa,
            "precharge_pressure_pa": self.precharge_pressure_pa,
            "orifice_pressure_regularisation_pa": self.orifice_pressure_regularisation_pa,
            "supplies": {name: {
                "displacement_m3_per_rad": item.displacement_m3_per_rad,
                "nominal_speed_rad_s": item.nominal_speed_rad_s,
                "relief_pressure_pa": item.relief_pressure_pa,
                "plenum_volume_m3": item.plenum_volume_m3,
                "bulk_modulus_pa": item.bulk_modulus_pa,
                "relief_area_m2": item.relief_area_m2,
                "ideal_flow_l_per_min": item.ideal_flow_m3_s * 60000.0,
            } for name, item in self.supplies.items()},
            "channels": [{
                "name": item.name, "dof": item.dof, "supply": item.supply,
                "polarity": item.polarity,
                "kp": item.kp, "ki": item.ki, "kd": item.kd, "kff": item.kff,
                "command_limit": item.command_limit,
                "reference_peak_velocity_m_s": item.reference_peak_velocity_m_s,
                "notes": item.notes,
                "cylinder": {
                    "area_a_m2": item.cylinder.area_a_m2,
                    "area_b_m2": item.cylinder.area_b_m2,
                    "bore_mm": item.cylinder.bore_mm,
                    "stroke_m": item.cylinder.stroke_m,
                    "stroke_offset_m": item.cylinder.stroke_offset_m,
                    "half_stroke_m": item.cylinder.half_stroke_m,
                    "dead_volume_m3": item.cylinder.dead_volume_m3,
                    "mass_kg": item.cylinder.mass_kg,
                    "viscous_damping_n_s_per_m": item.cylinder.viscous_damping_n_s_per_m,
                    "coulomb_friction_n": item.cylinder.coulomb_friction_n,
                    "end_stop_stiffness_n_per_m": item.cylinder.end_stop_stiffness_n_per_m,
                    "end_stop_damping_n_s_per_m": item.cylinder.end_stop_damping_n_s_per_m,
                    "mass_source": item.cylinder.mass_source,
                },
                "valve": {
                    "maximum_area_m2": item.valve.maximum_area_m2,
                    "discharge_coefficient": item.valve.discharge_coefficient,
                    "lag_time_s": item.valve.lag_time_s,
                    "deadband": item.valve.deadband,
                    "velocity_per_unit_command_m_s":
                        item.valve.velocity_per_unit_command_m_s,
                },
            } for item in self.channels],
            "degradation": self.degradation.to_dict(),
            "assumptions": list(self.assumptions),
            "provenance": dict(self.provenance),
            "notes": self.notes,
        }


def _cylinder(raw: Mapping[str, Any]) -> CylinderParameters:
    return CylinderParameters(
        area_a_m2=float(raw["area_a_m2"]), area_b_m2=float(raw["area_b_m2"]),
        stroke_m=float(raw["stroke_m"]),
        stroke_offset_m=float(raw.get("stroke_offset_m", 0.0)),
        dead_volume_m3=float(raw["dead_volume_m3"]),
        bore_mm=float(raw.get("bore_mm", 0.0) or 0.0), mass_kg=float(raw["mass_kg"]),
        viscous_damping_n_s_per_m=float(raw["viscous_damping_n_s_per_m"]),
        coulomb_friction_n=float(raw["coulomb_friction_n"]),
        end_stop_stiffness_n_per_m=float(raw["end_stop_stiffness_n_per_m"]),
        end_stop_damping_n_s_per_m=float(raw["end_stop_damping_n_s_per_m"]),
        mass_source=str(raw.get("mass_source", ASSUMPTION_TAG)))


def _valve(raw: Mapping[str, Any]) -> ValveParameters:
    return ValveParameters(
        maximum_area_m2=float(raw["maximum_area_m2"]),
        discharge_coefficient=float(raw.get("discharge_coefficient", 0.62)),
        lag_time_s=float(raw.get("lag_time_s", 2.0e-3)),
        deadband=float(raw.get("deadband", 0.0)),
        velocity_per_unit_command_m_s=float(raw.get("velocity_per_unit_command_m_s", 0.0)))


def _pump(raw: Mapping[str, Any]) -> PumpParameters:
    return PumpParameters(
        displacement_m3_per_rad=float(raw["displacement_m3_per_rad"]),
        nominal_speed_rad_s=float(raw["nominal_speed_rad_s"]),
        relief_pressure_pa=float(raw["relief_pressure_pa"]),
        plenum_volume_m3=float(raw["plenum_volume_m3"]),
        bulk_modulus_pa=float(raw["bulk_modulus_pa"]),
        relief_area_m2=float(raw["relief_area_m2"]))


def _degradation(raw: Mapping[str, Any] | None) -> DegradationParameters:
    raw = dict(raw or {})
    known = set(DegradationParameters.__dataclass_fields__)
    unknown = set(raw) - known
    if unknown:
        raise ParameterError(f"未知的退化参数：{sorted(unknown)}")
    pumps = {name: PumpDegradationParameters(**{
        key: float(value) for key, value in dict(item).items()})
        for name, item in dict(raw.pop("pumps", {})).items()}
    valves = {name: ValveDegradationParameters(**{
        key: float(value) for key, value in dict(item).items()})
        for name, item in dict(raw.pop("valves", {})).items()}
    cylinders = {name: CylinderDegradationParameters(**{
        key: float(value) for key, value in dict(item).items()})
        for name, item in dict(raw.pop("cylinders", {})).items()}
    return DegradationParameters(
        **{key: float(value) for key, value in raw.items()},
        pumps=pumps, valves=valves, cylinders=cylinders)


def parameters_from_dict(raw: Mapping[str, Any]) -> EngineeringHydraulicParameters:
    if str(raw.get("schema_version")) != "J1R2.0":
        raise ParameterError(f"不支持的工程液压参数版本：{raw.get('schema_version')!r}")
    return EngineeringHydraulicParameters(
        schema_version="J1R2.0", tag=str(raw.get("tag", TAG)),
        fluid_bulk_modulus_pa=float(raw["fluid_bulk_modulus_pa"]),
        fluid_density_kg_m3=float(raw["fluid_density_kg_m3"]),
        tank_pressure_pa=float(raw["tank_pressure_pa"]),
        precharge_pressure_pa=float(raw["precharge_pressure_pa"]),
        orifice_pressure_regularisation_pa=float(
            raw.get("orifice_pressure_regularisation_pa", 1.0e5)),
        supplies={name: _pump(item) for name, item in raw["supplies"].items()},
        channels=tuple(ChannelParameters(
            name=str(item["name"]), dof=str(item["dof"]),
            cylinder=_cylinder(item["cylinder"]), valve=_valve(item["valve"]),
            supply=str(item["supply"]), polarity=float(item.get("polarity", 1.0)),
            kp=float(item.get("kp", 0.0)), ki=float(item.get("ki", 0.0)),
            kd=float(item.get("kd", 0.0)), kff=float(item.get("kff", 0.0)),
            command_limit=float(item.get("command_limit", 1.0)),
            reference_peak_velocity_m_s=float(
                item.get("reference_peak_velocity_m_s", 0.0)),
            notes=str(item.get("notes", ""))) for item in raw["channels"]),
        degradation=_degradation(raw.get("degradation")),
        assumptions=tuple(raw.get("assumptions", ())),
        provenance=dict(raw.get("provenance", {})),
        notes=str(raw.get("notes", "")))


def load_parameters(path: str | Path) -> EngineeringHydraulicParameters:
    source = Path(path)
    return parameters_from_dict(json.loads(source.read_text(encoding="utf-8")))


def save_parameters(parameters: EngineeringHydraulicParameters, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(parameters.to_dict(), ensure_ascii=False, indent=2),
                      encoding="utf-8")
    return target


def with_degradation(parameters: EngineeringHydraulicParameters,
                     **updates: Any) -> EngineeringHydraulicParameters:
    """返回一份只改了退化参数的副本（供以后的退化/寿命模块使用）。"""
    return replace(parameters, degradation=replace(parameters.degradation, **updates))


def with_component_degradation(
        parameters: EngineeringHydraulicParameters, *,
        pumps: Mapping[str, PumpDegradationParameters] | None = None,
        valves: Mapping[str, ValveDegradationParameters] | None = None,
        cylinders: Mapping[str, CylinderDegradationParameters] | None = None,
        ) -> EngineeringHydraulicParameters:
    """以内存副本注入独立部件退化；健康参数对象和 JSON 文件均不修改。"""
    degradation = replace(
        parameters.degradation,
        pumps=dict(parameters.degradation.pumps if pumps is None else pumps),
        valves=dict(parameters.degradation.valves if valves is None else valves),
        cylinders=dict(parameters.degradation.cylinders
                       if cylinders is None else cylinders))
    return replace(parameters, degradation=degradation)


def design_load_pressure(parameters: EngineeringHydraulicParameters,
                         supply: str, fraction: float = 0.7) -> float:
    """设计负载压力 = 供油压力上限的给定比例（阀仍保留控制余量的工作点）。"""
    pump = parameters.supplies[supply]
    return fraction * pump.relief_pressure_pa


def orifice_flow_gain(parameters: EngineeringHydraulicParameters,
                      valve: ValveParameters, delta_p_pa: float) -> float:
    """``Q / (A_max·u)`` 在给定压差下的值（m/s 每单位面积），用于选型核算。"""
    if delta_p_pa <= 0.0:
        return 0.0
    return (valve.discharge_coefficient * parameters.degradation.valve_flow_coefficient_scale
            * math.sqrt(2.0 / parameters.fluid_density_kg_m3) * math.sqrt(delta_p_pa))
