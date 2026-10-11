"""PHASE J0 plant diagnostics: valve polarity, static force authority, damping.

Read-only with respect to every official model.  Writes JSON/CSV/PNG artefacts
used by ``docs/integration/phase_J0_report.md``.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from steering_sim.hydraulics_lumped import LumpedHydraulicSystem  # noqa: E402
from steering_sim.j0_coupling.authority import (authority_as_dict,  # noqa: E402
                                                probe_channel_authority)
from steering_sim.j0_coupling.config import load_j0_config  # noqa: E402
from steering_sim.j0_coupling.diagnostics import (  # noqa: E402
    characterise_plant, passive_closed_loop_estimate)
from steering_sim.j0_coupling.reporting import (plot_diagnostics,  # noqa: E402
                                                write_summary_json)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(ROOT / "configs" / "j0" / "j0_config.json"))
    parser.add_argument("--output", default=str(ROOT / "outputs" / "j0" / "diagnostics"))
    parser.add_argument("--force-samples", type=int, default=9)
    args = parser.parse_args()

    config = load_j0_config(args.config)
    model = LumpedHydraulicSystem.fast_engineering()
    neutral = tuple(item.neutral_command for item in config.channels)

    authorities = probe_channel_authority(model, neutral_commands=neutral)
    plant = characterise_plant(model, neutral_commands=neutral,
                               force_samples=args.force_samples)

    mu = float(config.load["friction_coefficient"])
    gravity = 9.81
    # Road-load stiffness in the representative stroke coordinate, from the M1
    # geometry: k_x ~= K_q / J^2, estimated over the J0-04 configuration.
    road_stiffness_estimate = {
        "note": "仅给量级参考；精确值由运行器在具体工况上给出",
        "assumed_axle_mass_kg": 6 * 11.5e3,
        "mu": mu,
        "gravity_mps2": gravity,
    }

    payload = {
        "config": str(config.path),
        "channel_authority": [authority_as_dict(item) for item in authorities],
        "plant_characterisation": [
            {
                "channel": item.channel,
                "valve_alias": item.valve_alias,
                "command": item.command,
                "d_force_d_velocity_n_s_per_m": item.d_force_d_velocity_n_s_per_m,
                "d_force_d_displacement_n_per_m": item.d_force_d_displacement_n_per_m,
                "force_offset_n": item.force_offset_n,
                "force_window_n": list(item.force_window_n),
                "flags": list(item.flags),
            } for item in plant],
        "road_stiffness_estimate": road_stiffness_estimate,
        "linearised_stability": {},
    }
    for item in plant:
        payload["linearised_stability"][item.channel] = passive_closed_loop_estimate(
            item.d_force_d_velocity_n_s_per_m, item.d_force_d_displacement_n_per_m,
            road_stiffness_n_per_m=0.0)

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    write_summary_json(payload, output / "j0_diagnostics.json")
    plot_diagnostics(payload, output)

    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
