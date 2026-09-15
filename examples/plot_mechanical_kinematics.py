"""Debug plot for the frozen six-axle steering kinematics."""
from __future__ import annotations
import argparse
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np
from steering_sim.mechanics import SixAxleSteeringKinematics, reference_geometry_from_file

COLORS = {"CROSS": "tab:red", "LONG": "tab:orange", "SIDE": "tab:blue"}

def _plot_configuration(axis, model, solution, title):
    reference = model.reference
    for name, (a, b) in solution.link_endpoints.items():
        kind = next(key for key in COLORS if key in name)
        axis.plot([a[0], b[0]], [a[1], b[1]], color=COLORS[kind], lw=1.8,
                  label=kind.lower().replace("_", " "))
    for name, actuator in reference.actuators.items():
        a = solution.hardpoints[actuator.frame_point_id]
        b = solution.hardpoints[actuator.moving_point_id]
        axis.plot([a[0], b[0]], [a[1], b[1]], "--", color="tab:green", lw=1.4,
                  label="hydraulic actuator")
    for name, body in reference.bodies.items():
        pivot = np.asarray(body.pivot)
        if name.startswith("SWING_"):
            for point_id in body.local_hardpoints:
                point = solution.hardpoints[point_id]
                axis.plot([pivot[0], point[0]], [pivot[1], point[1]], color="0.25", lw=1.2,
                          label="swing arm")
        elif name.startswith("WHEEL_"):
            angle = solution.wheel_angles[name]
            direction = np.array([np.cos(angle), np.sin(angle)])
            ends = np.stack([pivot - 0.30 * direction, pivot + 0.30 * direction])
            axis.plot(ends[:, 0], ends[:, 1], color="black", lw=3, label="wheel")
    all_points = np.stack(list(solution.hardpoints.values()))
    axis.scatter(all_points[:, 0], all_points[:, 1], s=7, color="black", zorder=5)
    for axle in range(1, 7):
        wheel_names = (f"WHEEL_{axle}_NEG_Y", f"WHEEL_{axle}_POS_Y")
        x = np.mean([reference.bodies[name].pivot[0] for name in wheel_names])
        axis.text(x, 1.28, f"Axle {axle}", ha="center", va="bottom", fontsize=8)
    axis.text(-8.2, -1.40, "NEG_Y", ha="center", color="tab:purple")
    axis.text(-8.2, 1.40, "POS_Y", ha="center", color="tab:purple")
    axis.set(title=title, xlabel="X [m]", ylabel="Y [m]")
    axis.set_aspect("equal", adjustable="box")
    axis.grid(True, alpha=0.2)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, default=Path("mechanical_model_input_spec_v1.0.yaml"))
    parser.add_argument("--output", type=Path, default=Path("outputs/R02B_kinematics_check.png"))
    args = parser.parse_args()
    model = SixAxleSteeringKinematics(reference_geometry_from_file(args.spec))
    zero = model.solve(np.zeros(5))
    model.reset()
    turned = model.solve(np.full(5, 0.05))
    figure, axes = plt.subplots(2, 1, figsize=(16, 7), constrained_layout=True)
    _plot_configuration(axes[0], model, zero, "q = 0 reference configuration")
    _plot_configuration(axes[1], model, turned, "q = [0.05, 0.05, 0.05, 0.05, 0.05] rad")
    handles, labels = axes[0].get_legend_handles_labels()
    unique = dict(zip(labels, handles))
    figure.legend(unique.values(), unique.keys(), loc="outside upper center", ncol=6)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(args.output, dpi=180)
    plt.close(figure)
    print(args.output.resolve())

if __name__ == "__main__":
    main()
