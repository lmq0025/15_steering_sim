"""CSV / figure / JSON artefacts for a PHASE J0 run."""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from .runner import J0CaseResult

COLORS = {
    "front": "#1f77b4",
    "rear_1": "#d62728",
    "rear_2": "#2ca02c",
    "rear_3": "#9467bd",
}
CHANNEL_LABEL = {
    "channel_front": "channel_front -> q_front (axles 1-2)",
    "channel_rear_1": "channel_rear_1 -> q4 (axle 4)",
    "channel_rear_2": "channel_rear_2 -> q5 (axle 5)",
    "channel_rear_3": "channel_rear_3 -> q6 (axle 6)",
}


def write_samples_csv(result: J0CaseResult, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = list(result.samples)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(keys)
        for row in zip(*(result.samples[key] for key in keys)):
            writer.writerow([f"{value:.12g}" for value in row])
    return path


def write_summary_json(payload: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=_default),
                    encoding="utf-8")
    return path


def _default(value: Any) -> Any:
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return str(value)


def _finish(fig, path: Path) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    import matplotlib.pyplot as plt
    plt.close(fig)
    return path


def plot_case(result: J0CaseResult, out_dir: Path, label: str | None = None) -> list[Path]:
    """Three required J0 figures for one operating case."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    samples = result.samples
    case = result.case
    if "time_s" not in samples or len(samples["time_s"]) == 0:
        return []
    time = samples["time_s"]
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = label or f"{case.id}_{case.target_outer_angle_deg:+.0f}deg_{case.speed_kmh:.0f}kmh"
    written: list[Path] = []

    # 1. target vs actual wheel angles
    fig, axes = plt.subplots(3, 1, figsize=(11, 10), sharex=True)
    groups = (("axle1_left", "axle1_right", "axle2_left", "axle2_right"),
              ("axle4_left", "axle4_right"),
              ("axle5_left", "axle5_right", "axle6_left", "axle6_right",
               "axle3_left", "axle3_right"))
    for axis, group in zip(axes, groups):
        for wheel in group:
            axis.plot(time, samples[f"wheel_{wheel}_actual_deg"],
                      label=f"{wheel} actual")
            axis.plot(time, samples[f"wheel_{wheel}_target_deg"], "--", linewidth=1.0,
                      label=f"{wheel} target")
        axis.set_ylabel("wheel angle [deg]")
        axis.grid(alpha=0.3)
        axis.legend(fontsize=7, ncol=2, loc="best")
        axis.axhline(0.0, color="k", linewidth=0.5, alpha=0.4)
    axes[0].set_title(f"{case.id}: target vs actual wheel angles "
                      f"(target {case.target_outer_angle_deg:+.1f} deg, "
                      f"{case.speed_kmh:.0f} km/h)")
    axes[-1].set_xlabel("time [s]")
    written.append(_finish(fig, out_dir / f"{tag}_fig1_wheel_angles.png"))

    # 2. target vs actual hydraulic stroke
    fig, axes = plt.subplots(4, 1, figsize=(11, 12), sharex=True)
    for axis, item in zip(axes, result.summary["channel_names"]):
        axis.plot(time, samples[f"{item}_x_ref_m"] * 1e3, "k--", linewidth=1.2,
                  label="target stroke")
        axis.plot(time, samples[f"{item}_x_m"] * 1e3, color=COLORS[item.split('_', 1)[1]],
                  label="actual stroke")
        axis.set_ylabel("stroke [mm]")
        axis.grid(alpha=0.3)
        axis.legend(fontsize=8, loc="best")
    axes[0].set_title(f"{case.id}: target vs actual hydraulic stroke")
    axes[-1].set_xlabel("time [s]")
    written.append(_finish(fig, out_dir / f"{tag}_fig2_strokes.png"))

    # 3. chamber pressures, hydraulic force, road load
    fig, axes = plt.subplots(3, 1, figsize=(11, 11), sharex=True)
    for item in result.summary["channel_names"]:
        axes[0].plot(time, samples[f"{item}_pA_mpa_g"], label=f"{item} pA")
        axes[0].plot(time, samples[f"{item}_pB_mpa_g"], "--", label=f"{item} pB")
        axes[1].plot(time, samples[f"{item}_hydraulic_force_n"] / 1e3,
                     label=f"{item} F_hyd")
        axes[1].plot(time, samples[f"{item}_load_force_n"] / 1e3, "--",
                     label=f"{item} F_load")
        axes[2].plot(time, samples[f"{item}_Q_road_nm"], label=f"{item} Q_road")
    axes[0].set_ylabel("chamber pressure [MPa(g)]")
    axes[1].set_ylabel("force [kN]")
    axes[2].set_ylabel("Q_road [N*m]")
    for axis in axes:
        axis.grid(alpha=0.3)
        axis.legend(fontsize=7, ncol=2, loc="best")
    axes[0].set_title(f"{case.id}: chamber pressures, hydraulic force vs road load, "
                      f"generalised road moment")
    axes[-1].set_xlabel("time [s]")
    written.append(_finish(fig, out_dir / f"{tag}_fig3_pressure_force_load.png"))
    return written


def plot_diagnostics(payload: dict[str, Any], out_dir: Path) -> list[Path]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    names = [item["channel"] for item in payload["plant_characterisation"]]
    damping = [item["d_force_d_velocity_n_s_per_m"] for item in payload["plant_characterisation"]]
    stiffness = [item["d_force_d_displacement_n_per_m"] for item in payload["plant_characterisation"]]
    window = [item["force_window_n"] for item in payload["plant_characterisation"]]

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5))
    axes[0].bar(names, damping, color="#d62728")
    axes[0].axhline(0.0, color="k", linewidth=0.8)
    axes[0].set_title("dF_hyd/dv (must be < 0 for a passive actuator)")
    axes[0].set_ylabel("N/(m/s)")
    axes[1].bar(names, stiffness, color="#ff7f0e")
    axes[1].axhline(0.0, color="k", linewidth=0.8)
    axes[1].set_title("dF_hyd/dx (must be < 0 for a restoring chamber)")
    axes[1].set_ylabel("N/m")
    axes[2].bar(names, [high - low for low, high in window], color="#1f77b4")
    axes[2].set_title("static force window width over the full command range")
    axes[2].set_ylabel("N")
    for axis in axes:
        axis.grid(alpha=0.3, axis="y")
        axis.tick_params(axis="x", labelrotation=20)
    written.append(_finish(fig, out_dir / "plant_characterisation.png"))
    return written


def markdown_table(rows: Iterable[Iterable[Any]], header: Iterable[Any]) -> str:
    header = [str(item) for item in header]
    lines = ["| " + " | ".join(header) + " |",
             "|" + "|".join("---" for _ in header) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(item) for item in row) + " |")
    return "\n".join(lines)
