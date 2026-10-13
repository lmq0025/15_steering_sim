"""Compare the GUI long-ramp step with the unchanged J1-R2 hydraulic step."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
for item in (ROOT, ROOT / "src"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from steering_sim.demo.scenario import DemoScenario
from steering_sim.demo.service import DemoService
from steering_sim.desktop.response_analysis import linear_ramp_profile
from steering_sim.j0_coupling.runner import CHANNEL_ORDER, WHEELS


def one(dt_h: float, suffix: str):
    service = DemoService(output_dir=ROOT / "outputs" / "desktop" / "r1" / "step_validation")
    service.runner.dt_h = dt_h
    service.runner.substeps = int(round(service.runner.dt_c / dt_h))
    service.runner.stride = max(1, int(round(0.01 / dt_h)))
    scenario = DemoScenario(target_outer_angle_deg=2.0, speed_kmh=5.0,
                            friction_coefficient=0.8, axle_mass_t=(11.5,) * 6,
                            duration_s=17.0, case_id=suffix)
    started = time.perf_counter()
    result = service.run(scenario, profile=linear_ramp_profile(12.0),
                         reference_start_outer_angle_deg=0.0,
                         reference_time_s=12.0, output_suffix=suffix,
                         generate_figures=False, allow_extended_duration=True)
    return result, time.perf_counter() - started


def main() -> Path:
    baseline, baseline_wall = one(0.0005, "BASELINE_0P5MS")
    optimized, optimized_wall = one(0.002, "GUI_2MS")
    wheel_delta = max(abs(float(baseline.samples[f"wheel_{wheel}_actual_deg"][-1]) -
                              float(optimized.samples[f"wheel_{wheel}_actual_deg"][-1]))
                      for wheel in WHEELS)
    cylinder_delta = max(abs(float(baseline.samples[f"{channel}_x_m"][-1]) -
                                 float(optimized.samples[f"{channel}_x_m"][-1]))
                         for channel in CHANNEL_ORDER)
    pressure_delta = max(
        abs(float(np.max(baseline.samples[key])) - float(np.max(optimized.samples[key])))
        for key in ("supply_pressure_front_mpa_g", "supply_pressure_rear_mpa_g"))
    payload = {
        "case": "0_to_2_deg_6_s_per_deg_plus_5_s_hold",
        "baseline_hydraulic_step_s": 0.0005,
        "gui_ramp_hydraulic_step_s": 0.002,
        "baseline_wall_s": baseline_wall,
        "gui_ramp_wall_s": optimized_wall,
        "speedup": baseline_wall / optimized_wall,
        "maximum_final_wheel_angle_difference_deg": wheel_delta,
        "maximum_final_cylinder_position_difference_m": cylinder_delta,
        "maximum_peak_supply_pressure_difference_mpa": pressure_delta,
        "baseline_completed": baseline.completed,
        "optimized_completed": optimized.completed,
    }
    path = ROOT / "outputs" / "desktop" / "r1" / "ramp_timestep_validation.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return path


if __name__ == "__main__":
    main()
