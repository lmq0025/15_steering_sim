"""R02-E six-axle coordination demonstration (baseline, not vehicle validation)."""
from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from steering_sim.mechanics import (
    MechanicalSteeringIOModel, MultiAxleSteeringCoordinator, SteeringMode,
    load_calibration_parameter_set, load_steering_coordinator_config,
    reference_geometry_from_file, SixAxleSteeringKinematics,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"
GEOMETRY = ROOT / "mechanical_model_input_spec_v1.0.yaml"
IO_BASELINE = ROOT / "configs/mechanics/mechanical_io_baseline.yaml"
COORDINATION_BASELINE = ROOT / "configs/mechanics/multi_axle_steering_baseline.yaml"
CSV_PATH = OUTPUTS / "R02E_steering_demo.csv"
DEMO_PATH = OUTPUTS / "R02E_low_speed_counterphase_demo.png"
COMPARISON_PATH = OUTPUTS / "R02E_baseline_comparison.png"


def build_coordinator() -> MultiAxleSteeringCoordinator:
    reference = reference_geometry_from_file(GEOMETRY)
    parameters = load_calibration_parameter_set(IO_BASELINE, reference)
    model = MechanicalSteeringIOModel(SixAxleSteeringKinematics(reference), parameters)
    config = load_steering_coordinator_config(COORDINATION_BASELINE)
    return MultiAxleSteeringCoordinator(model, config)


def _fmt(value, digits=3):
    return "n/a" if value is None else f"{value:.{digits}f}"


def print_result(result) -> None:
    print("STEERING MODE")
    print(f"  {result.mode.value} / {result.preset}")
    print("ICR")
    print(f"  x={_fmt(result.x_icr_m, 6)} m, y={_fmt(result.y_icr_m, 6)} m")
    print("IDEAL AXLE ANGLES [deg]")
    for axle, item in result.axles.items():
        print(
            f"  Axle{axle}: mean={math.degrees(item.ideal_mean_rad):+.4f}, "
            f"POS_Y={math.degrees(item.ideal_pos_y_rad):+.4f}, "
            f"NEG_Y={math.degrees(item.ideal_neg_y_rad):+.4f}"
        )
    print("ACTUAL AXLE/WHEEL ANGLES [deg]")
    for axle, item in result.axles.items():
        print(
            f"  Axle{axle}: mean={math.degrees(item.actual_mean_rad):+.4f}, "
            f"POS_Y={math.degrees(item.actual_pos_y_rad):+.4f}, "
            f"NEG_Y={math.degrees(item.actual_neg_y_rad):+.4f}"
        )
    print("ACTUATOR STROKES [mm]")
    print(f"  Front baseline mapped position={result.actuator_input.front_position * 1e3:+.4f}")
    for axle in range(3, 7):
        item = result.axles[axle]
        print(
            f"  Axle{axle}: A={item.actuator_a_stroke_m * 1e3:+.4f}, "
            f"B={item.actuator_b_stroke_m * 1e3:+.4f}"
        )
    print("ACKERMANN ERRORS [deg, max wheel target mismatch]")
    for axle, item in result.axles.items():
        print(f"  Axle{axle}: {item.ackermann_error_deg:.4f} ({item.status})")
    print("FEASIBILITY")
    print(f"  feasible={result.feasible}")
    if not result.feasible:
        equivalent = result.target_axle1_mean_angle_deg * result.largest_feasible_scale
        print(
            f"  largest_feasible_scale={result.largest_feasible_scale:.6f}; "
            f"equivalent axle1 target={equivalent:+.4f} deg"
        )
    for axle in (5, 6):
        item = result.axles[axle]
        print(
            f"  Axle{axle}: q={item.q_rad:+.8f} rad, "
            f"residual={math.degrees(item.geometry_residual_rad):.5f} deg RMS, "
            f"branch={item.monotonic_branch_used}, "
            f"continuity={item.branch_continuity}, status={item.status}"
        )


def _wheel_segment(x, y, angle, length=0.9):
    direction = np.array([math.cos(angle), math.sin(angle)])
    center = np.array([x, y])
    return np.vstack((center - 0.5 * length * direction, center + 0.5 * length * direction))


def plot_vehicle_demo(result, coordinator, path: Path) -> None:
    fig = plt.figure(figsize=(14, 12), constrained_layout=True)
    grid = fig.add_gridspec(3, 1, height_ratios=(2.2, 1.25, 1.0))
    ax_vehicle = fig.add_subplot(grid[0])
    centers = coordinator.centers
    for axle in range(1, 7):
        ys = [centers[f"axle{axle}_{side}"][1] for side in ("NEG_Y", "POS_Y")]
        x = coordinator.axle_x_m(axle)
        ax_vehicle.plot([x, x], ys, color="#9aa0a6", linewidth=1.2)
        ax_vehicle.text(x, max(ys) + 0.42, f"Axle{axle}", ha="center", fontsize=10)
        for side in ("POS_Y", "NEG_Y"):
            wheel = f"axle{axle}_{side}"
            center = centers[wheel]
            zero = _wheel_segment(*center, 0.0)
            actual = _wheel_segment(*center, result.mechanical_output.wheel_angles_rad[wheel])
            ax_vehicle.plot(zero[:, 0], zero[:, 1], "--", color="#d0d3d4", linewidth=3)
            ax_vehicle.plot(actual[:, 0], actual[:, 1], color="black", linewidth=4)
    y_limit = max(abs(center[1]) for center in centers.values()) + 1.35
    if result.x_icr_m is not None and result.y_icr_m is not None:
        displayed_y = math.copysign(y_limit * 0.92, result.y_icr_m)
        ax_vehicle.scatter(
            [result.x_icr_m], [displayed_y], marker="^" if result.y_icr_m > 0 else "v",
            s=110, color="#d62728", zorder=5, label="ICR direction (off-scale)"
        )
        ax_vehicle.annotate(
            f"ICR: ({result.x_icr_m:.3f}, {result.y_icr_m:.3f}) m",
            (result.x_icr_m, displayed_y), xytext=(12, -5), textcoords="offset points",
            color="#d62728", fontweight="bold"
        )
        turn_text = "positive / toward POS_Y" if result.y_icr_m > 0 else "negative / toward NEG_Y"
        ax_vehicle.annotate(
            f"Turn direction: {turn_text}", xy=(0.98, 0.08), xycoords="axes fraction",
            xytext=(0.78, 0.08), textcoords="axes fraction",
            arrowprops={"arrowstyle": "->", "color": "#1f77b4"},
            color="#1f77b4", ha="right"
        )
    ax_vehicle.plot([], [], "--", color="#d0d3d4", linewidth=3, label="q=0 wheel direction")
    ax_vehicle.plot([], [], color="black", linewidth=4, label="actual mechanical wheel direction")
    ax_vehicle.set_ylim(-y_limit, y_limit)
    ax_vehicle.set_aspect("equal", adjustable="box")
    ax_vehicle.set_xlabel("Vehicle longitudinal X [m] — vehicle front is toward +X")
    ax_vehicle.set_ylabel("Y [m] (POS_Y upward)")
    ax_vehicle.set_title(
        f"{result.preset.replace('_', ' ')} — target Axle1 mean "
        f"{result.target_axle1_mean_angle_deg:+.1f} deg\n"
        "Generalized-Ackermann baseline through frozen CUSTOMER mechanics"
    )
    ax_vehicle.grid(alpha=0.2)
    ax_vehicle.legend(loc="upper center", bbox_to_anchor=(0.5, 1.0), ncol=3)

    ax_angles = fig.add_subplot(grid[1])
    axles = np.arange(1, 7)
    ideal = [math.degrees(result.axles[int(a)].ideal_mean_rad) for a in axles]
    pos = [math.degrees(result.axles[int(a)].actual_pos_y_rad) for a in axles]
    neg = [math.degrees(result.axles[int(a)].actual_neg_y_rad) for a in axles]
    width = 0.24
    ax_angles.bar(axles - width, ideal, width, label="ideal mean", color="#4c78a8")
    ax_angles.bar(axles, pos, width, label="actual POS_Y", color="#f58518")
    ax_angles.bar(axles + width, neg, width, label="actual NEG_Y", color="#54a24b")
    for axle in axles:
        item = result.axles[int(axle)]
        ax_angles.text(
            axle, max(ideal[axle - 1], pos[axle - 1], neg[axle - 1], 0) + 0.12,
            f"err {item.ackermann_error_deg:.2f}°", ha="center", fontsize=8
        )
    ax_angles.axhline(0.0, color="black", linewidth=0.8)
    ax_angles.set_xticks(axles, [f"Axle{a}" for a in axles])
    ax_angles.set_ylabel("Steering angle [deg]")
    ax_angles.set_title("Ideal mean vs actual POS_Y / NEG_Y; err = max target mismatch")
    ax_angles.legend(ncol=3)
    ax_angles.grid(axis="y", alpha=0.2)

    ax_stroke = fig.add_subplot(grid[2])
    labels = ["Front map"] + [f"{a}{side}" for a in range(3, 7) for side in ("A", "B")]
    values = [result.actuator_input.front_position * 1e3]
    for axle in range(3, 7):
        values.extend([
            result.axles[axle].actuator_a_stroke_m * 1e3,
            result.axles[axle].actuator_b_stroke_m * 1e3,
        ])
    colors = ["#999999"] + ["#e45756" if label.endswith("A") else "#72b7b2" for label in labels[1:]]
    ax_stroke.bar(labels, values, color=colors)
    ax_stroke.axhline(0.0, color="black", linewidth=0.8)
    ax_stroke.set_ylabel("Position / stroke [mm]")
    ax_stroke.set_title("Required R02-D inputs (Front is baseline mapped position; Axle3–6 are strokes)")
    ax_stroke.grid(axis="y", alpha=0.2)
    fig.suptitle(
        "R02-E coordination demonstration — BASELINE ONLY, NOT customer vehicle validation",
        fontsize=15, fontweight="bold"
    )
    fig.savefig(path, dpi=180)
    plt.close(fig)


def plot_comparison(public_result, hint_result, path: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(15, 6.5), sharey=True, constrained_layout=True)
    for ax, result, heading in zip(
        axes, (public_result, hint_result),
        ("PUBLIC: Axle1/2/3 vs Axle4/5/6", "CUSTOMER-HINT: Axle1/2 vs Axle3/4/5/6"),
    ):
        axles = np.arange(1, 7)
        ideal = [math.degrees(result.axles[int(a)].ideal_mean_rad) for a in axles]
        actual = [math.degrees(result.axles[int(a)].actual_mean_rad) for a in axles]
        ax.bar(
            axles, ideal,
            color=["#4c78a8" if value >= 0 else "#e45756" for value in ideal],
            alpha=0.8, label="ideal axle mean"
        )
        ax.plot(axles, actual, "ko-", linewidth=1.5, label="actual mechanical mean")
        ax.axhline(0.0, color="black", linewidth=0.8)
        ax.set_xticks(axles, [f"A{a}" for a in axles])
        ax.set_xlabel("Axle")
        ax.set_title(f"{heading}\nICR x={result.x_icr_m:.3f} m; feasible={result.feasible}")
        ax.grid(axis="y", alpha=0.2)
        ax.legend()
    axes[0].set_ylabel("Mean steering angle [deg]")
    fig.suptitle(
        "R02-E preset comparison at target Axle1 mean +2 deg\n"
        "Ideal ICR coordination and achieved frozen-mechanism response",
        fontsize=14, fontweight="bold"
    )
    fig.savefig(path, dpi=180)
    plt.close(fig)


def write_csv(results, path: Path) -> None:
    fields = [
        "preset", "mode", "target_axle1_mean_deg", "x_icr_m", "y_icr_m",
        "axle", "POS_Y_ideal_deg", "NEG_Y_ideal_deg", "POS_Y_actual_deg",
        "NEG_Y_actual_deg", "mean_actual_deg", "ackermann_error_deg", "q_rad",
        "actuator_A_stroke_mm", "actuator_B_stroke_mm", "feasible",
        "largest_feasible_scale", "geometry_residual", "geometry_status",
        "monotonic_branch_used", "branch_continuity",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for result in results:
            for axle, item in result.axles.items():
                writer.writerow({
                    "preset": result.preset,
                    "mode": result.mode.value,
                    "target_axle1_mean_deg": result.target_axle1_mean_angle_deg,
                    "x_icr_m": result.x_icr_m,
                    "y_icr_m": result.y_icr_m,
                    "axle": axle,
                    "POS_Y_ideal_deg": math.degrees(item.ideal_pos_y_rad),
                    "NEG_Y_ideal_deg": math.degrees(item.ideal_neg_y_rad),
                    "POS_Y_actual_deg": math.degrees(item.actual_pos_y_rad),
                    "NEG_Y_actual_deg": math.degrees(item.actual_neg_y_rad),
                    "mean_actual_deg": math.degrees(item.actual_mean_rad),
                    "ackermann_error_deg": item.ackermann_error_deg,
                    "q_rad": item.q_rad,
                    "actuator_A_stroke_mm": (
                        None if item.actuator_a_stroke_m is None
                        else item.actuator_a_stroke_m * 1e3
                    ),
                    "actuator_B_stroke_mm": (
                        None if item.actuator_b_stroke_m is None
                        else item.actuator_b_stroke_m * 1e3
                    ),
                    "feasible": result.feasible,
                    "largest_feasible_scale": result.largest_feasible_scale,
                    "geometry_residual": item.geometry_residual_rad,
                    "geometry_status": item.status,
                    "monotonic_branch_used": item.monotonic_branch_used,
                    "branch_continuity": item.branch_continuity,
                })


def main() -> None:
    parser = argparse.ArgumentParser(
        description="R02-E generalized-Ackermann mechanical baseline demonstration"
    )
    parser.add_argument("--preset", choices=("public", "customer-hint"), default="public")
    parser.add_argument("--axle1-deg", type=float, default=2.0)
    args = parser.parse_args()
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    coordinator = build_coordinator()
    primary = coordinator.coordinate(args.axle1_deg, args.preset)
    print_result(primary)
    plot_vehicle_demo(primary, coordinator, DEMO_PATH)

    coordinator.reset()
    public = coordinator.coordinate(2.0, "public")
    coordinator.reset()
    hint = coordinator.coordinate(2.0, "customer-hint")
    plot_comparison(public, hint, COMPARISON_PATH)

    results = []
    for preset in ("public", "customer-hint"):
        coordinator.reset()
        for target in (-2.0, -1.0, 1.0, 2.0):
            results.append(coordinator.coordinate(target, preset))
    write_csv(results, CSV_PATH)
    print(f"CSV: {CSV_PATH}")
    print(f"DEMO FIGURE: {DEMO_PATH}")
    print(f"COMPARISON FIGURE: {COMPARISON_PATH}")


if __name__ == "__main__":
    main()
