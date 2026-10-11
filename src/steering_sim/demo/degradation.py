"""退化预测与质量评估的**接口预留**（本轮不实现算法）。

本模块只做三件事：

1. 定义未来退化建模可以调节的参数（全部默认 1.0 = 健康），
2. 说明每个参数对应现有模型中的哪个物理量，
3. 明确拒绝输出任何尚未实现的寿命或质量预测值。

因此界面可以显示"性能退化与质量评估（待开发）"，但绝不允许出现一个看起来
像计算结果、实际是占位符的数字。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any, Mapping


class DegradationNotImplementedError(NotImplementedError):
    """在任何尚未实现的预测路径上显式失败，而不是返回占位数值。"""


@dataclass(frozen=True, slots=True)
class DegradationParameters:
    """退化因子集合。1.0 表示与当前标定一致的健康状态。

    这些因子未来会作为**乘性修正**施加到对应的物理参数上；本层只保存数值，
    不改变被控对象的默认参数。
    """

    # 泵
    pump_volumetric_efficiency: float = 1.0
    pump_displacement: float = 1.0
    # 阀
    valve_discharge_coefficient: float = 1.0
    valve_response_speed: float = 1.0
    valve_leakage: float = 1.0
    # 液压缸
    cylinder_internal_leakage: float = 1.0
    cylinder_external_leakage: float = 1.0
    cylinder_friction: float = 1.0
    cylinder_damping: float = 1.0
    # 控制
    controller_proportional_gain: float = 1.0
    controller_integral_gain: float = 1.0
    controller_derivative_gain: float = 1.0
    controller_command_limit: float = 1.0

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if value <= 0.0:
                raise ValueError(f"退化因子 {name} 必须为正（1.0 = 健康）")

    @property
    def is_healthy(self) -> bool:
        return all(value == 1.0 for value in asdict(self).values())

    def scaled(self, **factors: float) -> "DegradationParameters":
        return replace(self, **factors)


#: 每个退化因子在现有模型中的落点（供后续实现直接对照）。
INTERFACE_MAP: Mapping[str, str] = {
    "pump_volumetric_efficiency":
        "hydraulics_lumped.pump.pump_flow —— 容积效率修正泵流量",
    "pump_displacement":
        "hydraulics_lumped.parameters.PumpParameters.displacement",
    "valve_discharge_coefficient":
        "hydraulics_lumped.valve.characteristic_orifice_flow 的流量系数",
    "valve_response_speed":
        "hydraulics_lumped.valve 的 SC_1 阀口开度曲线（响应时间常数）",
    "valve_leakage":
        "hydraulics_lumped.valve 四孔口的零位泄漏面积",
    "cylinder_internal_leakage":
        "hydraulics_lumped.actuator 的 A/B 腔间泄漏（当前为 0）",
    "cylinder_external_leakage":
        "hydraulics_lumped.actuator 的腔外泄漏",
    "cylinder_friction":
        "hydraulics_lumped.actuator 的库仑摩擦力",
    "cylinder_damping":
        "hydraulics_lumped.actuator 的粘性阻尼系数",
    "controller_proportional_gain": "control.pid.PIDController.kp（四通道）",
    "controller_integral_gain": "control.pid.PIDController.ki（四通道）",
    "controller_derivative_gain": "control.pid.PIDController.kd（四通道）",
    "controller_command_limit": "j0_coupling.config.ChannelControlConfig.command_limit",
}

#: 预留的后续模块位置。
RESERVED_MODULES = ("steering_sim.demo.degradation",
                    "steering_sim.demo.quality_assessment",
                    "steering_sim.demo.prediction")


def describe_interfaces() -> dict[str, Any]:
    """给界面用：说明接口现状，不产生任何数值预测。"""
    healthy = DegradationParameters()
    return {
        "status": "RESERVED",
        "implemented": False,
        "parameters": asdict(healthy),
        "interface_map": dict(INTERFACE_MAP),
        "reserved_modules": list(RESERVED_MODULES),
        "note": ("本轮不开发退化预测与质量评估算法。这里只预留参数接口；"
                 "健康工况下所有因子保持 1.0，不改变任何现有默认值。"),
        "disclaimer": "本平台当前不输出寿命、剩余寿命或质量评分。",
    }


def predict_life(*_args: Any, **_kwargs: Any) -> Any:
    """未实现的寿命预测入口：显式失败，绝不返回占位数值。"""
    raise DegradationNotImplementedError(
        "本阶段（PHASE J0-DEMO）不包含寿命预测；接口已预留，算法未实现。")


def assess_quality(*_args: Any, **_kwargs: Any) -> Any:
    """未实现的质量评估入口：显式失败，绝不返回占位数值。"""
    raise DegradationNotImplementedError(
        "本阶段（PHASE J0-DEMO）不包含质量评估；接口已预留，算法未实现。")
