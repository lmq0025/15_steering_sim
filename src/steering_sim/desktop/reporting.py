"""Chinese comprehensive report assembled only from modules actually executed."""
from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any, Mapping


FACTOR_CN = {
    "pump:rail_front": "前供油轨齿轮泵", "pump:rail_rear": "后供油轨齿轮泵",
    "valve:channel_front": "前通道转向阀", "valve:channel_rear_1": "后通道1转向阀",
    "valve:channel_rear_2": "后通道2转向阀", "valve:channel_rear_3": "后通道3转向阀",
    "cylinder:channel_front": "前通道等效液压缸",
    "cylinder:channel_rear_1": "后通道1等效液压缸",
    "cylinder:channel_rear_2": "后通道2等效液压缸",
    "cylinder:channel_rear_3": "后通道3等效液压缸",
}


def _failure_reason_cn(value: object) -> str:
    text = str(value)
    for key, name in FACTOR_CN.items():
        text = text.replace(key, name)
    for key, name in {"response_lag": "响应迟滞", "internal_leakage": "内泄漏",
                      "mechanical_loss": "机械损失", "friction": "摩擦增大"}.items():
        text = text.replace(key, name)
    return text.replace(" damage ", "：损伤 ").replace("hard limit", "硬限值").replace(">=", "≥")


def build_report(project: Mapping[str, Any], results: Mapping[str, Any],
                 provenance: Mapping[str, Any]) -> str:
    lines = ["# 电液转向系统质量性能评估与预测综合报告", "",
             f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
             f"- 工程名称：{project.get('name', '未命名工程')}",
             "- 正式机械模型：`ENGINEERING_STEERING_MODEL`",
             "- 正式液压模型：`ENGINEERING_HYDRAULIC_V1`", ""]
    lines += ["## 1. 任务输入说明", "",
              f"- 任务谱：`{project.get('spectrum_path') or '未选择'}`",
              f"- 初始状态：`{project.get('initial_state', '未设置')}`", ""]
    if "simulation" in results:
        item = results["simulation"]
        response = item.get("response", {})
        system_settled = response.get("system_settled_s")
        system_settled_text = (response.get("system_status", "—")
                               if system_settled is None else f"{system_settled:.3f} s")
        lines += ["## 2. 机械—液压—控制联合仿真", "",
                  f"- 计算完成：{item.get('calculation_success')}",
                  f"- 液压跟踪达标：{item.get('tracking_pass')}",
                  f"- 目标轨迹可行：{item.get('trajectory_feasible')}",
                  f"- 动态计算耗时：{item.get('runtime_s', 0):.3f} s",
                  f"- 指令类型：{item.get('command_type', 'step')}",
                  f"- 指令完成时间：{response.get('command_completion_s', '—')} s",
                  f"- 十二轮共同稳态时间：{response.get('all_wheels_settled_s')}",
                  f"- 四组等效作动通道共同稳态时间：{response.get('all_cylinders_settled_s')}",
                  f"- 整机共同稳态时间：{system_settled_text}", ""]
    if "degradation" in results:
        item = results["degradation"]
        lines += ["## 3. 关键部件退化结果", "",
                  "- 对象：2台齿轮泵、4个转向阀、4组等效液压缸。",
                  "- 模式：泵内泄漏/机械损失、阀内泄漏/响应迟滞、缸内泄漏/摩擦增长。",
                  f"- 工况风险条数：{len(item.get('risks', []))}",
                  "- 标记：`ENGINEERING_DESIGN_ASSUMPTION / PENDING_CLIENT_CALIBRATION`", ""]
    if "quality" in results:
        item = results["quality"]
        lines += ["## 4. 当前质量评价", "",
                  f"- 整车质量等级：`{item.get('grade')}`",
                  f"- 场景性质：{item.get('natural_or_sensitivity')}",
                  "- 指标来自D2标准工况真实22状态动态仿真。", ""]
    if "rul" in results:
        item = results["rul"]
        summary = item.get("summary", {})
        quality = item.get("quality")
        if quality is not None and not quality.empty:
            start_grade = quality.iloc[0].get("rated_quality_grade", "—")
            end_grade = quality.iloc[-1].get("rated_quality_grade", "—")
            lines += ["## 5. 未来任务循环质量变化", "",
                      f"- 首个真实动力学检查点等级：`{start_grade}`",
                      f"- 寿命临界检查点等级：`{end_grade}`",
                      "- 等级来自D2真实22状态检查点；循环间退化由D3快速模型推进。", ""]
        lines += ["## 6. 剩余任务循环结果", "",
                  f"- 预测状态：`{summary.get('prediction_status')}`",
                  f"- 剩余完整30天任务：{summary.get('remaining_complete_30day_cycles')}",
                  f"- 首次越限任务循环：{summary.get('first_failure_cycle')}",
                  f"- 首次越限工况段：{summary.get('first_failure_segment_id')}",
                  f"- 限制部件：{', '.join(FACTOR_CN.get(x, x) for x in (summary.get('limiting_factors') or []))}",
                  f"- 原因：{'；'.join(_failure_reason_cn(x) for x in (summary.get('failure_reasons') or []))}",
                  "- 循环内记录时刻是工况段末首次越限检测时刻，不是段内精确失效瞬间。",
                  "- Monte Carlo为快速近似载荷推进，并非每条随机路径都执行完整22状态验证。", ""]
    missing = [name for name, title in (("simulation", "联合仿真"),
                                         ("degradation", "部件退化"),
                                         ("quality", "质量评估"),
                                         ("rul", "剩余寿命")) if name not in results]
    if missing:
        lines += ["## 7. 未执行模块", "",
                  "以下模块本工程尚未执行，报告没有使用历史示例结果填充：",
                  *[f"- {name}" for name in missing], ""]
    lines += ["## 8. 工况风险与适用边界", "",
              "- 高速大转角可能超出附着极限；该风险与液压退化故障分开。",
              "- 退化率、质量阈值、硬失效阈值和随机分布均待甲方试验标定。",
              "- 当前结果用于工程趋势、接口和物理反馈验证，不是实车认证寿命。", "",
              "## 9. 可追溯信息", "", "```json",
              json.dumps(dict(provenance), ensure_ascii=False, indent=2), "```", ""]
    return "\n".join(lines)


def write_report(path: str | Path, project: Mapping[str, Any],
                 results: Mapping[str, Any], provenance: Mapping[str, Any]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(build_report(project, results, provenance), encoding="utf-8")
    return target
