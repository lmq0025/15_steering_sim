"""Generate the R02-B kinematic acceptance/debug figures.

The +0.05 rad states are isolated numerical perturbations of the internal
generalized coordinates. They are not vehicle steering commands.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np

from steering_sim.mechanics import SixAxleSteeringKinematics, reference_geometry_from_file


LINK_COLORS = {"CROSS": "tab:red", "LONG": "tab:orange", "SIDE": "tab:blue"}
SWING_COLOR = "tab:purple"
ACTUATOR_COLOR = "tab:green"
WHEEL_COLOR = "black"
REFERENCE_COLOR = "0.65"
Q_NAMES = ("q_front", "q3", "q4", "q5", "q6")


def _belongs_to_axle(name: str, axle: int) -> bool:
    return f"_{axle}_" in name or name.endswith(f"_{axle}")


def _link_is_visible(name: str, axle: int | None) -> bool:
    if axle is None:
        return True
    if axle in (1, 2) and ("_12" in name or f"_{axle}_" in name):
        return True
    return _belongs_to_axle(name, axle)


def _draw_configuration(axis, model, solution, *, axle=None, reference=False):
    color_override = REFERENCE_COLOR if reference else None
    linestyle = "--" if reference else "-"
    linewidth = 1.15 if reference else 1.8

    for name, (point_a, point_b) in solution.link_endpoints.items():
        if not _link_is_visible(name, axle):
            continue
        kind = next(key for key in LINK_COLORS if key in name)
        axis.plot(
            [point_a[0], point_b[0]], [point_a[1], point_b[1]],
            color=color_override or LINK_COLORS[kind], linestyle=linestyle,
            linewidth=linewidth, zorder=2,
        )

    for name, actuator in model.reference.actuators.items():
        actuator_axle = int(name.split("_")[1])
        if axle is not None and actuator_axle != axle:
            continue
        point_a = solution.hardpoints[actuator.frame_point_id]
        point_b = solution.hardpoints[actuator.moving_point_id]
        axis.plot(
            [point_a[0], point_b[0]], [point_a[1], point_b[1]],
            color=color_override or ACTUATOR_COLOR, linestyle=linestyle,
            linewidth=linewidth, zorder=2,
        )

    for name, body in model.reference.bodies.items():
        if axle is not None and not _belongs_to_axle(name, axle):
            continue
        pivot = np.asarray(body.pivot)
        if name.startswith("SWING_"):
            for point_id in body.local_hardpoints:
                point = solution.hardpoints[point_id]
                axis.plot(
                    [pivot[0], point[0]], [pivot[1], point[1]],
                    color=color_override or SWING_COLOR, linestyle=linestyle,
                    linewidth=linewidth, zorder=3,
                )
        elif name.startswith("WHEEL_"):
            angle = solution.wheel_angles[name]
            direction = np.array([np.cos(angle), np.sin(angle)])
            ends = np.stack([pivot - 0.30 * direction, pivot + 0.30 * direction])
            axis.plot(
                ends[:, 0], ends[:, 1], color=color_override or WHEEL_COLOR,
                linestyle=linestyle, linewidth=2.6 if not reference else 1.4,
                zorder=4,
            )


def _solve_isolated(model, coordinate_index: int, value: float = 0.05):
    q = np.zeros(5)
    q[coordinate_index] = value
    model.reset()
    return model.solve(q)


def _axle_center(model, axle: int) -> float:
    return float(np.mean([
        model.reference.bodies[f"WHEEL_{axle}_{side}"].pivot[0]
        for side in ("NEG_Y", "POS_Y")
    ]))


def _format_local_axis(axis, model, axle: int) -> None:
    x_center = _axle_center(model, axle)
    axis.set_xlim(x_center - 1.35, x_center + 1.35)
    axis.set_ylim(-1.38, 1.38)
    axis.set_aspect("equal", adjustable="box")
    axis.grid(True, alpha=0.18)
    axis.set_xlabel("X [m]", fontsize=8)
    axis.set_ylabel("Y [m]", fontsize=8)
    axis.tick_params(labelsize=7)


def _local_metrics(zero, moved, axle: int) -> str:
    pos_wheel = np.degrees(
        moved.wheel_angles[f"WHEEL_{axle}_POS_Y"]
        - zero.wheel_angles[f"WHEEL_{axle}_POS_Y"]
    )
    neg_wheel = np.degrees(
        moved.wheel_angles[f"WHEEL_{axle}_NEG_Y"]
        - zero.wheel_angles[f"WHEEL_{axle}_NEG_Y"]
    )
    pos_swing = np.degrees(moved.swing_angles[f"SWING_{axle}_POS_Y"])
    neg_swing = np.degrees(moved.swing_angles[f"SWING_{axle}_NEG_Y"])
    lines = [
        f"POS_Y wheel change: {pos_wheel:+.3f} deg",
        f"NEG_Y wheel change: {neg_wheel:+.3f} deg",
        f"swing POS/NEG: {pos_swing:+.3f} / {neg_swing:+.3f} deg",
    ]
    if axle >= 3:
        lines.extend([
            f"actuator A: {moved.actuator_lengths[f'ACTUATOR_{axle}_A'] * 1e3:.3f} mm",
            f"actuator B: {moved.actuator_lengths[f'ACTUATOR_{axle}_B'] * 1e3:.3f} mm",
        ])
    return "\n".join(lines)


def _legend_handles(include_reference=False):
    handles = []
    if include_reference:
        handles.append(Line2D([0], [0], color=REFERENCE_COLOR, linestyle="--", label="q=0 reference"))
    handles.extend([
        Line2D([0], [0], color=SWING_COLOR, label="swing arm"),
        Line2D([0], [0], color=LINK_COLORS["CROSS"], label="cross tie rod"),
        Line2D([0], [0], color=LINK_COLORS["LONG"], label="long tie rod"),
        Line2D([0], [0], color=LINK_COLORS["SIDE"], label="side tie rod"),
        Line2D([0], [0], color=WHEEL_COLOR, linewidth=2.6, label="wheel"),
        Line2D([0], [0], color=ACTUATOR_COLOR, label="hydraulic actuator"),
    ])
    return handles


def create_vehicle_overview(model, zero, output: Path) -> None:
    figure, axis = plt.subplots(figsize=(17, 4.8), constrained_layout=True)
    _draw_configuration(axis, model, zero)
    for axle in range(1, 7):
        axis.text(_axle_center(model, axle), 1.18, f"Axle {axle}", ha="center", va="bottom", fontsize=9)
    all_points = np.stack(list(zero.hardpoints.values()))
    axis.scatter(all_points[:, 0], all_points[:, 1], s=7, color="0.15", zorder=5)
    x_min, x_max = float(all_points[:, 0].min()), float(all_points[:, 0].max())
    axis.text(x_min - 0.20, 1.12, "POS_Y", ha="right", va="center", color="tab:purple", weight="bold")
    axis.text(x_min - 0.20, -1.12, "NEG_Y", ha="right", va="center", color="tab:purple", weight="bold")
    axis.set_xlim(x_min - 1.25, x_max + 0.65)
    axis.set_ylim(-1.42, 1.42)
    axis.set_aspect("equal", adjustable="box")
    axis.grid(True, alpha=0.18)
    axis.set_xlabel("X [m] — vehicle front is toward +X")
    axis.set_ylabel("Y [m]")
    figure.suptitle("R02-B six-axle steering mechanism topology — q = 0", fontsize=14)
    figure.legend(handles=_legend_handles(), loc="outside upper center", ncol=6, fontsize=8)
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=180)
    plt.close(figure)


def create_local_kinematics(model, zero, output: Path) -> None:
    figure, axes = plt.subplots(2, 3, figsize=(16, 10), constrained_layout=True)
    for axle, axis in enumerate(axes.flat, start=1):
        coordinate_index = 0 if axle <= 2 else axle - 2
        moved = _solve_isolated(model, coordinate_index)
        _draw_configuration(axis, model, zero, axle=axle, reference=True)
        _draw_configuration(axis, model, moved, axle=axle)
        axis.set_title(f"Axle {axle} — {Q_NAMES[coordinate_index]} = +0.05 rad", fontsize=10)
        axis.text(
            0.02, 0.02, _local_metrics(zero, moved, axle), transform=axis.transAxes,
            ha="left", va="bottom", fontsize=7.3,
            bbox={"facecolor": "white", "edgecolor": "0.8", "alpha": 0.9, "pad": 2.5},
        )
        _format_local_axis(axis, model, axle)
    figure.suptitle(
        "Debug kinematic perturbation, NOT a physical vehicle steering command",
        fontsize=14,
    )
    figure.legend(handles=_legend_handles(include_reference=True), loc="outside upper center", ncol=7, fontsize=8)
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=180)
    plt.close(figure)


def create_single_dof_sweep(model, zero, output: Path) -> None:
    figure, axes = plt.subplots(2, 3, figsize=(16, 9.2), constrained_layout=True)
    cases = ((0, (1, 2)), (1, (3,)), (2, (4,)), (3, (5,)), (4, (6,)))
    for axis, (coordinate_index, axles) in zip(axes.flat, cases):
        moved = _solve_isolated(model, coordinate_index)
        for axle in axles:
            _draw_configuration(axis, model, zero, axle=axle, reference=True)
            _draw_configuration(axis, model, moved, axle=axle)
        centers = [_axle_center(model, axle) for axle in axles]
        axis.set_xlim(min(centers) - 1.40, max(centers) + 1.40)
        axis.set_ylim(-1.38, 1.38)
        axis.set_aspect("equal", adjustable="box")
        axis.grid(True, alpha=0.18)
        controlled = "Axles 1–2" if coordinate_index == 0 else f"Axle {axles[0]}"
        axis.set_title(f"{Q_NAMES[coordinate_index]} = +0.05 rad → {controlled}", fontsize=10)
        axis.set_xlabel("X [m]", fontsize=8)
        axis.set_ylabel("Y [m]", fontsize=8)
        axis.tick_params(labelsize=7)
    info_axis = axes.flat[-1]
    info_axis.axis("off")
    info_axis.text(
        0.5, 0.58,
        "Each case changes one internal generalized coordinate.\n"
        "All other coordinates remain exactly zero.\n\n"
        "The +0.05 rad value is a numerical debug perturbation,\n"
        "not a physical steering command or an operating limit.",
        ha="center", va="center", fontsize=11,
        bbox={"boxstyle": "round,pad=0.6", "facecolor": "0.97", "edgecolor": "0.75"},
    )
    figure.suptitle("R02-B single-DOF kinematic checks", fontsize=14)
    figure.legend(handles=_legend_handles(include_reference=True), loc="outside upper center", ncol=7, fontsize=8)
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=180)
    plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, default=Path("mechanical_model_input_spec_v1.0.yaml"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs"))
    args = parser.parse_args()

    model = SixAxleSteeringKinematics(reference_geometry_from_file(args.spec))
    model.reset()
    zero = model.solve(np.zeros(5))
    outputs = (
        args.output_dir / "R02B_vehicle_overview.png",
        args.output_dir / "R02B_local_kinematics.png",
        args.output_dir / "R02B_single_dof_sweep.png",
    )
    create_vehicle_overview(model, zero, outputs[0])
    create_local_kinematics(model, zero, outputs[1])
    create_single_dof_sweep(model, zero, outputs[2])
    for output in outputs:
        print(output.resolve())


if __name__ == "__main__":
    main()
