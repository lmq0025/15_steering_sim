"""Chinese comprehensive report assembled only from modules actually executed."""
from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any, Mapping
from .localization import cn, chinese_frame
from .rul_presentation import rul_outcome_text

def _number(value):
    try:
        number=float(value)
        import math
        return f'{number:.2f}' if math.isfinite(number) else '—'
    except (ValueError,TypeError):return '—'


def _table(frame):
    frame=chinese_frame(frame)
    def fmt(value):
        if value is None: return '—'
        if isinstance(value,float): return '—' if value!=value else f'{value:.6g}'
        return str(value).replace('|','／')
    header='| '+' | '.join(str(c) for c in frame.columns)+' |'
    return '\n'.join([header,'| '+' | '.join(['---']*len(frame.columns))+' |']+
        ['| '+' | '.join(fmt(v) for v in row)+' |' for row in frame.itertuples(index=False,name=None)])


FACTOR_CN = {
    "pump:rail_front": "前供油轨齿轮泵", "pump:rail_rear": "后供油轨齿轮泵",
    "valve:channel_front": "前通道转向阀", "valve:channel_rear_1": "后通道1转向阀",
    "valve:channel_rear_2": "后通道2转向阀", "valve:channel_rear_3": "后通道3转向阀",
    "cylinder:channel_front": "前通道等效液压缸",
    "cylinder:channel_rear_1": "后通道1等效液压缸",
    "cylinder:channel_rear_2": "后通道2等效液压缸",
    "cylinder:channel_rear_3": "后通道3等效液压缸",
}
FACTOR_CN={key:cn(key) for key in FACTOR_CN}


def _failure_reason_cn(value: object) -> str:
    text = str(value)
    for key, name in FACTOR_CN.items():
        text = text.replace(key, name)
    for key, name in {"response_lag": "响应迟滞", "internal_leakage": "内泄漏",
                      "mechanical_loss": "机械损失", "friction": "摩擦增大"}.items():
        text = text.replace(key, name)
    return cn(text.replace(" damage ", "：损伤 ").replace("hard limit", "硬限值").replace(">=", "≥"))


