"""Integrate the 10-state reduced model with SYNTHETIC_TEST_ONLY inertia."""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from scipy.integrate import solve_ivp

from steering_sim.mechanics import (
    GENERALIZED_COORDINATES, ReducedMechanicalDynamics, SixAxleSteeringKinematics,
    load_mass_properties_csv, reference_geometry_from_file,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, default=Path("mechanical_model_input_spec_v1.0.yaml"))
    parser.add_argument(
        "--mass-properties", type=Path,
        default=Path("data/example/mechanical_mass_properties_SYNTHETIC_TEST_ONLY.csv"),
    )
    parser.add_argument("--output", type=Path, default=Path("outputs/R02C_synthetic_dynamics.png"))
    args = parser.parse_args()

    reference = reference_geometry_from_file(args.spec)
    body_ids = tuple(reference.bodies) + tuple(reference.links)
    properties = load_mass_properties_csv(args.mass_properties, body_ids)
    dynamics = ReducedMechanicalDynamics(
        SixAxleSteeringKinematics(reference), properties,
        allow_synthetic_test_only=True,
    )

    initial_state = np.r_[
        np.zeros(5),
        np.array([0.020, -0.015, 0.012, -0.010, 0.008]),
    ]
    evaluation_times = np.linspace(0.0, 0.15, 61)
    result = solve_ivp(
        lambda t, y: dynamics.mechanical_rhs(t, y, np.zeros(5)),
        (evaluation_times[0], evaluation_times[-1]), initial_state,
        t_eval=evaluation_times, rtol=2e-6, atol=1e-9,
    )
    if not result.success:
        raise RuntimeError(result.message)

    energy = np.array([
        dynamics.kinetic_energy(result.y[:5, index], result.y[5:, index])
        for index in range(result.y.shape[1])
    ])
    figure, axes = plt.subplots(3, 1, figsize=(10, 9), sharex=True, constrained_layout=True)
    for index, name in enumerate(GENERALIZED_COORDINATES):
        axes[0].plot(result.t, result.y[index], label=name)
        axes[1].plot(result.t, result.y[index + 5], label=name)
    axes[0].set_ylabel("q [rad]")
    axes[1].set_ylabel("q_dot [rad/s]")
    axes[2].plot(result.t, energy, color="black")
    axes[2].set_ylabel("kinetic energy [J]")
    axes[2].set_xlabel("time [s]")
    for axis in axes:
        axis.grid(True, alpha=0.25)
    axes[0].legend(ncol=5, loc="upper center", fontsize=8)
    figure.suptitle(
        "Synthetic dynamics verification only\nNOT customer vehicle prediction",
        fontsize=14,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(args.output, dpi=180)
    plt.close(figure)
    relative_drift = float(np.max(np.abs(energy - energy[0])) / energy[0])
    print(args.output.resolve())
    print(f"relative kinetic-energy drift: {relative_drift:.17e}")


if __name__ == "__main__":
    main()
