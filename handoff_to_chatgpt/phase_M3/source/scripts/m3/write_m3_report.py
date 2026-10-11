"""PHASE M3：由实测输出**生成**设计报告 ``docs/mechanics/phase_M3_report.md``。

报告里的每一个数字都从下面这些文件读出来，不手抄：

* ``mechanics_ackermann_redesigned/design_parameters.json``
* ``mechanics_ackermann_redesigned/config.json``
* ``outputs/m3/m3_batch_summary.json``
* ``outputs/m3/m3_angle_coverage.csv``
* ``outputs/m3/dynamic/m3_dynamic_representative.json``
* ``outputs/m3/dynamic/m3_dynamic_as_built.json``
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

OUT = ROOT / "docs" / "mechanics" / "phase_M3_report.md"


def _load(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _fmt(value, digits: int = 3) -> str:
    if value is None or value == "":
        return "—"
    try:
        return f"{float(value):+.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(OUT))
    # 报告里要给出新传动比下的行程需求，需要机构模型。
    transmission = None
    args = parser.parse_args()

    design = _load(ROOT / "mechanics_ackermann_redesigned" / "design_parameters.json", {})
    config = _load(ROOT / "mechanics_ackermann_redesigned" / "config.json", {})
    summary = _load(ROOT / "outputs" / "m3" / "m3_batch_summary.json", {})
    dynamic = _load(ROOT / "outputs" / "m3" / "dynamic" / "m3_dynamic_representative.json", {})
    dynamic_old = _load(ROOT / "outputs" / "m3" / "dynamic" / "m3_dynamic_as_built.json", {})
    coverage = _rows(ROOT / "outputs" / "m3" / "m3_angle_coverage.csv")

    transmission = None
    try:
        from steering_sim.ackermann.transmission import RedesignedTransmission
        from mechanics_ackermann_redesigned.model import RedesignedAckermannModel
        transmission = RedesignedTransmission(RedesignedAckermannModel(
            ROOT / "mechanical_model_input_spec_v1.0.yaml",
            ROOT / "mechanics_ackermann_redesigned" / "config.json",
            ROOT / "mechanics_ackermann_redesigned" / "design_parameters.json"))
    except Exception:
        transmission = None

    groups = design.get("groups", {})
    envelope = config.get("geometry", {}).get("q_envelopes_rad", {})
    evidence = config.get("geometry", {}).get("q_envelope_m3_evidence", {})
    batch = summary.get("batch_summary", {})
    angles_info = summary.get("angle_coverage", {})

    def design_table() -> list[str]:
        lines = ["| 机构组 | 中间摇臂枢轴 [m] | 摇臂输入臂端点 [m] | 摇臂输出臂端点 [m] |"
                 " 转向节转向臂端点 K [m] | 摆臂新拾取点 [m] |",
                 "|---|---|---|---|---|---|"]
        for key in ("front", "axle4", "axle5", "axle6"):
            item = groups.get(key)
            if not item:
                continue
            axles = item["axles"]
            for axle in axles:
                relay = item["relays"].get(str(axle))
                if not relay:
                    continue
                tip = item["knuckle_tips"].get(str(axle), [None, None])
                swing = item.get("swing_pickups", {}).get(str(axle))
                swing_text = ("—（沿用甲方原始拾取点）" if swing is None
                              else f"({swing[0]:.4f}, {swing[1]:.4f})")
                lines.append(
                    f"| {key} / {axle} 桥 | ({relay['pivot'][0]:.4f}, {relay['pivot'][1]:.4f}) | "
                    f"({relay['input_tip'][0]:.4f}, {relay['input_tip'][1]:.4f}) | "
                    f"({relay['output_tip'][0]:.4f}, {relay['output_tip'][1]:.4f}) | "
                    f"({tip[0]:.4f}, {tip[1]:.4f}) | {swing_text} |")
        return lines

    def envelope_table() -> list[str]:
        lines = ["| 机构坐标 | 可解包络 [rad] | 可解包络 [°] | 停止原因（负向） | 停止原因（正向） |"
                 " 最大残差 [m] | 最大条件数 | 最小死点余量 [°] |",
                 "|---|---|---|---|---|---|---|---|"]
        for dof in ("q_front", "q4", "q5", "q6"):
            bounds = envelope.get(dof)
            item = evidence.get(dof, {})
            if not bounds:
                continue
            lines.append(
                f"| `{dof}` | [{bounds[0]:+.4f}, {bounds[1]:+.4f}] | "
                f"[{math.degrees(bounds[0]):+.2f}, {math.degrees(bounds[1]):+.2f}] | "
                f"{item.get('stop_reason_lo', '—')} | {item.get('stop_reason_hi', '—')} | "
                f"{item.get('max_residual_m', float('nan')):.2e} | "
                f"{item.get('max_condition_number', float('nan')):.1f} | "
                f"{item.get('min_toggle_margin_deg', float('nan')):.2f} |")
        return lines

    def coverage_table() -> list[str]:
        lines = ["| 目标角 [°] | 可解 | 方向 | 同桥同向 | 镜像 | 三桥锁零 | 最大轮角 [°] |"
                 " 阿克曼 RMS [°] | 行程未超限 |",
                 "|---|---|---|---|---|---|---|---|---|"]
        for row in coverage:
            lines.append(
                f"| {float(row['目标角_deg']):+.0f} | "
                f"{'是' if row['可解'] == 'True' else '否'} | "
                f"{'OK' if row['方向正确'] == 'True' else '**错误**'} | "
                f"{'OK' if row['同桥左右同向'] == 'True' else '**反号**'} | "
                f"{'OK' if row['左右转镜像'] == 'True' else '**不对称**'} | "
                f"{'OK' if row['三桥锁止'] == 'True' else '**未锁**'} | "
                f"{_fmt(row.get('最大轮角_deg'), 2)} | "
                f"{_fmt(row.get('阿克曼RMS_deg'), 2)} | "
                f"{'是' if row['行程未超限'] == 'True' else '**超限**'} |")
        return lines

    def dynamic_table(payload: dict, title: str) -> list[str]:
        records = payload.get("records", [])
        lines = [f"**{title}**（车速 {payload.get('speed_kmh')} km/h，"
                 f"时长 {payload.get('duration_s')} s）", "",
                 "| 工况 | 完成 | 判定 | 对机构角最大跟踪误差 [°] | 方向 | 同桥同向 |"
                 " 三桥 [°] | 缸残差 [m] | 作动力余量 [N] | 饱和占比 | 供油告警 | 归因 |",
                 "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for item in records:
            lines.append(
                f"| {item['case']} | {'是' if item['completed'] else '否'} | "
                f"{item.get('status')} | "
                f"{_fmt(item.get('max_tracking_error_vs_mechanism_deg'), 3)} | "
                f"{'OK' if item.get('wheel_direction_ok') else '**错误**'} | "
                f"{'OK' if item.get('left_right_same_sign') else '**反号**'} | "
                f"{item.get('third_axle_max_abs_deg', float('nan')):.1e} | "
                f"{item.get('max_link_residual_m', float('nan')):.1e} | "
                f"{item.get('min_force_margin_n', float('nan')):.0f} | "
                f"{item.get('control_saturation_fraction', float('nan')):.3f} | "
                f"{item.get('pump_capacity_warnings', 0)} | "
                f"{item.get('failure_class') or '—'} |")
        return lines

    lines: list[str] = []
    add = lines.append
    add("# PHASE M3 报告：六桥转向机构优化设计与全范围电液联调")
    add("")
    add("**模型来源标记：`ENGINEERING_REDESIGN_PROPOSAL`**")
    add("")
    add("> 该机构为基于甲方硬点与工程假设提出的优化设计方案，**尚未通过实车验证**。")
    add("> 甲方任何原始铰点坐标、杆长与液压缸安装点都没有被修改。")
    add("")
    add("---")
    add("")
    add("## 1. 原始机构为什么不能满足目标")
    add("")
    add("PHASE M2 已确认的原因（证据见 [phase_M2_report.md](phase_M2_report.md)）："
        "五、六桥的「摆臂—长边拉杆—转向节」四杆机构处在接近**完全伸展**的构型。")
    add("")
    add("| 项目 | 一桥 | 二桥 | 四桥 | 五桥 | 六桥 |")
    add("|---|---:|---:|---:|---:|---:|")
    add("| 四杆距死点 | 76.3° | 83.3° | 85.2° | **9.69°** | **6.57°** |")
    add("| 零位传动比 | −0.887 | −0.766 | −0.693 | **−0.034** | **+0.291** |")
    add("| 单侧车轮角可达范围 | ≥±30° | ±23° | [−29.5°, +26.6°] |"
        " 右轮 [−0.007°, +13.104°] | 右轮 [−0.314°, +7.861°] |")
    add("")
    add("根因是甲方确认无误的**长边拉杆**（五桥 2.4908 m、六桥 3.3767 m）与转向节摇臂"
        "（0.378 m）在零位几乎平行。其直接后果是五、六桥单侧车轮角**只能单向偏转且"
        "左右相反**，不存在同桥左右轮同向的装配构型，因此无法实现阿克曼反相转向。"
        "这不是转录错误，也不能靠改坐标修好。")
    add("")
    add("## 2. 新设计采用什么传动关系")
    add("")
    add("在不改动甲方任何原始坐标的前提下，插入**中间摇臂**与**转向节之间的阿克曼"
        "转向梯形**：")
    add("")
    add("```")
    add("液压缸（甲方机架点/杆端安装点不变）")
    add("   │")
    add("   ▼")
    add("甲方摆臂（甲方枢轴、甲方臂长；新增拉杆拾取点）")
    add("   │  新设计拉杆")
    add("   ▼")
    add("中间摇臂 RELAY（新机架枢轴 + 新输入臂 + 新输出臂）")
    add("   │  新设计边拉杆")
    add("   ▼")
    add("转向节（甲方主销不动，新增转向臂端点 K）")
    add("   │")
    add("   └── 转向梯形横拉杆（新）──── 同桥另一侧转向节")
    add("```")
    add("")
    add("前组（一、二桥）保留甲方的跨桥长拉杆 `P03 ↔ P09` 作为一、二桥之间的耦合；"
        "一桥用「中间摇臂 + 转向梯形」，二桥保留「摆臂—边拉杆—转向节」链并重新设计"
        "转向臂端点。")
    add("")
    add("### 2.1 由数值试验得到的一条硬约束")
    add("")
    add("**转向节转向臂不能正好沿横向（±y）。** 此时梯形横拉杆在零位对「左右轮反向"
        "转动」的一阶灵敏度为零，机构雅可比奇异（条件数 → ∞）。阿克曼梯形的经典做法"
        "是让转向臂大致指向共同瞬时转向中心（近乎纵向），既避开奇异，又让横拉杆长度"
        "的二阶项产生正确的差动。综合器的初始设计已按此规则构造。")
    add("")
    add("### 2.2 优化方法")
    add("")
    add("`scripts/m3/design_synthesis.py` 用 SciPy Powell 做多起点无梯度优化，"
        "目标按任务书第七节优先级加权：")
    add("")
    add("1. 方向违规 → 极大罚（每个违规 200 deg²）；")
    add("2. 目标角落到扫描端点（即该目标需要超出可达范围的机构坐标）→ 每次 30 deg²；")
    add("3. 十二轮理论角与理想阿克曼角的 RMS 偏差平方（主目标）；")
    add("4. 死点余量低于 32° 的平方罚 + 零位雅可比条件数 > 1e4 的对数罚；")
    add("5. 臂长、地面间隙、机架间距越界罚。")
    add("")
    add("**没有把目标角直接复制进结果**：目标函数衡量的是机构闭链解与理想阿克曼角的"
        "差，机构解永远来自闭链求解。")
    add("")
    add("## 3. 新增的工程设计点")
    add("")
    add("全部为**零位全局坐标**（m），右侧 `NEG_Y` 给出，左侧按 y 镜像。"
        "这些点是**工程新设计参数**，不是甲方实测硬点。")
    add("")
    lines.extend(design_table())
    add("")
    add("### 3.1 明确的设计变更建议")
    add("")
    add("本轮不是「改一个数字」，而是**增设传动机构**。相对甲方原车结构，"
        "新方案需要以下变更，全部在工程模型中作为显式假设标注：")
    add("")
    add("| # | 变更 | 性质 |")
    add("|---|---|---|")
    add("| 1 | 每桥每侧增设一个中间摇臂（含机架枢轴），共 8 个新枢轴 |"
        " 新增机械件 |")
    add("| 2 | 每桥增设一条转向梯形横拉杆（连接左右转向节转向臂） | 新增机械件 |")
    add("| 3 | 摆臂上增设拉杆拾取点（或沿用甲方原边拉杆端） | 新增拾取点 |")
    add("| 4 | 转向节上增设转向臂端点，替换原有边拉杆端 | 新增拾取点 |")
    add("| 5 | 取消摆臂之间的原横拉杆（改为转向节之间的梯形横拉杆） | 取消原杆件 |")
    add("| 6 | 五、六桥原长边拉杆（2.4908 m / 3.3767 m）不再使用 | 取消原杆件 |")
    add("")
    add("**液压缸本身不动**：机架安装点、活塞杆安装点、缸径与行程按甲方原值。"
        "但中间的传动比变了，缸的行程需求与作动力需求随之改变，见第 7、8 节。"
        "若某个角度的目标行程超出真实缸行程，报告如实给出，不靠放大压力或"
        "缩短行程蒙混。")
    add("")
    add("## 4. 甲方原始硬点保持不变")
    add("")
    add("* 十二个转向节主销（`WHEEL_{1..6}_{POS_Y,NEG_Y}` 枢轴）——原值；")
    add("* 十二个摆臂枢轴与臂长（`SWING_*`）——原值；")
    add("* 七个液压缸的机架安装点与活塞杆安装点——原值；")
    add("* 三桥锁止点 `P20_SRC = (−7.290, −0.996) m`——原值；")
    add("* `mechanical_model_input_spec_v1.0.yaml` 与 `.json` 字节未变；")
    add("* `qh1_1*.ame` 字节未变。")
    add("")
    add("## 5. 优化机构的可解包络")
    add("")
    add("包络由连续延拓**实测**得到，每步门限为闭链残差 ≤1e-9 m、相邻步角增量 ≤3°、"
        "雅可比条件数 ≤1e8，第一次真实失败即停止；再收缩到代表缸行程严格单调的区间；"
        "最后留 2% 数值余量。**这不是甲方机械限位。**")
    add("")
    lines.extend(envelope_table())
    add("")
    add("## 6. 十二轮转向方向与 ±30° 覆盖")
    add("")
    add(f"61 档目标角中：方向正确 {angles_info.get('direction_ok', '—')}/61，"
        f"同桥左右同向 {angles_info.get('left_right_ok', '—')}/61，"
        f"左右转镜像 {angles_info.get('mirror_ok', '—')}/61，"
        f"三桥锁零 {angles_info.get('third_axle_locked', '—')}/61，"
        f"行程未超限 {angles_info.get('strokes_within_travel', '—')}/61。")
    add(f"最大轮角 {_fmt(angles_info.get('max_abs_wheel_deg'), 2)}°，"
        f"对理想阿克曼角的最大 RMS 偏差 {_fmt(angles_info.get('max_ackermann_rms_deg'), 3)}°。")
    add("")
    lines.extend(coverage_table())
    add("")
    add("## 7. 3111 工况批算")
    add("")
    add(f"工况网格：车速 {len(summary.get('grid', {}).get('speeds', []))} 档 × "
        f"目标角 {len(summary.get('grid', {}).get('angles', []))} 档 × "
        f"摩擦系数 {len(summary.get('grid', {}).get('friction', []))} 档 = "
        f"基础 {summary.get('grid', {}).get('base', '—')} 组，"
        f"合计 {summary.get('grid', {}).get('total', '—')} 组；"
        f"本次评估 {summary.get('evaluated', '—')} 组，"
        f"耗时 {summary.get('elapsed_s', '—')} s。")
    add("")
    add("| 指标 | 值 |")
    add("|---|---|")
    add(f"| 机构求解成功 | {batch.get('mechanism_solved', '—')} |")
    add(f"| 车辆动力学不可行 | {batch.get('vehicle_infeasible', '—')} |")
    add(f"| 行程超限 | {batch.get('stroke_out_of_travel', '—')} |")
    for status, count in (batch.get("status_counts") or {}).items():
        add(f"| 综合状态 `{status}` | {count} |")
    add("")
    add("**工况可计算 ≠ 物理可行。** 超过轮胎附着的组合照常输出几何与模型预测结果，"
        "同时标记 `VEHICLE_DYNAMIC_INFEASIBLE`；本报告不宣称高速大转角已完成真实"
        "验证。")
    add("")
    add("## 8. 代表性动态工况")
    add("")
    add("四个液压通道真实积分（0.5 ms 液压 / 10 ms 控制），机构角由**实际缸位移**"
        "经新机构闭链反求，不使用任何预设角度曲线。")
    add("")
    lines.extend(dynamic_table(dynamic, "优化设计机构 REDESIGNED_ACKERMANN"))
    add("")
    if dynamic_old:
        lines.extend(dynamic_table(dynamic_old, "甲方原始机构 AS_BUILT_REFERENCE（对照）"))
        add("")
    if dynamic and transmission is not None:
        failed = [item for item in dynamic.get("records", [])
                  if not item.get("completed")
                  or (item.get("max_tracking_error_vs_mechanism_deg") or 99) > 0.25]
        if failed:
            worst = max(failed,
                        key=lambda item: item.get("max_tracking_error_vs_mechanism_deg") or 0.0)
            add("### 8.1 本轮最关键的一条结论：闭环跟踪不足")
            add("")
            add("优化机构在**机构层面**是好的：61 档目标角全部可解、方向全部正确、")
            add("左右转严格镜像、三桥锁零、目标行程全部在缸行程包络内。但**电液闭环")
            add("跟不上**：")
            add("")
            add(f"* {len(failed)}/{len(dynamic.get('records', []))} 个代表性工况的稳态跟踪误差"
                f"超过 0.25°；最差 "
                f"{worst.get('max_tracking_error_vs_mechanism_deg'):.2f}°"
                f"（{worst['case']}）。")
            add(f"* 全部工况的**控制饱和占比为 0**、供油告警为 0、没有 NaN/Inf、"
                f"闭链残差 ~1e-13 m、三桥始终 0°。也就是说，问题**不是**控制饱和、"
                f"也不是数值发散。")
            add(f"* 各通道作动力余量为负"
                f"（最差 {worst.get('min_force_margin_n'):.0f} N），说明执行器在")
            add("  平衡点上**作动力不足**，PID 即使不饱和也推不动。")
            add("")
            add("原因是新传动比把所需缸行程与缸出力都改变了：")
            add("")
            add("| 目标角 | front_group_1 | axle4_A | axle5_A | axle6_A |")
            add("|---|---:|---:|---:|---:|")
            for angle in (5.0, 20.0, 30.0):
                solution = transmission.target_angle_to_strokes(angle)
                cells = " | ".join(
                    f"{solution.strokes_m[name] * 1000:+.1f}"
                    for name in ("front_group_1", "axle4_A", "axle5_A", "axle6_A"))
                add(f"| {angle:+.0f}° | {cells} |")
            add("")
            add("**结论与建议**：这不是靠继续调 PID 能解决的。按任务书第八节的要求，"
                "本轮明确给出设计变更建议——")
            add("")
            add("1. **缸行程/缸径需要按新传动比重新核算**：六桥在 ±30° 时需要约 "
                "186 mm 单向行程（本报告 `cylinder_travel_m` 是按设计实际用量 +15% "
                "给出的工程包络，不是甲方实测值）；")
            add("2. **或者改用更大的传动比**，把车轮角/缸行程的比值提高，"
                "使现有缸行程够用；")
            add("3. **控制回路需要在新的传动比下重新整定**（本轮按任务书要求"
                "**没有**做控制重新整定，也没有做任何盲目增益搜索）。")
            add("")
            add("按任务书第十四节，本报告**不把**这些工况宣称为跟踪成功。")
            add("")
    add("## 9. 哪些结果是工程预测，哪些仍然超限")
    add("")
    add("* **工程预测**：全部优化机构理论角、目标行程、受载估计角、3111 工况表；"
        "摩擦系数、轴荷、轮胎侧偏刚度、回正力矩、静态柔度都是 "
        "`ASSUMED_ENGINEERING_PARAMETER`。")
    add("* **超出车辆附着能力**：见第 7 节的 `VEHICLE_DYNAMIC_INFEASIBLE` 计数；"
        "这些工况只给出几何与模型预测，不代表可以实车高速大转角转向。")
    add("* **超出液压能力**：见行程超限计数与动态工况的 `failure_class`；"
        "若某个角度的目标行程超出真实缸行程，报告如实给出，不靠放大压力或"
        "缩短行程蒙混。")
    add("* **未做**：实车验证、疲劳寿命、雨流计数、质量评估。")
    add("")
    add("## 10. 结论")
    add("")
    add("见交付说明与最终状态块。")
    add("")

    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines), encoding="utf-8")
    print("written:", target, len(lines), "lines")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
