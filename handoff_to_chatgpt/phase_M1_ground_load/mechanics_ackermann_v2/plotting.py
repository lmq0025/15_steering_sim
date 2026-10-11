"""Required PHASE M1 figures."""
from __future__ import annotations

from pathlib import Path
import math

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .model import CaseInput, WHEEL_ORDER, PhaseM1Model


def _save(fig, path: Path) -> None:
    fig.tight_layout()
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def plot_topology(model: PhaseM1Model, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(12, 4.8))
    for axle in range(1, 7):
        left = model.centers[f"axle{axle}_left"]
        right = model.centers[f"axle{axle}_right"]
        ax.plot([right[0], left[0]], [right[1], left[1]], color="#667085", lw=2)
        color = "#98A2B3" if axle == 3 else ("#175CD3" if axle <= 2 else "#B54708")
        ax.scatter([left[0], right[0]], [left[1], right[1]], s=65, color=color, zorder=3)
        ax.text(np.mean([left[0], right[0]]), 1.12, f"A{axle}", ha="center", fontsize=8)
    ax.axvline(model.centers["axle3_left"][0], color="#98A2B3", ls="--", lw=1.4, label="Axle 3 fixed / ICR x reference")
    ax.annotate("+X forward", xy=(0.7, 0), xytext=(-1.0, 0), arrowprops={"arrowstyle": "->", "color": "black"})
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("x [m]")
    ax.set_ylabel("y [m], left positive")
    ax.set_ylim(-1.65, 1.55)
    ax.set_title("PHASE M1 six-axle topology", pad=14)
    ax.grid(alpha=0.22)
    ax.legend(loc="lower left")
    _save(fig, path)


def plot_turn_example(model: PhaseM1Model, target_deg: float, path: Path) -> None:
    geometry = model.solve_geometry(target_deg)
    masses = tuple(map(float, model.config["default_scan"]["axle_mass_t"]))
    loaded = model.solve_loaded_case(CaseInput(10.0, target_deg, 0.75, masses), geometry)
    fig, ax = plt.subplots(figsize=(11, 6))
    scale = 1.2
    for wheel in WHEEL_ORDER:
        x, y = model.centers[wheel]
        ideal = math.radians(geometry.ideal_ackermann_angle_deg[wheel])
        theoretical = math.radians(geometry.theoretical_angle_deg[wheel])
        actual = math.radians(loaded.actual_loaded_angle_deg[wheel])
        ax.plot([x - scale * math.cos(ideal), x + scale * math.cos(ideal)], [y - scale * math.sin(ideal), y + scale * math.sin(ideal)], color="#84ADFF", lw=3)
        ax.plot([x - scale * math.cos(theoretical), x + scale * math.cos(theoretical)], [y - scale * math.sin(theoretical), y + scale * math.sin(theoretical)], color="#175CD3", lw=2)
        ax.plot([x - scale * math.cos(actual), x + scale * math.cos(actual)], [y - scale * math.sin(actual), y + scale * math.sin(actual)], color="#D92D20", lw=1.4)
    if geometry.y_icr_m is not None:
        ax.text(
            0.02, 0.96,
            f"ICR = ({geometry.x_icr_m:+.3f}, {geometry.y_icr_m:+.3f}) m",
            transform=ax.transAxes, va="top", ha="left", fontsize=10,
        )
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlim(-18.5, 2.0)
    ax.set_ylim(-2.4, 2.4)
    ax.set_xlabel("x [m]")
    ax.set_ylabel("y [m]")
    direction = "Left" if target_deg > 0 else "Right"
    ax.set_title(f"{direction} turn example: outer target {target_deg:+.0f} deg, 10 km/h, mu=0.75")
    ax.plot([], [], color="#84ADFF", lw=3, label="ideal Ackermann")
    ax.plot([], [], color="#175CD3", lw=2, label="rigid-link theoretical")
    ax.plot([], [], color="#D92D20", lw=1.4, label="loaded actual (assumed stiffness)")
    ax.grid(alpha=0.2)
    ax.legend(loc="best")
    _save(fig, path)


def plot_theoretical_vs_loaded(model: PhaseM1Model, path: Path) -> None:
    masses = tuple(map(float, model.config["default_scan"]["axle_mass_t"]))
    geometry = model.solve_geometry(10.0)
    loaded = model.solve_loaded_case(CaseInput(20.0, 10.0, 0.75, masses), geometry)
    x = np.arange(len(WHEEL_ORDER))
    fig, ax = plt.subplots(figsize=(13, 5.2))
    ax.plot(x, [geometry.ideal_ackermann_angle_deg[w] for w in WHEEL_ORDER], "o--", label="Ideal Ackermann", color="#84ADFF")
    ax.plot(x, [geometry.theoretical_angle_deg[w] for w in WHEEL_ORDER], "o-", label="Theoretical rigid linkage", color="#175CD3")
    ax.plot(x, [loaded.actual_loaded_angle_deg[w] for w in WHEEL_ORDER], "s-", label="Loaded actual", color="#D92D20")
    ax.set_xticks(x, [w.replace("axle", "A").replace("_left", "L").replace("_right", "R") for w in WHEEL_ORDER], rotation=45)
    ax.set_ylabel("wheel steering angle [deg]")
    ax.set_title("Theoretical and loaded wheel angles: +10 deg outer target, 20 km/h, mu=0.75")
    ax.grid(alpha=0.25)
    ax.legend()
    _save(fig, path)


def plot_speed_comparison(model: PhaseM1Model, path: Path) -> None:
    masses = tuple(map(float, model.config["default_scan"]["axle_mass_t"]))
    geometry = model.solve_geometry(10.0)
    speeds = np.arange(0.0, 81.0, 5.0)
    selected = ("axle1_right", "axle2_right", "axle4_right", "axle5_right", "axle6_right")
    fig, ax = plt.subplots(figsize=(11, 5.5))
    for wheel in selected:
        values = [
            model.solve_loaded_case(CaseInput(float(speed), 10.0, 0.75, masses), geometry).actual_loaded_angle_deg[wheel]
            for speed in speeds
        ]
        ax.plot(speeds, values, marker="o", ms=3, label=wheel)
    ax.set_xlabel("speed [km/h]")
    ax.set_ylabel("loaded actual wheel angle [deg]")
    ax.set_title("Speed-dependent road feedback at +10 deg outer target, mu=0.75")
    ax.grid(alpha=0.25)
    ax.legend(ncol=2)
    _save(fig, path)


def generate_required_figures(model: PhaseM1Model, output_dir: str | Path) -> None:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    plot_topology(model, output_dir / "six_axle_topology.png")
    plot_turn_example(model, 10.0, output_dir / "left_turn_example.png")
    plot_turn_example(model, -10.0, output_dir / "right_turn_example.png")
    plot_theoretical_vs_loaded(model, output_dir / "theoretical_vs_loaded_angles.png")
    plot_speed_comparison(model, output_dir / "speed_angle_comparison.png")
