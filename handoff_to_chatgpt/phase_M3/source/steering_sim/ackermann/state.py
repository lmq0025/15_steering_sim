"""机构状态的最小公共接口（PHASE M3）。

``PhaseM1Model``（甲方原始结构）与 ``RedesignedAckermannModel``（M3 工程设计
提案）都通过 ``mechanism_state(q_values)`` 返回本结构。J0 集成层只依赖这一接口，
因此两套机构可以共用同一套联合仿真循环、同一套地面载荷换算与同一套雅可比。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True, slots=True)
class MechanismState:
    """一个机构坐标下的机构状态。

    ``cylinder_stroke_m`` 的键固定为 ``front_group_1`` 与 ``axle{4,5,6}_{A,B}``，
    全部为**相对零位的行程**（m）。
    """

    q_rad: Mapping[str, float]
    wheel_angles_rad: Mapping[str, float]
    wheel_angles_deg: Mapping[str, float]
    cylinder_stroke_m: Mapping[str, float]
    #: J0 单通道使用的**等效代表行程**（m，相对零位），键为 ``axle{4,5,6}`` 与
    #: ``front``。它不是某一只缸的几何位移：后桥是"对称双缸推程缸"位移
    #: （见 :func:`steering_sim.ackermann.redesign.representative_stroke_m`）。
    representative_stroke_m: Mapping[str, float]
    max_residual_m: float
    condition_number: float
    singular: bool
    third_axle_max_abs_deg: float
    #: 距最近死点的最小传动角（度）；甲方原始机构不提供该量时取 NaN。
    min_toggle_margin_deg: float = float("nan")
