"""Status-aware Chinese RUL text; presentation never infers a new lifetime."""
from __future__ import annotations

from typing import Any, Mapping


def rul_outcome_text(summary: Mapping[str, Any]) -> dict[str, str]:
    """Distinguish component detections, sparse quality brackets and unknowns.

    Old saved results lack the explicit quality interval, so their recorded
    safe-checkpoint lower bound and failure-checkpoint upper bound are used.
    Neither bound is interpolated into a segment or an exact failure instant.
    """
    status = summary.get("prediction_status")
    remaining = summary.get("remaining_complete_30day_cycles")
    cycle = summary.get("first_failure_cycle")
    if status == "FAILURE_REACHED":
        segment = summary.get("first_failure_segment_id")
        day = summary.get("first_failure_day_in_cycle")
        cycle_text = "首次越限循环未记录" if cycle is None else f"第{cycle}次任务"
        if segment and segment != "DYNAMIC_CHECKPOINT":
            detection = f"{segment}段末检测"
            if day is not None:
                detection += f"；第{float(day):.6f}天"
            detail = "记录时刻是段末检测时刻，不是段内精确失效瞬间。"
        else:
            detection = "检查点检测，未记录可定位的任务段"
            detail = "仅显示已记录的检测分辨率，不推断段内失效时刻。"
        return dict(
            complete_value="未记录" if remaining is None else f"{remaining} 次",
            complete_note="从当前状态起、首次越限前可完整执行的任务数",
            failure_value=cycle_text, failure_note=detection,
            explanation=f"已检测到失效阈值越限。{cycle_text}，{detection}。{detail}",
            level="danger", banner_level="warning")
    if status == "FAILURE_BRACKETED":
        interval = summary.get("system_quality_failure_cycle_interval")
        if not isinstance(interval, (list, tuple)) or len(interval) != 2:
            interval = (remaining, cycle)
        lower, upper = interval
        bounds_known = lower is not None and upper is not None
        if bounds_known and lower == upper == 0:
            detection = "第0次初始质量检查已达到系统终止条件"
        elif bounds_known:
            detection = f"首次系统质量越限位于第{lower}～{upper}次检查区间（{lower}, {upper}]"
        else:
            detection = "已确认系统质量越限区间，区间端点记录不完整"
        return dict(
            complete_value="已检安全下界未记录" if lower is None else f"已检安全下界 {lower} 次",
            complete_note="安全检查点下界，不是精确求得的剩余完整任务次数",
            failure_value="质量检查点区间",
            failure_note=detection,
            explanation=detection + "；中间循环未逐次动态验证，未确定具体任务段或段内时刻。",
            level="warning", banner_level="warning")
    if status == "NOT_REACHED_WITHIN_HORIZON":
        return dict(
            complete_value="预测范围内未失效",
            complete_note="剩余寿命尚未确定；不能把预测上限当作真实寿命",
            failure_value="未检测到越限",
            failure_note="仅限已计算范围和实际执行的检查点",
            explanation="预测范围内未达到失效阈值；未检查的中间系统质量不作已验证结论，预测上限不是真实剩余寿命。",
            level="normal", banner_level="info")
    return dict(
        complete_value="无法确定",
        complete_note="数值或模型验证不足，不能确定剩余完整任务次数",
        failure_value="尚无法判断",
        failure_note="不能据此宣称未越限或给出精确失效时刻",
        explanation="数值或模型能力不足，无法判断；未形成完整寿命结论，请查看计算详情。",
        level="danger", banner_level="error")
