"""PHASE J1-R2：轻量化工程电液伺服模型（``ENGINEERING_HYDRAULIC_V1``）。

这是 J1-R2 起的**唯一正式液压运行模型**，替代 L1-Fast 承担闭环仿真。旧
``hydraulics_lumped`` L1-Fast 只作为历史证据保留。

设计目标（J1-R2 任务书第三节）：

* 经典**阀控对称双腔液压缸**，每通道核心状态 ``pA, pB, x, v``（外加一个阀芯
  一阶响应状态），四个等效作动通道；
* 两条**共用恒压供油轨**（前组一条、后三组一条），带泵、蓄能器容积与溢流阀；
  泵排量、供压与压力上限全部可配置，**不使用无限压力或无限流量**；
* 四通道同时运动时按**共用供油总量**核算，不各缸独立计算；
* ``x_actual`` 与 ``v_actual`` 一律由微分方程积分产生，绝不赋值为目标行程；
* 退化接口统一预留（泵容积效率/内泄漏、阀流量系数/死区/响应、缸内泄漏/摩擦）。
"""
from __future__ import annotations

from .authority import (EngineeringAuthority, probe_engineering_authority)
from .model import (EngineeringHydraulicSystem, EngineeringHydraulicError,
                    evaluate_hydraulic_engineering, state_layout)
from .parameters import (ASSUMPTION_TAG, TAG, ChannelParameters,
                         CylinderDegradationParameters, CylinderParameters,
                         DegradationParameters, EngineeringHydraulicParameters,
                         ParameterError, PumpDegradationParameters, PumpParameters,
                         ValveDegradationParameters, ValveParameters,
                         load_parameters, parameters_from_dict, save_parameters,
                         with_component_degradation, with_degradation)

__all__ = [
    "ASSUMPTION_TAG", "TAG", "ChannelParameters",
    "CylinderDegradationParameters", "CylinderParameters",
    "DegradationParameters", "EngineeringAuthority",
    "EngineeringHydraulicError", "EngineeringHydraulicParameters",
    "EngineeringHydraulicSystem", "ParameterError", "PumpDegradationParameters",
    "PumpParameters", "ValveDegradationParameters", "ValveParameters",
    "evaluate_hydraulic_engineering", "load_parameters",
    "parameters_from_dict", "probe_engineering_authority", "save_parameters",
    "state_layout", "with_component_degradation", "with_degradation",
]
