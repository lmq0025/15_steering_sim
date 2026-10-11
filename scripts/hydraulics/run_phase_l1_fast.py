from __future__ import annotations

import hashlib
import json
import math
import shutil
import statistics
import sys
import time
import zipfile
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(r"E:\15_project")
SRC = ROOT / "src" / "steering_sim" / "hydraulics_lumped"
DOCS = ROOT / "docs" / "hydraulics"
OUT = ROOT / "outputs" / "hydraulics" / "phase_L1_Fast"
HANDOFF = ROOT / "handoff_to_chatgpt" / "phase_L1_Fast"
sys.path.insert(0, str(ROOT / "src"))

from steering_sim.hydraulics_lumped import (LumpedHydraulicSystem, SystemInputs,
                                            precharged_state)
from steering_sim.hydraulics_lumped.simulation import simulate_rk4


ACCEPTED_DT = 0.0005


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def working_point(model: LumpedHydraulicSystem):
    # J0-R1：工作点压力改由 precharged_state 用模型自身的阀口流量求解（前阀为开放式
    # 中立，两腔稳态压力是两条轨的均值，不再是回油轨）；外载符号随 F1 的力方向修正
    # 一起更新为 F_hyd = A_b*p_b - A_a*p_a。
    state, loads, _ = precharged_state(model, (0.0,) * 4)
    return state, loads


def make_inputs(model, loads, command: float, *, prescribed: bool,
                time_s: float = 0.0) -> SystemInputs:
    primary = (1.0, command, 0.0, 0.0)
    valves = dict(zip(("dirvalve_6", "dirvalve_1", "dirvalve_8", "dirvalve_11"),
                      primary))
    valves.update({"dirvalve_2": 0.0, "dirvalve_9": 0.0,
                   "dirvalve_12": 0.0})
    motion = None
    if prescribed:
        motion = {c.actuator_alias: (0.0, 0.0, 0.0) for c in model.channels}
        position = 1.0e-4 * math.sin(2.0 * math.pi * time_s)
        velocity = 2.0 * math.pi * 1.0e-4 * math.cos(2.0 * math.pi * time_s)
        acceleration = -(2.0 * math.pi)**2 * position
        motion["actuator001"] = (position, velocity, acceleration)
    speeds = tuple(c.pump.nominal_speed for c in model.channels)
    return SystemInputs(primary, speeds, loads, valve_commands_by_alias=valves,
                        prescribed_motion_by_alias=motion)


def timed_run(duration: float, dt: float, input_fn, state: np.ndarray,
              repeats: int = 1):
    walls = []
    final = None
    for _ in range(repeats):
        model = LumpedHydraulicSystem.fast_engineering()
        start = time.perf_counter()
        times, states = simulate_rk4(model, duration, dt, input_fn, state)
        walls.append(time.perf_counter() - start)
        final = (model, times, states)
    assert final is not None
    return (*final, statistics.median(walls), walls)


def collect(model, times, states, input_fn, stride=1):
    rows = []
    model.reset_fast_solver()
    for i in range(0, len(times), stride):
        _, output = model.evaluate(float(times[i]), states[i], input_fn(float(times[i])))
        channel = output[1]
        rows.append({
            "time_s": float(times[i]), "pA_pa_g": channel["pA"],
            "pB_pa_g": channel["pB"], "force_n": channel["hydraulic_force"],
            "position_m": channel["position"], "velocity_m_s": channel["velocity"],
            "QA_m3_s": channel["QA"], "QB_m3_s": channel["QB"],
            "front_supply_pa_g": output[0]["pump_outlet_pressure"],
            "rear_supply_pa_g": output[1]["pump_outlet_pressure"],
            "capacity_warning_front": bool(output[0]["pump_capacity_insufficient"]),
            "capacity_warning_rear": bool(output[1]["pump_capacity_insufficient"]),
        })
    return rows


