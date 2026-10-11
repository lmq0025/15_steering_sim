"""PHASE J0-DEMO 演示图像。

全部图像只读取**同一次仿真**的 samples，因此横轴、单位与图例必然一致。
图中始终把三个不同的角度分开表示：

* **实际角** —— 由真实液压缸位移经机构闭链反求得到（唯一"真值"）
* **机构可达角** —— M1 刚体闭链在 q_ref 上真正能达到的角度（J0 闭环的跟踪目标）
* **理想阿克曼角** —— 指令工况按共同瞬时中心算出的几何理想值

三者不可合并为一条曲线，否则会把 M1 的机构偏差误记成控制跟踪误差。

实现上**刻意不使用 ``pyplot``**：界面在后台线程里跑仿真，而 pyplot 的全局状态机
与 ``matplotlib.use()`` 的后端切换都不是线程安全的（在 Tk 主循环存在时会直接
使进程崩溃）。这里改为显式的 ``Figure`` + ``FigureCanvasAgg``，逐图独立、
不共享全局状态，也不改动全局后端。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import numpy as np

from steering_sim.j0_coupling.reporting import configure_chinese_font

WHEELS = tuple(f"axle{axle}_{side}" for axle in range(1, 7)
               for side in ("left", "right"))
CHANNELS = ("channel_front", "channel_rear_1", "channel_rear_2", "channel_rear_3")
CHANNEL_LABEL = {"channel_front": "前组(一、二桥)", "channel_rear_1": "四桥",
                 "channel_rear_2": "五桥", "channel_rear_3": "六桥"}
CHANNEL_COLOR = {"channel_front": "#1f77b4", "channel_rear_1": "#d62728",
                 "channel_rear_2": "#2ca02c", "channel_rear_3": "#9467bd"}
ACTUAL_COLOR = "#111111"
MECHANISM_COLOR = "#1f77b4"
IDEAL_COLOR = "#ff7f0e"
ACTUAL_STYLE = dict(linewidth=1.6)
MECHANISM_STYLE = dict(linestyle="--", linewidth=1.1, alpha=0.85)
IDEAL_STYLE = dict(linestyle=":", linewidth=1.1, alpha=0.8)

DPI = 140


def _figure(figsize=(11, 8)):
    """建一个独立 Figure（Agg 画布，不接触 pyplot 全局状态）。"""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    configure_chinese_font()
    figure = Figure(figsize=figsize, layout="constrained")
    FigureCanvasAgg(figure)
    return figure


def _save(figure, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=DPI)
    figure.clear()
    return path


def _title(scenario) -> str:
    return (f"{scenario.case_id}：目标 {scenario.target_outer_angle_deg:+.1f}° / "
            f"{scenario.speed_kmh:.0f} km/h / μ={scenario.friction_coefficient:.2f} / "
            f"轴荷 {scenario.axle_mass_t[0]:.1f} t")


def _legend_handles():
    from matplotlib.lines import Line2D
    return [Line2D([], [], color=ACTUAL_COLOR, label="实际车轮角"),
            Line2D([], [], color=MECHANISM_COLOR, **MECHANISM_STYLE,
                   label="机构可达角"),
            Line2D([], [], color=IDEAL_COLOR, **IDEAL_STYLE, label="理想阿克曼角"),
            Line2D([], [], color="#e8291c", linewidth=2.2,
                   label="三桥（锁止 0°）")]


# ------------------------------------------------------------- 1 俯视
def plot_plan_view(samples: Mapping[str, np.ndarray], summary: Mapping[str, Any],
                   scenario, centers: Mapping[str, tuple[float, float]],
                   out_dir: Path) -> Path:
    """六桥十二轮俯视结构示意 + 十二轮稳态转角对照。

    俯视图按真实比例绘制（16.3 m 车长），因此 ±5° 的车轮转角在这个尺度上
    只有几毫米的可见量——这是事实，不能靠放大角度来"看清楚"。所以下面再配一张
    逐轮稳态转角柱状图，把实际 / 机构可达 / 理想阿克曼三个角度并排画出来。
    """
    from matplotlib.lines import Line2D
    import numpy as np

    figure = _figure((13, 10))
    grid = figure.add_gridspec(2, 1, height_ratios=[0.78, 1.5], hspace=0.30)
    axis = figure.add_subplot(grid[0])
    last = -1
    wheel_length = 0.55
    axles = sorted({int(name[4]) for name in WHEELS})
    for axle in axles:
        for side in ("left", "right"):
            name = f"axle{axle}_{side}"
            cx, cy = centers[name]
            axis.plot([cx], [cy], marker="o", markersize=2.5, color="#666666", zorder=1)
            for key, style, color in (
                    (f"wheel_{name}_actual_deg", ACTUAL_STYLE, ACTUAL_COLOR),
                    (f"wheel_{name}_target_mechanism_deg", MECHANISM_STYLE,
                     MECHANISM_COLOR),
                    (f"wheel_{name}_target_deg", IDEAL_STYLE, IDEAL_COLOR)):
                radians = np.radians(float(np.asarray(samples[key])[last]))
                dx = wheel_length * np.cos(radians)
                dy = wheel_length * np.sin(radians)
                axis.plot([cx - dx / 2, cx + dx / 2], [cy - dy / 2, cy + dy / 2],
                          color=color, solid_capstyle="round", **style)
        left = centers[f"axle{axle}_left"]
        right = centers[f"axle{axle}_right"]
        axis.plot([left[0], right[0]], [left[1], right[1]],
                  color="#e8291c" if axle == 3 else "#999999",
                  linewidth=2.4 if axle == 3 else 1.0, zorder=0)
        axis.text((left[0] + right[0]) / 2, 1.35, f"{axle}桥", ha="center",
                  va="bottom", fontsize=9,
                  color="#e8291c" if axle == 3 else "#444444")
    xs = [centers[name][0] for name in WHEELS]
    axis.set_xlim(min(xs) - 1.4, max(xs) + 3.4)
    axis.set_ylim(-1.9, 2.1)
    axis.annotate("车头 →", xy=(max(xs) + 0.8, 1.15), fontsize=12, color="#333333")
    axis.set_aspect("equal")
    axis.set_xlabel("整车纵坐标 x [m]（+ 为车头方向）")
    axis.set_ylabel("整车横坐标 y [m]\n（+ 为车辆左侧）")
    axis.set_title(_title(scenario) + "\n六桥十二轮俯视结构示意（真实比例，"
                                    "该尺度下车轮转角仅几毫米可见）")
    axis.legend(handles=_legend_handles(), loc="lower right", fontsize=8, ncol=2)
    axis.grid(alpha=0.25)

    # 逐轮稳态转角对照
    axis2 = figure.add_subplot(grid[1])
    labels = list(WHEELS)
    position = np.arange(len(labels))
    width = 0.27
    ideal = [float(summary["target_wheel_angle_deg"][name]) for name in labels]
    mechanism = [float(summary["target_mechanism_wheel_angle_deg"][name])
                 for name in labels]
    actual = [float(np.asarray(samples[f"wheel_{name}_actual_deg"])[last])
              for name in labels]
    axis2.bar(position - width, ideal, width, color=IDEAL_COLOR, label="理想阿克曼角")
    axis2.bar(position, mechanism, width, color=MECHANISM_COLOR, label="机构可达角")
    axis2.bar(position + width, actual, width, color=ACTUAL_COLOR, label="实际角")
    axis2.axhline(0.0, color="k", linewidth=0.8)
    axis2.set_xticks(position)
    axis2.set_xticklabels(labels, rotation=55, ha="right", fontsize=8)
    axis2.set_ylabel("稳态转角 [°]")
    axis2.set_title("十二轮稳态转角对照：实际角 / 机构可达角 / 理想阿克曼角")
    axis2.grid(alpha=0.3, axis="y")
    axis2.legend(fontsize=8, ncol=3)
    for axle in (4, 5, 6):
        pairs = [labels.index(f"axle{axle}_left"), labels.index(f"axle{axle}_right")]
        if np.sign(mechanism[pairs[0]]) != np.sign(mechanism[pairs[1]]):
            axis2.axvspan(min(pairs) - 0.5, max(pairs) + 0.5, color="#e8291c",
                          alpha=0.10, zorder=0)
    if any(np.sign(mechanism[labels.index(f"axle{axle}_left")])
           != np.sign(mechanism[labels.index(f"axle{axle}_right")])
           for axle in (4, 5, 6)):
        axis2.text(0.995, 0.96,
                   "红色底纹：同桥左右轮机构可达角反号\n（ACKERMANN_GEOMETRY_DEVIATION）",
                   transform=axis2.transAxes, ha="right", va="top", fontsize=8,
                   color="#b00020")
    for axle in (3,):
        axis2.text(labels.index(f"axle{axle}_left") + 0.5, 0.0, "三桥锁止 0°",
                   ha="center", va="bottom", fontsize=8, color="#e8291c")
    return _save(figure, out_dir / "fig1_plan_view.png")


# ------------------------------------------------------- 2 车轮转角
def plot_wheel_angles(samples: Mapping[str, np.ndarray], summary: Mapping[str, Any],
                      scenario, out_dir: Path) -> Path:
    time = samples["time_s"]
    groups = (("一、二桥（前组）", ("axle1_left", "axle1_right", "axle2_left",
                                    "axle2_right")),
              ("三桥（锁止）", ("axle3_left", "axle3_right")),
              ("四桥", ("axle4_left", "axle4_right")),
              ("五桥", ("axle5_left", "axle5_right")),
              ("六桥", ("axle6_left", "axle6_right")))
    figure = _figure((11, 13))
    axes = figure.subplots(len(groups), 1, sharex=True)
    for axis, (label, wheels) in zip(axes, groups):
        for wheel in wheels:
            axis.plot(time, samples[f"wheel_{wheel}_actual_deg"], color=ACTUAL_COLOR,
                      label=f"{wheel} 实际", **ACTUAL_STYLE)
            axis.plot(time, samples[f"wheel_{wheel}_target_mechanism_deg"],
                      color=MECHANISM_COLOR, label=f"{wheel} 机构可达",
                      **MECHANISM_STYLE)
            axis.plot(time, samples[f"wheel_{wheel}_target_deg"], color=IDEAL_COLOR,
                      label=f"{wheel} 理想阿克曼", **IDEAL_STYLE)
        axis.set_ylabel(f"{label}\n转角 [°]")
        axis.grid(alpha=0.3)
        axis.axhline(0.0, color="k", linewidth=0.5, alpha=0.4)
        axis.legend(fontsize=7, ncol=2, loc="best")
    axes[0].set_title(_title(scenario) + "\n车轮转角：实际 vs 机构可达 vs 理想阿克曼")
    axes[-1].set_xlabel("时间 [s]")
    return _save(figure, out_dir / "fig2_wheel_angles.png")


# ------------------------------------------------------- 3 液压缸行程
def plot_strokes(samples: Mapping[str, np.ndarray], summary: Mapping[str, Any],
                 scenario, out_dir: Path) -> Path:
    time = samples["time_s"]
    figure = _figure((13, 12))
    axes = figure.subplots(4, 2, sharex=True)
    for row, tag in enumerate(CHANNELS):
        color = CHANNEL_COLOR[tag]
        axes[row][0].plot(time, samples[f"{tag}_x_ref_m"] * 1e3, "k--", linewidth=1.2,
                          label="目标行程")
        axes[row][0].plot(time, samples[f"{tag}_x_m"] * 1e3, color=color, label="实际行程")
        axes[row][0].set_ylabel(f"{CHANNEL_LABEL[tag]}\n行程 [mm]")
        axes[row][0].legend(fontsize=8, loc="best")
        axes[row][1].plot(time, samples[f"{tag}_v_m_s"] * 1e3, color=color,
                          label="活塞速度")
        axes[row][1].set_ylabel(f"{CHANNEL_LABEL[tag]}\n速度 [mm/s]")
        axes[row][1].legend(fontsize=8, loc="best")
        for axis in axes[row]:
            axis.grid(alpha=0.3)
            axis.axhline(0.0, color="k", linewidth=0.5, alpha=0.4)
    axes[0][0].set_title(_title(scenario) + "\n液压缸行程与活塞速度")
    for axis in axes[-1]:
        axis.set_xlabel("时间 [s]")
    return _save(figure, out_dir / "fig3_strokes.png")


# ----------------------------------------------- 4 压力 / 力 / 负载 / 阀
def plot_hydraulics(samples: Mapping[str, np.ndarray], summary: Mapping[str, Any],
                    scenario, out_dir: Path) -> Path:
    time = samples["time_s"]
    figure = _figure((12, 14))
    axes = figure.subplots(4, 1, sharex=True)
    for tag in CHANNELS:
        color = CHANNEL_COLOR[tag]
        label = CHANNEL_LABEL[tag]
        axes[0].plot(time, samples[f"{tag}_pA_mpa_g"], color=color, label=f"{label} pA")
        axes[0].plot(time, samples[f"{tag}_pB_mpa_g"], color=color, linestyle="--",
                     alpha=0.8, label=f"{label} pB")
        axes[1].plot(time, samples[f"{tag}_hydraulic_force_n"] / 1e3, color=color,
                     label=f"{label} 液压力")
        axes[1].plot(time, samples[f"{tag}_load_force_n"] / 1e3, color=color,
                     linestyle="--", alpha=0.7, label=f"{label} 地面负载")
        axes[2].plot(time, samples[f"{tag}_valve_command"], color=color,
                     label=f"{label} 主阀命令")
        axes[3].plot(time, samples[f"{tag}_flow_a_m3_s"] * 60000.0, color=color,
                     label=f"{label} QA")
    axes[0].set_ylabel("腔压力 [MPa(g)]")
    axes[1].set_ylabel("力 [kN]")
    axes[2].set_ylabel("主阀控制输入 [—]")
    axes[3].set_ylabel("A 腔流量 [L/min]")
    for axis in axes:
        axis.grid(alpha=0.3)
        axis.legend(fontsize=7, ncol=2, loc="best")
    axes[0].set_title(_title(scenario) + "\n腔压力、液压力 vs 地面负载、主阀命令与流量")
    axes[-1].set_xlabel("时间 [s]")
    return _save(figure, out_dir / "fig4_hydraulics.png")


# ---------------------------------------------------------- 5 控制
def plot_control(samples: Mapping[str, np.ndarray], summary: Mapping[str, Any],
                 scenario, out_dir: Path) -> Path:
    time = samples["time_s"]
    figure = _figure((12, 11))
    axes = figure.subplots(3, 1, sharex=True)
    for tag in CHANNELS:
        color = CHANNEL_COLOR[tag]
        label = CHANNEL_LABEL[tag]
        axes[0].plot(time, (samples[f"{tag}_x_ref_m"] - samples[f"{tag}_x_m"]) * 1e3,
                     color=color, label=f"{label} 行程误差")
        axes[2].plot(time, samples[f"{tag}_pid_raw_output"], color=color,
                     label=f"{label} PID 输出")
    for tag, wheel in (("channel_front", "axle1_left"),
                       ("channel_rear_1", "axle4_left"),
                       ("channel_rear_2", "axle5_left"),
                       ("channel_rear_3", "axle6_left")):
        axes[1].plot(time, samples[f"wheel_{wheel}_actual_deg"]
                     - samples[f"wheel_{wheel}_target_mechanism_deg"],
                     color=CHANNEL_COLOR[tag], label=f"{wheel} 实际−机构可达")
    axes[1].plot(time, samples["wheel_axle1_right_actual_deg"]
                 - samples["wheel_axle1_right_target_mechanism_deg"],
                 color=CHANNEL_COLOR["channel_front"], linestyle="--", alpha=0.7,
                 label="axle1_right 实际−机构可达")
    axes[0].set_ylabel("行程误差 [mm]")
    axes[1].set_ylabel("轮角跟踪误差 [°]")
    axes[2].set_ylabel("PID 输出 [—]")
    for axis in axes:
        axis.grid(alpha=0.3)
        axis.axhline(0.0, color="k", linewidth=0.5, alpha=0.4)
        axis.legend(fontsize=7, ncol=2, loc="best")
    axes[0].set_title(_title(scenario) + "\n控制结果：跟踪误差与 PID 命令")
    axes[-1].set_xlabel("时间 [s]")
    return _save(figure, out_dir / "fig5_control.png")


# ------------------------------------------------- 6 工况与供油能力
def plot_case_and_supply(samples: Mapping[str, np.ndarray],
                         summary: Mapping[str, Any], scenario,
                         assessment, out_dir: Path) -> Path:
    time = samples["time_s"]
    figure = _figure((13, 8.5))
    axes = figure.subplots(2, 2)

    axes[0][0].plot(time, samples["adhesion_utilization"], color="#d62728",
                    label="附着利用率")
    axes[0][0].axhline(1.0, color="k", linestyle="--", linewidth=1.0,
                       label="附着极限 1.0")
    axes[0][0].set_ylabel("附着利用率 |Fy|/Fy_max [—]")
    axes[0][0].set_xlabel("时间 [s]")
    axes[0][0].legend(fontsize=8)

    axes[0][1].plot(time, samples["max_abs_slip_angle_deg"], color="#1f77b4",
                    label="最大轮胎侧偏角")
    axes[0][1].set_ylabel("侧偏角 [°]")
    axes[0][1].set_xlabel("时间 [s]")
    axes[0][1].legend(fontsize=8)

    supply = assessment.supply.to_dict()["groups"]
    labels, pump, demand, margin = [], [], [], []
    for item in supply.values():
        labels.append(item["label"])
        pump.append(item["q_pump_l_per_min"])
        demand.append(item["high_rail_demand_l_per_min"])
        margin.append(item["margin_l_per_min"])
    position = np.arange(len(labels))
    axes[1][0].bar(position - 0.2, pump, width=0.4, color="#7f7f7f", label="泵供量")
    axes[1][0].bar(position + 0.2, demand, width=0.4, color="#1f77b4",
                   label="高压轨取流量")
    for index, value in enumerate(margin):
        axes[1][0].text(index, max(pump[index], demand[index]) + 0.6,
                        f"余量 {value:.2f} L/min", ha="center", fontsize=8,
                        color="#d62728" if value < 0.1 * pump[index] else "#2ca02c")
    axes[1][0].set_xticks(position)
    axes[1][0].set_xticklabels(labels, fontsize=8)
    axes[1][0].set_ylim(0.0, max(pump + demand) * 1.25)
    axes[1][0].set_ylabel("流量 [L/min]")
    axes[1][0].legend(fontsize=8)

    lines = [scenario.describe(), ""]
    lines.append(f"机械检查：{assessment.mechanism.status}")
    for message in assessment.mechanism.messages[:2]:
        lines.append("· " + _wrap(message, 34))
    lines.append("")
    lines.append(f"供油检查：{assessment.supply.status}")
    for message in assessment.supply.messages[:2]:
        lines.append("· " + _wrap(message, 34))
    lines.append("")
    lines.append("工程假设：摩擦系数与轴荷为 ASSUMED，非实车测量值；")
    lines.append("实际轮角全部由真实液压缸位移经机构闭链反求。")
    if any(item.outside_verified for item in assessment.ranges):
        lines.append("")
        lines.append("⚠ 该工况超出已验证动态联调范围，属于外推。")
    axes[1][1].axis("off")
    axes[1][1].text(0.0, 1.0, "\n".join(lines), va="top", ha="left", fontsize=8.5,
                    transform=axes[1][1].transAxes)
    axes[1][1].set_title("工况与模型限制", fontsize=10)
    for axis in (axes[0][0], axes[0][1], axes[1][0]):
        axis.grid(alpha=0.3)
    figure.suptitle(_title(scenario), fontsize=11)
    return _save(figure, out_dir / "fig6_case_and_supply.png")


def _wrap(text: str, width: int) -> str:
    out, line = [], ""
    for char in text:
        line += char
        if len(line) >= width and char in "，。；、）":
            out.append(line)
            line = ""
    if line:
        out.append(line)
    return "\n  ".join(out) if out else text


def plot_all(result, centers: Mapping[str, tuple[float, float]],
             out_dir: Path) -> tuple[Path, ...]:
    """生成全部演示图像。所有图共用同一份 samples。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    return (
        plot_plan_view(result.samples, result.summary, result.scenario, centers, out_dir),
        plot_wheel_angles(result.samples, result.summary, result.scenario, out_dir),
        plot_strokes(result.samples, result.summary, result.scenario, out_dir),
        plot_hydraulics(result.samples, result.summary, result.scenario, out_dir),
        plot_control(result.samples, result.summary, result.scenario, out_dir),
        plot_case_and_supply(result.samples, result.summary, result.scenario,
                             result.preflight, out_dir),
    )
