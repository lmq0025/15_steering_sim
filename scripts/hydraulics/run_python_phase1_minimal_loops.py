from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from steering_sim.hydraulics.elements import ComplianceLine, FixedOrifice, HJ020, PU001
from steering_sim.hydraulics.solver import ActuatorLoop, MinimalHydraulicLoop
from steering_sim.hydraulics.units import cc_per_rev_to_m3_per_rad, rpm_to_rad_s

ROOT = Path(r"E:\15_project")


def main() -> None:
    hydraulic = MinimalHydraulicLoop(
        PU001(cc_per_rev_to_m3_per_rad(10.0)), rpm_to_rad_s(1350.0),
        ComplianceLine(2e-3, 1.7e9), FixedOrifice(2e-6, 850.0), 1e5,
    )
    hres = hydraulic.simulate(0.05, 1e5)

    cylinder = HJ020(
        piston_diameter_m=0.025, rod_diameter_2_m=0.012, stroke_m=0.3,
        dead_volume_1_m3=50e-6, dead_volume_2_m3=50e-6,
        bulk_modulus_pa=1.7e9, leakage_m3_s_pa=2e-12,
        viscous_friction_n_s_m=300.0,
    )
    actuator = ActuatorLoop(
        cylinder, FixedOrifice(2e-7, 850.0), FixedOrifice(2e-7, 850.0),
        supply_pressure_pa=5e6, tank_pressure_pa=1e5, mass_kg=50.0, load_force_n=500.0,
    )
    ares = actuator.simulate(0.02, np.array([1e5, 1e5, 0.15, 0.0]))

    payload = {
        "surrogate_level": "LEVEL C SURROGATE",
        "solver": "scipy.integrate.solve_ivp(method='BDF')",
        "minimal_hydraulic_loop": {
            "success": hres.success,
            "samples": int(hres.time_s.size),
            "initial_pressure_pa": float(hres.state[0, 0]),
            "final_pressure_pa": float(hres.state[0, -1]),
        },
        "actuator_loop": {
            "success": ares.success,
            "samples": int(ares.time_s.size),
            "initial_state_si": ares.state[:, 0].tolist(),
            "final_state_si": ares.state[:, -1].tolist(),
            "final_time_s": float(ares.time_s[-1]),
        },
    }
    path = ROOT / "hydraulic_audit" / "15A_python_phase1_minimal_loop_results.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    if not hres.success or not ares.success:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