def build_report(project: Mapping[str, Any], results: Mapping[str, Any],
                 provenance: Mapping[str, Any]) -> str:
    lines = ["# 电液转向系统质量性能评估与预测综合报告", "",
             f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
             f"- 工程名称：{project.get('name', '未命名工程')}",
             "- 正式机械模型：`ENGINEERING_STEERING_MODEL`",
             "- 正式液压模型：`ENGINEERING_HYDRAULIC_V1`", ""]
    lines += ["## 1. 任务输入说明", "",
              f"- 任务谱：`{project.get('spectrum_path') or '未选择'}`",
              f"- 初始状态：{cn(project.get('initial_state', '未设置'))}", ""]
    if "simulation" in results and results["simulation"].get("kind") == "batch":
        item = results["simulation"]
        lines += ["## 2. 准稳态作动能力估计", "",
                  "- 计算方式：`FAST_BATCH_ESTIMATE`，不是完整22状态动态仿真。",
                  f"- 实际结果数：{item.get('row_count', len(item.get('rows', [])))}组。",
                  f"- 电脑计算耗时：{_number(item.get('runtime_s'))} s",
                  "- 本结果不包含动态到位、稳态时间或十二轮回放。", ""]
        names = {"target_outer_angle_deg": ("一桥外轮转角", "°"),
                 "speed_kmh": ("车速", "km/h"),
                 "friction_coefficient": ("附着系数", "无量纲")}
        for field, values in item.get("grids", {}).items():
            name, unit = names.get(field, (cn(field), ""))
            lines += [f"- {name}网格（{unit}）：" + "、".join(f"{value:g}" for value in values)]
        lines += ["", "- 本次结果目录：" + item.get("output_dir", "未记录"), ""]
    elif "simulation" in results:
        item = results["simulation"]
        response = item.get("response", {})
        system_settled = response.get("system_settled_s")
        system_settled_text = (response.get("system_status", "—")
                               if system_settled is None else f"{system_settled:.3f} s")
        lines += ["## 2. 机械—液压—控制联合仿真", "",
                  f"- 数据性质：{'历史积分结果回放，非本次新积分' if item.get('provenance_kind')=='HISTORICAL_REPLAY' else '本次实际计算'}",
                  f"- 计算完成：{cn(item.get('calculation_success'))}",
                  f"- 液压跟踪达标：{cn(item.get('tracking_pass'))}",
                  f"- 目标轨迹可行：{cn(item.get('trajectory_feasible'))}",
                  f"- 联算核心耗时（含参考准备及结果整理）：{item.get('runtime_s', 0):.3f} s",
                  f"- 完整服务电脑计算耗时：{item.get('service_runtime_s',item.get('runtime_s',0)):.3f} s",
                  f"- 模拟总时长：{item.get('simulation_horizon_s','—')} s",
                  f"- 指令类型：{'斜坡输入' if item.get('command_type') == 'ramp' else '阶跃兼容模式'}",
                  f"- 每度转向时间：{item.get('seconds_per_degree', '—')} s/°",
                  f"- 指令完成时间：{response.get('command_completion_s', '—')} s",
                  f"- 十二轮共同稳态时间：{_number(response.get('all_wheels_settled_s'))} s",
                  f"- 四组等效作动通道共同稳态时间：{_number(response.get('all_cylinders_settled_s'))} s",
                  f"- 整机共同稳态时间：{system_settled_text}", ""]
        if response:
            lines += [f"- 指令结束后额外收敛时间：{_number(response.get('additional_convergence_s'))} s",
                      "- 三桥固定零位，无需转向到位；仍参与共同稳态的静态约束检查。", ""]
            for key,title in [('wheel_table','十二轮到位与稳态'),('cylinder_table','四组等效作动通道响应')]:
                if key in response:
                    lines += [f'### {title}', '',_table(response[key]),'']
            criteria=response.get('criteria')
            if criteria is not None:
                lines += [f'判据：轮角±{criteria.wheel_angle_tolerance_deg}°，角速度≤{criteria.wheel_speed_threshold_deg_s}°/s；位移±{criteria.cylinder_position_tolerance_m*1000} mm，活塞速度≤{criteria.piston_speed_threshold_m_s*1000} mm/s；连续观察{criteria.settled_observation_s}秒。','']
        if item.get('input_scenario'):
            lines += ['本次实际计算输入（不是计算后重新编辑的控件值）：','',
                      '```json',json.dumps(item['input_scenario'],ensure_ascii=False,indent=2),'```','']
    if "degradation" in results:
        item = results["degradation"]
        lines += ["## 3. 关键部件退化结果", "",
                  "- 对象：2台齿轮泵、4个转向阀、4组等效液压缸。",
                  "- 模式：泵内泄漏/机械损失、阀内泄漏/响应迟滞、缸内泄漏/摩擦增长。",
                  f"- 工况风险条数：{len(item.get('risks', []))}",
                  ""]
        if 'statistics' in item:
            import pandas as pd
            from .degradation_cards import final_component_summary
            center = project.get('page_inputs',{}).get('degradation',{}).get('center','mean')
            cards, _ = final_component_summary(item, center)
            lines += ['### 第30天部件摘要','']
            for kind, card in cards.items():
                lines += [f'- {cn(kind)}：{card.value}；{card.note.replace(chr(10), "；")}']
            lines += ['']
            lines += [f"- 预测总时长：{item['curve_frame'].day.iloc[-1]:g}天；初态：{cn(item['initial_state_source'])}。",
                      f"- 本次真实随机路径数：{item['sample_count']}；随机种子：{item['random_seed']}；包含统计与导出的计算耗时：{item['runtime_s']:.3f}秒。",
                      f"- 当前图形采用中央{project.get('page_inputs',{}).get('degradation',{}).get('interval',90)}%逐时刻预测区间；表中分位数按列名报告，不是均值置信区间。",
                      '- 每条路径先映射成物理参数，再计算该参数分位数；效率下降时不复用损伤上下界。',
                      '- 条件载荷暴露沿用D3初态修正任务谱，路径独立推进二十状态；温度和污染为确定输入，未显式模拟随机环境。',
                      '- 非线性状态反馈及上限截断会改变总体均值，未强制缩放随机数据。',
                      f"- 固定参考压差 {item['reference_conditions']['pressure_pa']/1e6:g}MPa，油温40℃，泵额定转速，缸参考速度0.01m/s。",'']
            if item.get('provenance'):
                lines += ['- 本次退化输入任务谱SHA256：'+item['provenance'].get('spectrum_sha256','未记录'),'']
            curves=item['curve_frame']; rows=[]
            for metric in [c for c in curves if c!='day']:
                row={'metric':cn(metric),'unit':item['units'][metric]}
                for day in (0,10,20,30):
                    chosen=curves.loc[curves.day>=day-1e-9]
                    row[f'第{day}天']=float(chosen.iloc[0][metric]) if not chosen.empty else None
                rows.append(row)
            lines += ['### 确定性参考：二十状态与实际物理参数检查点','', '以下各日使用该日及之后首个真实段末记录；未对段内状态插值。随机均值和分位数另列，不强制等于该参考。',_table(pd.DataFrame(rows)),'']
            if item['sample_count']:
                last=item['statistics']; last=last.loc[last.day==last.day.max(),['metric','unit','mean','p05','p50','p95','std']]
                lines += ['### 第30天随机退化预测分布','',_table(last),'']
            for kind,modes in item['models'].items():
                for mode,cfg in modes.items():
                    lines += [f"- {cn(kind)}／{cn(mode)}：退化率{cfg['rate']:g}／{cn(cfg['exposure_unit'])}，α={cfg['state_factor_alpha']}，硬失效损伤={cfg['failure_damage']}；驱动量：{'、'.join(cn(v) for v in cfg['drivers'])}。"]
            lines += ['', '方程：dD/dE = rate × (1 + αD)，确定性采用解析推进；Gamma以当前状态的确定性损伤增量为条件期望，采样后遵守损伤上限。雨流仅用于缸摩擦增长模式中的载荷反转项，不用于所有磨损模式。','']
    if "quality" in results:
        item = results["quality"]
        lines += ["## 4. 当前质量评价", "",
                  f"- 整车质量等级：{cn(item.get('grade'))}",
                  f"- 场景性质：{item.get('natural_or_sensitivity')}",
                  f"- 本次实际评估状态：{cn(item.get('source','未记录'))}",
                  "- 指标来自D2标准工况真实22状态动态仿真。", ""]
        if 'comparison_frame' in item:
            lines+=['### 同一标准工况健康/当前指标','',_table(item['comparison_frame']),'',
                    '- 两套状态使用相同目标、车速、附着、轴荷、控制器及数值设置；未重新整定控制器。',
                    '- 原始成对动态与缓存条件：'+item.get('output_dir','未记录'),'']
    if "rul" in results:
        item = results["rul"]
        summary = item.get("summary", {})
        quality = item.get("quality")
        if quality is not None and not quality.empty:
            start_grade = quality.iloc[0].get("rated_quality_grade", "—")
            end_grade = quality.iloc[-1].get("rated_quality_grade", "—")
            lines += ["## 5. 未来任务循环质量变化", "",
                      f"- 首个真实动力学检查点等级：{cn(start_grade)}",
                      f"- 末个真实动力学检查点等级：{cn(end_grade)}",
                      "- 等级来自D2真实22状态检查点；循环间退化由D3快速模型推进。", ""]
            cycles = [int(value) for value in quality.mission_cycle]
            lines += [f'- 本次实际执行{len(cycles)}个22状态动态质量检查点，循环位置：'+
                      '、'.join(map(str,cycles))+'。',
                      '- 未列出的中间循环未逐次运行动态质量评估，不插值生成等级。',
                      '- 部件硬失效与系统质量终止是独立判据；部件达到硬阈值时系统等级仍可能是“退化”。',
                      '', _table(quality.drop(columns=['degradation_state_json'],errors='ignore')), '']
        outcome = rul_outcome_text(summary)
        lines += ["## 6. 剩余任务循环结果", "",
                  f"- 预测状态：{cn(summary.get('prediction_status'))}",
                  f"- 剩余完整30天任务：{outcome['complete_value']}（{outcome['complete_note']}）",
                  f"- 首次越限定位：{outcome['failure_value']}；{outcome['failure_note']}",
                  f"- 限制部件：{', '.join(cn(x) for x in (summary.get('limiting_factors') or []))}",
                  f"- 原因：{'；'.join(_failure_reason_cn(x) for x in (summary.get('failure_reasons') or []))}",
                  f"- 定位与验证范围：{outcome['explanation']}",
                  "- Monte Carlo为快速近似载荷推进，并非每条随机路径都执行完整22状态验证。", ""]
        record=item.get('mc_checkpoints')
        if record is not None:
            import numpy as np
            n=record['damage'].shape[1]
            safe=int(item['mc_samples']['last_safe_checkpoint'].min())
            keys=record['mode_keys'].tolist()
            limits=np.array([item['mc_models'][key.split(':')[0]][key.split(':')[2]]['failure_damage'] for key in keys])
            if np.any(record['damage'][0]+1e-15>=limits):
                safe=-1
            scope=(f'第0～{safe}循环' if safe>=0 else '无共同安全检查点（初始状态已达到硬阈值）')
            lines += [f'- 已保存全部{n}条路径的20状态循环检查点。全样本预测带限于共同安全范围：{scope}；终止后不前向填充。',
                '- 随机寿命按每条路径自己的首次越限记录计算，随机越限点为循环末检测；不是均值曲线穿阈值位置。','']
    missing = [name for name, title in (("simulation", "联合仿真"),
                                         ("degradation", "部件退化"),
                                         ("quality", "质量评估"),
                                         ("rul", "剩余寿命")) if name not in results]
    if missing:
        lines += ["## 7. 未执行模块", "",
                  "以下模块本工程尚未执行，报告没有使用历史示例结果填充：",
                  *[f"- {cn(name)}" for name in missing], ""]
    lines += ["## 8. 计算依据与参数来源", "",
              "- 高速大转角可能超出附着极限；该风险与液压退化故障分开。",
              "- 参数来源：现有工程设计配置；标定状态：PENDING_CLIENT_CALIBRATION。",
              "- 验证范围：数值、接口和动态反馈；未包含独立实车耐久精度验收。", "",
              "## 9. 可追溯信息", "", "```json",
              json.dumps(dict(provenance), ensure_ascii=False, indent=2), "```", ""]
    return "\n".join(lines)


def write_report(path: str | Path, project: Mapping[str, Any],
                 results: Mapping[str, Any], provenance: Mapping[str, Any],figures=None) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    text=build_report(project,results,provenance)
    if figures:
        text+='\n## 10. 本次结果图表\n\n'+'\n\n'.join(f'![{title}](<{name}>)' for title,name in figures)
    target.write_text(text, encoding="utf-8")
    return target
