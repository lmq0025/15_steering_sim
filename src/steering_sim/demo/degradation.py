"""D1 退化接口兼容层。

正式参数类型唯一位于 :mod:`steering_sim.hydraulics_engineering.parameters`。
本模块保留历史 GUI/CLI 的导入路径，但不再定义同名占位类，也不再引用 L1-Fast。
"""
from __future__ import annotations

from typing import Any

from steering_sim.hydraulics_engineering import (
    CylinderDegradationParameters, DegradationParameters,
    PumpDegradationParameters, ValveDegradationParameters,
    with_component_degradation, with_degradation)


class DegradationNotImplementedError(NotImplementedError):
    """保留历史异常类型；D1 不包含 RUL 和质量评分。"""


INTERFACE_MAP = {
    "pumps.front/rear":
        "ENGINEERING_HYDRAULIC_V1 两条供油轨：容积效率与压差内泄漏",
    "valves.<channel>":
        "ENGINEERING_HYDRAULIC_V1 四通道：P→T 守恒内泄漏、流量系数、响应时间",
    "cylinders.<channel>":
        "ENGINEERING_HYDRAULIC_V1 四通道：A/B 腔间内泄漏与摩擦",
}


def describe_interfaces() -> dict[str, Any]:
    return {
        # 旧 GUI 入口询问的是“寿命/RUL/质量评分”，这些仍按原契约保留。
        "status": "RESERVED",
        "implemented": False,
        "d1_task_spectrum_status": "IMPLEMENTED",
        "formal_parameter_type":
            "steering_sim.hydraulics_engineering.parameters.DegradationParameters",
        "parameters": DegradationParameters().to_dict(),
        "interface_map": dict(INTERFACE_MAP),
        "component_instances": {
            "pumps": ["front", "rear"],
            "valves": ["channel_front", "channel_rear_1",
                       "channel_rear_2", "channel_rear_3"],
            "cylinders": ["channel_front", "channel_rear_1",
                          "channel_rear_2", "channel_rear_3"],
        },
        "note": "确定性 D1 任务谱退化已实现；此旧 GUI 页尚不重写。",
        "disclaimer": "D1 不输出寿命、剩余寿命或质量评分；这些功能留到 D3。",
    }


def predict_life(*_args: Any, **_kwargs: Any) -> Any:
    raise DegradationNotImplementedError("D1 只预测 30 天参数演化，不输出 RUL。")


def assess_quality(*_args: Any, **_kwargs: Any) -> Any:
    raise DegradationNotImplementedError("质量评分不在 D1 范围内。")


__all__ = [
    "CylinderDegradationParameters", "DegradationNotImplementedError",
    "DegradationParameters", "INTERFACE_MAP", "PumpDegradationParameters",
    "ValveDegradationParameters", "assess_quality", "describe_interfaces",
    "predict_life", "with_component_degradation", "with_degradation",
]
