"""PHASE J1-R2：由实测时间序列与批量结果生成代表性曲线。

只读 ``outputs/j1r2`` 里的真实数据，不重算、不美化。
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from steering_sim.engineering.mechanism import WHEEL_ORDER  # noqa: E402
from steering_sim.j0_coupling.reporting import configure_chinese_font  # noqa: E402

CHANNELS = ("channel_front", "channel_rear_1", "channel_rear_2", "channel_rear_3")
CHANNEL_LABEL = {"channel_front": "前组(一/二桥)", "channel_rear_1": "四桥组",
                 "channel_rear_2": "五桥组", "channel_rear_3": "六桥组"}


def _load_csv(path: Path) -> dict[str, np.ndarray]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    columns: dict[str, list[float]] = {}
    for row in rows:
        for key, value in row.items():
            try:
                columns.setdefault(key, []).append(float(value))
            except (TypeError, ValueError):
                pass
    return {key: np.asarray(values) for key, values in columns.items()}


def _figure(size):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    figure = plt.figure(figsize=size, dpi=120)
    return plt, figure


def _save(plt, figure, path: Path) -> Path:
    figure.tight_layout()
    figure.savefig(path, bbox_inches="tight")
    plt.close(figure)
    return path


def figure_dynamic(out_dir: Path, case: str) -> list[Path]:
    """代表工况（默认 +30°/10 km/h）的完整时序：行程、压力、阀命令、力、速度、轮角。"""
    path = out_dir / "dynamic" / f"{case}_timeseries.csv"
    if not path.exists():
        return []
    data = _load_csv(path)
    t = data["time_s"]
    produced: list[Path] = []

    plt, figure = _figure((11, 8))
    axes = figure.subplots(3, 1, sharex=True)
    for tag in CHANNELS:
        axes[0].plot(t, data[f"{tag}_x_ref_eff_m"] * 1000.0, "--",
                     label=f"{CHANNEL_LABEL[tag]} 目标")
        axes[0].plot(t, data[f"{tag}_x_m"] * 1000.0, "-",
                     label=f"{CHANNEL_LABEL[tag]} 实际")
        axes[1].plot(t, data[f"{tag}_valve_command"], label=CHANNEL_LABEL[tag])
        axes[2].plot(t, data[f"{tag}_pA_mpa_g"], label=f"{CHANNEL_LABEL[tag]} pA")
    axes[0].set_ylabel("行程 [mm]")
    axes[0].set_title(f"{case}：四通道目标/实际行程、阀命令与 A 腔压力（真实动态积分）")
    axes[1].set_ylabel("阀命令 [-]")
    axes[1].axhline(1.0, color="#b00020", lw=0.8, ls=":")
    axes[1].axhline(-1.0, color="#b00020", lw=0.8, ls=":")
    axes[2].set_ylabel("pA [MPa 表压]")
    axes[2].set_xlabel("时间 [s]")
    for axis in axes:
        axis.grid(alpha=0.3)
        axis.legend(fontsize=7, ncol=2)
    produced.append(_save(plt, figure, out_dir / "fig_r2_1_strokes_command_pressure.png"))

    plt, figure = _figure((11, 7))
    axes = figure.subplots(3, 1, sharex=True)
    for tag in CHANNELS:
        axes[0].plot(t, data[f"{tag}_hydraulic_force_n"] / 1000.0,
                     label=f"{CHANNEL_LABEL[tag]} 液压力")
        axes[0].plot(t, data[f"{tag}_load_force_n"] / 1000.0, "--", lw=0.9,
                     label=f"{CHANNEL_LABEL[tag]} 负载力")
        axes[1].plot(t, data[f"{tag}_v_m_s"] * 1000.0, label=CHANNEL_LABEL[tag])
        axes[2].plot(t, data[f"{tag}_Q_road_nm"] / 1000.0, label=CHANNEL_LABEL[tag])
    axes[0].set_ylabel("力 [kN]")
    axes[0].set_title(f"{case}：液压力 / 道路负载力、活塞速度、广义道路力矩")
    axes[1].set_ylabel("速度 [mm/s]")
    axes[2].set_ylabel("Q_road [kN·m]")
    axes[2].set_xlabel("时间 [s]")
    for axis in axes:
        axis.grid(alpha=0.3)
        axis.legend(fontsize=7, ncol=2)
    produced.append(_save(plt, figure, out_dir / "fig_r2_2_forces_velocity.png"))

    plt, figure = _figure((11, 7))
    axes = figure.subplots(2, 1, sharex=True)
    for wheel in WHEEL_ORDER:
        if wheel.startswith("axle3"):
            continue
        axes[0].plot(t, data[f"wheel_{wheel}_command_deg"], "--", lw=0.9,
                     label=f"{wheel} 指令")
        axes[0].plot(t, data[f"wheel_{wheel}_actual_deg"], "-", lw=1.1,
                     label=f"{wheel} 实际")
    error_key = [key for key in data if key.startswith("wheel_") and
                 key.endswith("_actual_deg")]
    worst = None
    for wheel in WHEEL_ORDER:
        if wheel.startswith("axle3"):
            continue
        error = np.abs(data[f"wheel_{wheel}_actual_deg"]
                       - data[f"wheel_{wheel}_command_deg"])
        axes[1].plot(t, error, label=wheel)
        worst = error if worst is None else np.maximum(worst, error)
    axes[0].set_ylabel("轮角 [°]")
    axes[0].set_title(f"{case}：十二轮指令角 / 液压实际角，以及逐轮跟踪误差")
    axes[1].set_ylabel("跟踪误差 [°]")
    axes[1].set_xlabel("时间 [s]")
    axes[1].axhline(0.25, color="#b00020", lw=0.8, ls=":")
    axes[1].axhline(-0.25, color="#b00020", lw=0.8, ls=":")
    for axis in axes:
        axis.grid(alpha=0.3)
        axis.legend(fontsize=6, ncol=3)
    produced.append(_save(plt, figure, out_dir / "fig_r2_3_wheel_tracking.png"))
    return produced


def figure_dynamic_summary(out_dir: Path, payload: dict) -> list[Path]:
    """所有代表工况的稳态/过渡峰值误差、饱和比例、最大压力。"""
    records = payload.get("records", [])
    if not records:
        return []
    labels = [r["case"] for r in records]
    steady = [r.get("steady_max_tracking_error_vs_command_deg") or 0.0 for r in records]
    peak = [r.get("max_tracking_error_vs_command_deg") or 0.0 for r in records]
    saturation = [(r.get("control_saturation_fraction") or 0.0) * 100.0 for r in records]
    pressure = [r.get("max_pressure_mpa_g") or 0.0 for r in records]

    plt, figure = _figure((12, 8))
    axes = figure.subplots(3, 1, sharex=True)
    x = np.arange(len(labels))
    axes[0].bar(x - 0.2, steady, width=0.4, label="稳态最大跟踪误差")
    axes[0].bar(x + 0.2, peak, width=0.4, label="过渡段峰值误差")
    axes[0].axhline(0.25, color="#b00020", lw=0.9, ls=":",
                    label="PASS 允许带 0.25°")
    axes[0].axhline(1.0, color="#8a6d00", lw=0.9, ls=":",
                    label="CONDITIONAL 允许带 1.0°")
    axes[0].set_ylabel("轮角误差 [°]")
    axes[0].set_yscale("log")
    axes[0].set_title("PHASE J1-R2 代表工况：跟踪误差、控制饱和与压力")
    axes[1].bar(x, saturation, color="#1b5e20")
    axes[1].set_ylabel("阀命令贴限幅占比 [%]")
    axes[2].bar(x, pressure, color="#0d47a1")
    axes[2].axhline(21.0, color="#b00020", lw=0.9, ls=":", label="溢流阀设定 21 MPa")
    axes[2].set_ylabel("最高腔压 [MPa]")
    axes[2].set_xticks(x)
    axes[2].set_xticklabels(labels, rotation=40, ha="right", fontsize=7)
    for axis in axes:
        axis.grid(alpha=0.3, axis="y")
        axis.legend(fontsize=7)
    return [_save(plt, figure, out_dir / "fig_r2_4_dynamic_summary.png")]


def figure_gate1(out_dir: Path, table: Path) -> list[Path]:
    if not table.exists():
        return []
    with table.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    angles = [float(r["目标角_deg"]) for r in rows]
    plt, figure = _figure((12, 7))
    axes = figure.subplots(2, 1, sharex=True)
    def column(name_cn: str) -> list[float] | None:
        if name_cn not in rows[0]:
            return None
        return [float(r[name_cn]) for r in rows]

    colours = {1: "#0d47a1", 2: "#1b5e20", 4: "#8a6d00", 5: "#b00020", 6: "#6a1b9a"}
    worst_rms = None
    for axle in range(1, 7):
        if axle == 3:
            continue
        colour = colours.get(axle, "#333333")
        ideal = column(f"理想_axle{axle}_right")
        mechanism = column(f"机构_axle{axle}_right")
        if ideal is not None:
            axes[0].plot(angles, ideal, "--", lw=0.8, color=colour)
        if mechanism is not None:
            axes[0].plot(angles, mechanism, "-", lw=1.2, color=colour,
                         label=f"{axle}桥右轮")
        if axle in (4, 5, 6) and ideal is not None and mechanism is not None:
            rms = np.sqrt((np.asarray(mechanism) - np.asarray(ideal)) ** 2)
            worst_rms = rms if worst_rms is None else np.maximum(worst_rms, rms)
    axes[0].set_ylabel("轮角 [°]")
    axes[0].set_title("61 个目标角：理想阿克曼角（虚线）与工程机构理论角（实线）")
    if worst_rms is not None:
        axes[1].plot(angles, worst_rms, color="#b00020",
                     label="后三桥最差单轮偏差")
    axes[1].set_ylabel("与理想阿克曼的偏差 [°]")
    axes[1].set_xlabel("一桥外侧目标角 [°]")
    for axis in axes:
        axis.grid(alpha=0.3)
        axis.legend(fontsize=8, ncol=2)
    return [_save(plt, figure, out_dir / "fig_r2_5_gate1_full_range.png")]


def figure_batch(out_dir: Path) -> list[Path]:
    path = out_dir / "j1r2_full_cases.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    speeds = sorted({float(r["车速_kmh"]) for r in rows})
    angles = sorted({float(r["目标角_deg"]) for r in rows})
    grid = np.zeros((len(speeds), len(angles)))
    for row in rows:
        if abs(float(row["摩擦系数"]) - 0.75) > 1.0e-9:
            continue
        index = (speeds.index(float(row["车速_kmh"])),
                 angles.index(float(row["目标角_deg"])))
        status = row["综合状态"]
        grid[index] = {"OK": 0.0, "ACKERMANN_TARGET_MISMATCH": 1.0,
                       "ACTUATOR_CAPABILITY_LIMITED": 2.0,
                       "VEHICLE_DYNAMIC_INFEASIBLE": 3.0}.get(status, 4.0)
    plt, figure = _figure((11, 6))
    axis = figure.add_subplot(111)
    image = axis.imshow(grid, aspect="auto", origin="lower", cmap="viridis",
                        extent=[min(angles), max(angles), min(speeds), max(speeds)])
    axis.set_xlabel("一桥外侧目标角 [°]")
    axis.set_ylabel("车速 [km/h]")
    axis.set_title("3111 工况（μ=0.75 切片）：综合状态分布\n"
                   "0=OK 1=机构阿克曼偏差 2=作动能力受限 3=目标轨迹超附着")
    figure.colorbar(image, ax=axis, ticks=[0, 1, 2, 3])
    return [_save(plt, figure, out_dir / "fig_r2_6_batch_status_map.png")]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "outputs" / "j1r2"))
    parser.add_argument("--case", default="低速5_+30deg")
    args = parser.parse_args()
    configure_chinese_font()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    produced = figure_dynamic(out, args.case)
    dynamic_json = out / "dynamic" / "j1r2_dynamic.json"
    if dynamic_json.exists():
        produced += figure_dynamic_summary(
            out, json.loads(dynamic_json.read_text(encoding="utf-8")))
    produced += figure_gate1(out, ROOT / "outputs" / "j1" / "gate1_angle_table.csv")
    produced += figure_batch(out)
    for path in produced:
        print("written:", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
