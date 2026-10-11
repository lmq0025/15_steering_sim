"""PHASE J0-DEMO：电液转向系统联合仿真平台（中文本地演示）。

本包只做**编排与展示**，不重新实现任何被控对象：

* 液压 —— ``steering_sim.hydraulics_lumped``（L1-Fast V1，4 通道 16 状态）
* 机械 —— ``mechanics_ackermann_v2``（M1，六桥十二轮四自由度）
* 联合 —— ``steering_sim.j0_coupling``（10 ms 控制 / 0.5 ms 液压）
* 控制器 —— 复用的四通道 ``PIDController``

界面、结果导出与退化/质量评估接口都在此层，方便后续替换而不动模型。
"""
from .scenario import (CUSTOMER_LIMITS, ENGINEERING_DEFAULTS, VERIFIED_LIMITS,
                       DemoScenario, Preset, preset_scenarios)
from .assessment import (ConsistencyReport, MechanismAssessment,
                         PreflightAssessment, SupplyAssessment,
                         assess_mechanism, assess_preflight, assess_supply,
                         check_run_consistency)
from .service import DemoResult, DemoService, DemoServiceError

__all__ = [
    "CUSTOMER_LIMITS", "VERIFIED_LIMITS", "ENGINEERING_DEFAULTS",
    "DemoScenario", "Preset", "preset_scenarios",
    "MechanismAssessment", "SupplyAssessment", "PreflightAssessment",
    "ConsistencyReport", "assess_mechanism", "assess_supply",
    "assess_preflight", "check_run_consistency",
    "DemoService", "DemoResult", "DemoServiceError",
]
