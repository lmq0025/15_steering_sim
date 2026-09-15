"""SYNTHETIC / BASELINE ONLY actuator-position to wheel-angle demonstration."""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from steering_sim.mechanics import (
    GENERALIZED_COORDINATES, MechanicalSteeringIOModel, PositionDefinition,
    SixAxleSteeringKinematics, load_calibration_parameter_set,
    reference_geometry_from_file,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, default=Path("mechanical_model_input_spec_v1.0.yaml"))
    parser.add_argument("--baseline", type=Path, default=Path("configs/mechanics/mechanical_io_baseline.yaml"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs"))
    args = parser.parse_args()

    reference = reference_geometry_from_file(args.spec)
    parameters = load_calibration_parameter_set(args.baseline, reference)
    model = MechanicalSteeringIOModel(SixAxleSteeringKinematics(reference), parameters)
    values = np.linspace(-0.05, 0.05, 21)
    rows = []
    cases = {}
    for coordinate_index, coordinate_name in enumerate(GENERALIZED_COORDINATES):
        model.reset()
        case_rows = []
        for value in values:
            q = np.zeros(5)
            q[coordinate_index] = value
            actuator_input = model.inputs_from_generalized_coordinates(
                q, PositionDefinition.STROKE_FROM_REFERENCE_M
            )
            output = model.solve_from_actuators(actuator_input)
            row = {
                "case": coordinate_name,
                "position_definition": PositionDefinition.STROKE_FROM_REFERENCE_M.value,
                "front_position_m": actuator_input.front_position,
                **{f"axle{axle}_{side}_position_m": getattr(actuator_input, f"axle{axle}_{side}").value_m
                   for axle in range(3, 7) for side in ("A", "B")},
                **{name: output.generalized_coordinates[name] for name in GENERALIZED_COORDINATES},
                **{f"{name}_angle_rad": angle for name, angle in output.wheel_angles_rad.items()},
                "maximum_actuator_residual_m": max(map(abs, output.actuator_residuals.values())),
                "maximum_constraint_residual_m": max(map(abs, output.constraint_residuals.values())),
                "valid": output.valid,
            }
            rows.append(row)
            case_rows.append((actuator_input, output))
        cases[coordinate_name] = case_rows

    figure, axes = plt.subplots(2, 3, figsize=(14, 8.5), constrained_layout=True)
    for axle, axis in enumerate(axes.flat, start=1):
        coordinate_name = "q_front" if axle <= 2 else f"q{axle}"
        case_rows = cases[coordinate_name]
        if axle <= 2:
            x = np.array([item[0].front_position for item in case_rows]) * 1e3
            x_label = "front baseline position [mm]"
        else:
            x = np.array([getattr(item[0], f"axle{axle}_A").value_m for item in case_rows]) * 1e3
            x_label = f"Axle {axle} actuator A stroke input [mm]"
        for side, color in (("POS_Y", "tab:blue"), ("NEG_Y", "tab:orange")):
            wheel = f"axle{axle}_{side}"
            y = np.degrees([item[1].wheel_angles_rad[wheel] for item in case_rows])
            axis.plot(x, y, color=color, label=side)
        axis.set_title(f"Axle {axle}")
        axis.set_xlabel(x_label, fontsize=8)
        axis.set_ylabel("wheel angle [deg]")
        axis.grid(True, alpha=0.25)
        axis.legend(fontsize=8)
    figure.suptitle(
        "SYNTHETIC / BASELINE ONLY\nActuator position → frozen mechanical geometry → wheel angle",
        fontsize=14,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    image_path = args.output_dir / "R02D_actuator_to_wheel_demo.png"
    csv_path = args.output_dir / "R02D_actuator_to_wheel_demo.csv"
    figure.savefig(image_path, dpi=180)
    plt.close(figure)
    pd.DataFrame(rows).to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(image_path.resolve())
    print(csv_path.resolve())


if __name__ == "__main__":
    main()
