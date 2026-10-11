"""PHASE M2：六桥阿克曼转向纠偏与全工况覆盖。

* :mod:`ideal`      —— 低速理想阿克曼角（共同 ICR，独立实现）
* :mod:`linkage`    —— 真实闭链装配分支追踪与可解范围探测
* :mod:`equivalent` —— ``ENGINEERING_EQUIVALENT_ACKERMANN`` 工程等效模式
* :mod:`assessment` —— 五类状态分离 + 整车动力学适用性
* :mod:`cases`      —— 甲方全工况表批量计算与 CSV/XLSX 模板
"""
from .ideal import (CHECK_ANGLES_DEG, IdealAckermann, IdealAckermannError,
                    ideal_ackermann, sweep_ideal)
from .linkage import (AxleLinkageReport, LinkageAudit, SideBranch, audit_linkage,
                      build_four_bars, trace_side)

__all__ = [
    "CHECK_ANGLES_DEG", "IdealAckermann", "IdealAckermannError",
    "ideal_ackermann", "sweep_ideal",
    "AxleLinkageReport", "LinkageAudit", "SideBranch", "audit_linkage",
    "build_four_bars", "trace_side",
]