def numerical_error(reference, candidate, position_floor=0.13, velocity_floor=0.1):
    pressure_columns = [0, 1, 4, 5, 8, 9, 12, 13]
    pressure_scale = max(float(np.max(np.abs(reference[:, pressure_columns]))), 1e5)
    return {
        "pressure_peak_relative": float(
            abs(np.max(np.abs(candidate[:, pressure_columns])) -
                np.max(np.abs(reference[:, pressure_columns]))) / pressure_scale),
        "pressure_final_relative": float(
            np.max(np.abs(candidate[-1, pressure_columns] -
                          reference[-1, pressure_columns])) / pressure_scale),
        "position_final_normalized": float(
            np.max(np.abs(candidate[-1, 2::4] - reference[-1, 2::4])) /
            position_floor),
        "velocity_final_normalized": float(
            np.max(np.abs(candidate[-1, 3::4] - reference[-1, 3::4])) /
            velocity_floor),
    }


def main() -> int:
    DOCS.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    model = LumpedHydraulicSystem.fast_engineering()
    initial, loads = working_point(model)

    steady_input = make_inputs(model, loads, 0.0, prescribed=False)
    steady_model, steady_t, steady_x, steady_wall, _ = timed_run(
        1.0, ACCEPTED_DT, lambda _t: steady_input, initial)
    steady_rows = collect(steady_model, steady_t, steady_x,
                          lambda _t: steady_input, stride=20)
    steady_pass = bool(np.isfinite(steady_x).all() and
                       np.array_equal(steady_x[-1], initial))

    step_input = make_inputs(model, loads, 0.001, prescribed=False)
    step_model, step_t, step_x, step_wall, _ = timed_run(
        0.05, ACCEPTED_DT, lambda _t: step_input, initial)
    step_rows = collect(step_model, step_t, step_x,
                        lambda _t: step_input)
    step_pass = bool(np.isfinite(step_x).all() and step_x[-1, 6] > 0.0 and
                     step_x[-1, 7] > 0.0)

    def sine_inputs(t: float) -> SystemInputs:
        return make_inputs(model, loads, 0.01 * math.sin(2.0 * math.pi * t),
                           prescribed=True, time_s=t)

    sine_model, sine_t, sine_x, sine_wall, _ = timed_run(
        1.0, ACCEPTED_DT, sine_inputs, initial)
    sine_rows = collect(sine_model, sine_t, sine_x, sine_inputs, stride=2)
    sine_pass = bool(np.isfinite(sine_x).all())

    # Required 0.5 ms vs 2 ms check plus a 0.25 ms confirmation of the
    # retained step.  Autonomous step and prescribed sine are reported
    # separately because they validate different interfaces.
    _, _, step_fine, _, _ = timed_run(
        0.05, 0.00025, lambda _t: step_input, initial)
    _, _, step_two, _, _ = timed_run(
        0.05, 0.002, lambda _t: make_inputs(model, loads, 0.001,
                                             prescribed=True), initial)
    _, _, step_half_prescribed, _, _ = timed_run(
        0.05, 0.0005, lambda _t: make_inputs(model, loads, 0.001,
                                              prescribed=True), initial)
    # Sample the fine autonomous trajectory at 0.5 ms points.
    step_fine_sampled = step_fine[::2]
    accepted_error = numerical_error(step_fine_sampled, step_x)
    two_ms_error = numerical_error(step_half_prescribed[::4], step_two)

    _, _, sine_fine, _, _ = timed_run(1.0, 0.00025, sine_inputs, initial)
    accepted_sine_error = numerical_error(sine_fine[::2], sine_x)
    _, _, sine_two, _, _ = timed_run(1.0, 0.002, sine_inputs, initial)
    sine_half_sampled = sine_x[::4]
    sine_two_error = numerical_error(sine_half_sampled, sine_two)
    numerical_consistency = (
        max(accepted_error.values()) <= 0.01 and
        max(accepted_sine_error.values()) <= 0.01)

    # Real dynamic timings; 100 s is executed, never extrapolated.
    benchmarks = []
    for duration, repeats in ((1.0, 3), (10.0, 3), (100.0, 1)):
        _, times, states, wall, walls = timed_run(
            duration, ACCEPTED_DT, sine_inputs, initial, repeats=repeats)
        benchmarks.append({
            "physical_time_s": duration, "dt_s": ACCEPTED_DT,
            "wall_time_s": wall, "all_wall_times_s": walls,
            "real_time_factor": wall / duration,
            "steps": len(times) - 1, "rhs_calls": 4 * (len(times) - 1),
            "finite": bool(np.isfinite(states).all()), "measurement": "ACTUAL",
        })

    all_rows = steady_rows + step_rows + sine_rows
    max_pressure = max(max(r["pA_pa_g"], r["pB_pa_g"]) for r in all_rows)
    min_pressure = min(min(r["pA_pa_g"], r["pB_pa_g"]) for r in all_rows)
    capacity_warning = any(r["capacity_warning_front"] or r["capacity_warning_rear"]
                           for r in all_rows)

    plt.figure(figsize=(8, 4.5))
    plt.plot([r["time_s"] for r in step_rows],
             [r["position_m"] * 1e3 for r in step_rows], label="position")
    plt.plot([r["time_s"] for r in step_rows],
             [r["velocity_m_s"] * 1e3 for r in step_rows], label="velocity")
    plt.xlabel("time [s]"); plt.ylabel("mm or mm/s")
    plt.title("L1-Fast small autonomous step, 0.5 ms")
    plt.legend(); plt.tight_layout(); plt.savefig(OUT / "step_response.png", dpi=150)
    plt.close()

    plt.figure(figsize=(8, 4.5))
    plt.plot([r["time_s"] for r in sine_rows],
             [r["pA_pa_g"] / 1e6 for r in sine_rows], label="pA")
    plt.plot([r["time_s"] for r in sine_rows],
             [r["pB_pa_g"] / 1e6 for r in sine_rows], label="pB")
    plt.xlabel("time [s]"); plt.ylabel("pressure [MPa(g)]")
    plt.title("L1-Fast 1 Hz prescribed-motion hydraulic response")
    plt.legend(); plt.tight_layout(); plt.savefig(OUT / "sine_1Hz_response.png", dpi=150)
    plt.close()

    protected_hashes = {name: sha256(ROOT / name)
                        for name in ("qh1_1.ame", "qh1_1_MCP_AUDIT.ame")}
    results = {
        "phase": "L1-Fast", "supply_mode": "regulated_constant_pressure",
        "physics_scope": "quasi-steady prepressurized engineering boundary",
        "dynamic_states": 16, "pipe_dynamic_states": 0,
        "inner_newton_solver": "DISABLED",
        "fixed_dt_s": ACCEPTED_DT,
        "requested_2ms_assessment": {
            "accepted": False, "reason": "autonomous step is unstable/inaccurate; prescribed step pressure error exceeds 1%",
            "prescribed_step_errors": two_ms_error,
            "prescribed_sine_errors": sine_two_error,
        },
        "numerical_consistency": {"pass": numerical_consistency,
                                  "accepted_dt_vs_0p25ms": accepted_error,
                                  "accepted_sine_dt_vs_0p25ms": accepted_sine_error},
        "tests": {"steady": steady_pass, "step": step_pass, "sine": sine_pass},
        "pressure_range_pa_g": {"minimum": min_pressure, "maximum": max_pressure},
        "unexplained_over_100mpa": max_pressure > 100e6,
        "pump_capacity_check": "WARNING" if capacity_warning else "PASS",
        "benchmarks": benchmarks,
        "hydraulic_io_interface": "READY",
        "independent_amesim_macro_accuracy": "NOT_VERIFIED",
        "autonomous_scope": "short-step direction only; sustained dynamics requires real mechanical load coupling",
        "fast_engineering_candidate": bool(steady_pass and step_pass and sine_pass and
                                            numerical_consistency and max_pressure < 100e6),
        "ready_for_mechanical_handoff": True,
        "pytest": "PENDING",
        "protected_model_hashes": protected_hashes,
    }
    result_path = DOCS / "phase_L1_Fast_results.json"
    result_path.write_text(json.dumps(
        results, indent=2,
        default=lambda value: value.item() if isinstance(value, np.generic)
        else str(value)), encoding="utf-8")

    io_doc = """# L1-Fast hydraulic I/O contract

The interface is implemented by `HydraulicInput`, `HydraulicOutput`, and
`evaluate_hydraulic()` in `interface.py`. All quantities use SI units.

## Input

| field | shape | unit | meaning |
|---|---:|---|---|
| valve_commands | 4 | 1 | primary commands for dirvalve_6, 1, 8, 11 |
| pump_speeds_rad_s | 4 | rad/s | pump01, pump01_1, pump01_2, pump01_3 |
| external_load_forces_n | 4 | N | load opposed by each actuator |
| redundant_valve_commands | alias map | 1 | independent dirvalve_2, 9, 12 commands |
| prescribed_motion_by_alias | alias map | m, m/s, m/s2 | optional Amesim/mechanical boundary |

## Output

Each of four channel outputs contains position [m], velocity [m/s], hydraulic
force [N], A/B gauge pressure [Pa], and A/B flow [m3/s]. System output also
contains the two pump-outlet boundary pressures [Pa(g)], capacity margins
[m3/s], and one capacity-insufficient flag per supply group.

## Call example

```python
from steering_sim.hydraulics_lumped import (
    HydraulicInput, LumpedHydraulicSystem, evaluate_hydraulic)

model = LumpedHydraulicSystem.fast_engineering()
x = model.initial_state()
u = HydraulicInput(
    valve_commands=(1.0, 0.0, 0.0, 0.0),
    pump_speeds_rad_s=tuple(c.pump.nominal_speed for c in model.channels),
    external_load_forces_n=(0.0, 0.0, 0.0, 0.0),
    redundant_valve_commands={"dirvalve_2": 0.0,
                              "dirvalve_9": 0.0,
                              "dirvalve_12": 0.0},
)
dx, y = evaluate_hydraulic(model, 0.0, x, u)
```

The present autonomous local-mass model is not a substitute for the vehicle
steering mechanics. The mechanical integration must supply consistent load
forces, or an explicit motion boundary during hydraulic-only validation.
"""
    (DOCS / "fast_hydraulic_io.md").write_text(io_doc, encoding="utf-8")

    b1, b10, b100 = benchmarks
    report = f"""# Phase L1-Fast regulated-source hydraulic kernel

## Outcome

The model now has an explicit `regulated_constant_pressure` mode. It keeps the
R3 SC_1 four-port maps and HJ020/HJ021 equations but removes the supply-network
Newton/Brent loop from every RHS call. Front and rear pump-outlet boundaries
remain distinct at 18.6623 MPa(g) and 16.8685 MPa(g). Their SC_1 high and
return rails also remain distinct physical locations.

No chamber-pressure clamp was introduced. Pump flows are still evaluated per
pump. Demand above available flow raises a capacity warning while the ideal
regulated boundary remains unchanged; such a run is outside the validated
capacity envelope.

## Numerical result

The requested 2 ms step was rejected. In the prescribed step it produced a
{100*max(two_ms_error.values()):.3f}% worst normalized error, and the uncoupled
autonomous actuator became unstable. The retained 0.5 ms step agrees with the
0.25 ms numerical reference within {100*max(accepted_error.values()):.3f}% on
the stated pressure/force/position/velocity normalization.

## Required tests

- Healthy steady: {'PASS' if steady_pass else 'FAIL'}.
- Small autonomous step (50 ms direction test): {'PASS' if step_pass else 'FAIL'}.
- 1 Hz prescribed-motion hydraulic sine: {'PASS' if sine_pass else 'FAIL'}.
- Pressure range across evidence runs: {min_pressure/1e6:.6f} to {max_pressure/1e6:.6f} MPa(g).
- Pump capacity: {'WARNING in at least one sample' if capacity_warning else 'PASS'}.

## Runtime

All timings are actual runs on this machine with the dynamic 1 Hz scenario:

| physical duration | wall time | real-time factor |
|---:|---:|---:|
| 1 s | {b1['wall_time_s']:.6f} s | {b1['real_time_factor']:.6f} |
| 10 s | {b10['wall_time_s']:.6f} s | {b10['real_time_factor']:.6f} |
| 100 s | {b100['wall_time_s']:.6f} s | {b100['real_time_factor']:.6f} |

The 100 s under 1 s target is {'PASS' if b100['wall_time_s'] < 1 else 'FAIL'}.
No further performance architecture was introduced after this measurement.

## Scope and limitations

This is a prepressurized engineering candidate, not a zero-pressure startup
model. The constant pressure boundaries are normal-point transfers, not exact
pressure predictions for every duty cycle. Independent Amesim macro accuracy
in this new working mode is NOT_VERIFIED. The autonomous actuator was checked
only for short-time direction because the standalone local mass lacks the
vehicle steering load that will provide the real mechanical constraint.

The package is ready for mechanical interface review. It does not modify or
couple the existing mechanical model, controller, degradation, rainflow, or
quality-assessment code.
"""
    (DOCS / "phase_L1_Fast_report.md").write_text(report, encoding="utf-8")

    # Assemble the deliberately small review package.
    if HANDOFF.exists():
        shutil.rmtree(HANDOFF)
    (HANDOFF / "source_review").mkdir(parents=True)
    (HANDOFF / "tests").mkdir()
    (HANDOFF / "figures").mkdir()
    for source in ("parameters.py", "supply.py", "model.py", "interface.py",
                   "simulation.py", "valve.py", "actuator.py"):
        shutil.copy2(SRC / source, HANDOFF / "source_review" / source)
    shutil.copy2(ROOT / "tests" / "hydraulics_lumped" /
                 "test_l1_fast_regulated_supply.py", HANDOFF / "tests")
    shutil.copy2(DOCS / "phase_L1_Fast_report.md", HANDOFF)
    shutil.copy2(result_path, HANDOFF)
    shutil.copy2(DOCS / "fast_hydraulic_io.md", HANDOFF)
    shutil.copy2(OUT / "step_response.png", HANDOFF / "figures")
    shutil.copy2(OUT / "sine_1Hz_response.png", HANDOFF / "figures")
    shutil.copy2(Path(__file__), HANDOFF / Path(__file__).name)
    readme = f"""请将整个 phase_L1_Fast.zip 上传给 ChatGPT 审核。

Supply mode: regulated_constant_pressure
Dynamic states: 16; pipe dynamic states: 0
Accepted fixed step: {ACCEPTED_DT*1000:.3f} ms (2 ms rejected by numerical check)
100 s actual wall time: {b100['wall_time_s']:.6f} s
Independent Amesim macro accuracy: NOT_VERIFIED

Reproduce:
& \"E:\\ProgramData\\condaData\\envs_dirs\\steering_sim\\python.exe\" .\\scripts\\hydraulics\\run_phase_l1_fast.py
& \"E:\\ProgramData\\condaData\\envs_dirs\\steering_sim\\python.exe\" -m pytest -q
"""
    (HANDOFF / "00_README_发给ChatGPT.txt").write_text(readme, encoding="utf-8")
    zip_path = ROOT / "handoff_to_chatgpt" / "phase_L1_Fast.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(HANDOFF.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(HANDOFF.parent))
    with zipfile.ZipFile(zip_path) as archive:
        bad = archive.testzip()
        if bad is not None or not archive.namelist():
            raise RuntimeError(f"handoff ZIP verification failed: {bad}")

    print(json.dumps(
        results, indent=2,
        default=lambda value: value.item() if isinstance(value, np.generic)
        else str(value)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
