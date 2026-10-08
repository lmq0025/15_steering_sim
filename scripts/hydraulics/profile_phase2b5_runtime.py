from __future__ import annotations

import cProfile
import math
import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from steering_sim.hydraulics.solver import FastHydraulicModel


parser = argparse.ArgumentParser(); parser.add_argument("--duration", type=float, default=1.0)
args = parser.parse_args()
model = FastHydraulicModel.from_ir(ROOT / "hydraulic_audit")
model._use_algebraic_cache = True
model._use_jacobian_sparsity = False
inputs = {"pump_speed_rad_s": 1350.0 * 2.0 * math.pi / 60.0, "valve_command": lambda t: 0.2 + 0.1 * math.sin(math.pi * t)}
profiler = cProfile.Profile()
# Disabling caller-edge collection avoids a Windows memory spike caused by the
# millions of repeated local algebraic calls while retaining per-function
# call counts and timings for hotspot ranking.
profiler.enable(subcalls=False, builtins=False)
result = model.simulate(args.duration, inputs, output_points=51)
profiler.disable()
if not result.success:
    raise SystemExit(result.message)
profiler.dump_stats(str(ROOT / "hydraulic_audit" / "19_runtime_profile.prof"))
print(f"PROFILE WALL TIME = {result.wall_time_s:.6f} s")
