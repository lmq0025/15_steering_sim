"""Run PHASE D2 natural-aging checkpoints and specified sensitivity cases."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import time
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT, ROOT / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from steering_sim.degradation import (ComponentDamageState, D1Predictor,
                                      DegradationState, checkpoint_states,
                                      load_degradation_config,
                                      load_task_spectrum)
from steering_sim.degradation.spectrum import TaskSegment, TaskSpectrum
from steering_sim.degradation.prediction import (component_parameter_rows,
                                                  parameters_from_damage)
from steering_sim.hydraulics_engineering import (
    CylinderDegradationParameters, load_parameters,
    with_component_degradation)
from steering_sim.j0_coupling.config import CHANNEL_ORDER, load_j0_config
from steering_sim.j0_coupling.mechanism import (ENGINEERING_STEERING_MODEL,
                                                build_mechanism_model)
from steering_sim.j0_coupling.runner import J0Runner
from steering_sim.quality_assessment import (AssessmentCase, QualityAssessor,
                                             component_health_rows,
                                             load_quality_config,
                                             standard_cases)
from steering_sim.quality_assessment.assessment import reversal_profile

OUT = ROOT / "outputs" / "degradation" / "phase_D2"
D1_CONFIG = ROOT / "configs" / "degradation" / "d1_degradation_models.json"
D2_CONFIG = ROOT / "configs" / "degradation" / "d2_quality_thresholds.json"
HEALTHY = ROOT / "configs" / "j1r2" / "engineering_hydraulics.json"
SPECTRUM = ROOT / "data" / "degradation" / "task_spectrum_30day_example.csv"


def _model():
    return build_mechanism_model(
        ENGINEERING_STEERING_MODEL,
        ROOT / "mechanical_model_input_spec_v1.0.yaml",
        ROOT / "mechanics_ackermann_v2" / "config.json",
        ROOT / "mechanics_ackermann_redesigned" / "config.json",
        design_path=ROOT / "configs" / "j1" / "engineering_mechanism.json",
        engineering_config_path=ROOT / "configs" / "j1" / "engineering_config.json")


def build_runner(parameters=None, *, accelerated: bool = False) -> J0Runner:
    config = load_j0_config(ROOT / "configs" / "j0" / "j0_config.json")
    if parameters is not None:
        config = replace(config, engineering_parameters=parameters)
    if accelerated:
        quality = load_quality_config(D2_CONFIG)
        dt_h = float(quality.integration["dt_hydraulic_s"])
        dt_c = float(quality.integration["dt_control_s"])
        config = replace(config, dt_hydraulic_s=dt_h, dt_control_s=dt_c)
    return J0Runner(config, _model(), probe_authority=False,
                    mechanical_mode=ENGINEERING_STEERING_MODEL)


def _state_payload(state: DegradationState) -> dict[str, dict[str, float]]:
    return {
        "pumps": {name: item.damage for name, item in state.pumps.items()},
        "valves": {name: item.damage for name, item in state.valves.items()},
        "cylinders": {name: item.damage for name, item in state.cylinders.items()},
    }


def _state_from_payload(payload: dict[str, dict[str, float]]) -> DegradationState:
    return DegradationState(**{
        kind: {name: ComponentDamageState(damage=float(value))
               for name, value in items.items()}
        for kind, items in payload.items()})


def _case_payload(case: AssessmentCase) -> dict[str, Any]:
    return {
        "case_id": case.case_id, "target_outer_angle_deg": case.target_outer_angle_deg,
        "speed_kmh": case.speed_kmh, "duration_s": case.duration_s,
        "reference_time_s": case.reference_time_s, "category": case.category,
        "reversal": case.profile_factory is not None,
    }


def _case_from_payload(payload: dict[str, Any]) -> AssessmentCase:
    return AssessmentCase(
        case_id=str(payload["case_id"]),
        target_outer_angle_deg=float(payload["target_outer_angle_deg"]),
        speed_kmh=float(payload["speed_kmh"]),
        duration_s=float(payload["duration_s"]),
        reference_time_s=float(payload["reference_time_s"]),
        category=str(payload["category"]),
        profile_factory=reversal_profile if payload.get("reversal") else None)


def _assessment_worker(jobs: list[dict[str, Any]]) -> dict[str, Any]:
    """One process builds geometry once, then evaluates its assigned states."""
    quality = load_quality_config(D2_CONFIG)
    degradation = load_degradation_config(D1_CONFIG)
    healthy = load_parameters(HEALTHY)
    geometry = _model()
    base = load_j0_config(ROOT / "configs" / "j0" / "j0_config.json")
    base = replace(
        base, dt_hydraulic_s=float(quality.integration["dt_hydraulic_s"]),
        dt_control_s=float(quality.integration["dt_control_s"]))
    rows: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []
    for job in jobs:
        state = _state_from_payload(job["state"])
        parameters = parameters_from_damage(healthy, state, degradation)
        if (job["source"] == "SPECIFIED_DEGRADATION_SENSITIVITY"
                and job["metadata"]["scenario_mode"] in
                ("single_cylinder", "combined")):
            cylinders = dict(parameters.degradation.cylinders)
            limit = float(quality.raw["sensitivity_physical_limits"][
                "cylinder_internal_leakage_m3_s_per_pa"])
            cylinders["channel_rear_2"] = CylinderDegradationParameters(
                internal_leakage_m3_s_per_pa=(
                    limit * state.cylinders["channel_rear_2"].damage))
            parameters = with_component_degradation(
                parameters, cylinders=cylinders)
        config = replace(base, engineering_parameters=parameters)
        runner = J0Runner(config, geometry, probe_authority=False,
                          mechanical_mode=ENGINEERING_STEERING_MODEL)
        assessor = QualityAssessor(runner, quality)
        for case_data in job["cases"]:
            case = _case_from_payload(case_data)
            assessed = assessor.run(job["state_label"], job["source"], case)
            row = dict(assessed.row)
            row.update(job["metadata"])
            rows.append(row)
            if job.get("save_trace"):
                wanted = [
                    "time_s", "wheel_axle1_right_command_deg",
                    "wheel_axle1_right_actual_deg", "channel_front_x_ref_eff_m",
                    "channel_front_x_m", "supply_pressure_front_mpa_g",
                    "supply_pressure_rear_mpa_g", "channel_front_valve_command"]
                trace = {name: assessed.dynamic.samples[name].tolist()
                         for name in wanted if name in assessed.dynamic.samples}
                traces.append({"state_label": job["state_label"],
                               "case_id": case.case_id, "samples": trace})
    return {"rows": rows, "traces": traces}


def _set_damage(state: DegradationState, mode: str, level: float) -> DegradationState:
    pumps = dict(state.pumps)
    valves = dict(state.valves)
    cylinders = dict(state.cylinders)
    if mode in ("front_pump", "combined"):
        pumps["front"] = ComponentDamageState(level)
    if mode in ("rear_pump", "combined"):
        pumps["rear"] = ComponentDamageState(level)
    if mode in ("single_valve", "combined"):
        valves["channel_rear_1"] = ComponentDamageState(level)
    if mode in ("single_cylinder", "combined"):
        cylinders["channel_rear_2"] = ComponentDamageState(level)
    return DegradationState(pumps=pumps, valves=valves, cylinders=cylinders)


def _worst_grade(values: pd.Series) -> str:
    order = {"HEALTHY": 0, "SUBHEALTHY": 1, "DEGRADED": 2, "DANGEROUS": 3}
    return max(values, key=lambda value: order[str(value)])


def _write_d1_feedback_evidence(degradation) -> None:
    """Export the two D1 load/state feedback checks requested by D2."""
    rows: list[dict[str, Any]] = []
    healthy_state = DegradationState.healthy(CHANNEL_ORDER)
    pumps = dict(healthy_state.pumps)
    pumps["front"] = ComponentDamageState(0.8)
    worn_state = replace(healthy_state, pumps=pumps)
    runner = build_runner()
    for label, angle, state in (
            ("straight_healthy", 0.0, healthy_state),
            ("loaded_healthy", 30.0, healthy_state),
            ("loaded_front_pump_damage_0p8", 30.0, worn_state)):
        segment = TaskSegment(
            segment_id=label, speed_kmh=5.0,
            target_outer_angle_deg=angle, segment_duration_s=60.0,
            friction_coefficient=0.8, axle_mass_t=(11.5,) * 6,
            pump_running=True)
        prediction = D1Predictor(runner, degradation).predict(
            TaskSpectrum((segment,), source=Path("D2_SYNTHETIC_EVIDENCE")), state)
        record = prediction.segment_records[0]
        rows.append({
            "case": label,
            "runtime_s": 60.0,
            "target_outer_angle_deg": angle,
            "initial_front_pump_damage": state.pumps["front"].damage,
            "front_load_pressure_pa": record["pump_front_load_pressure_pa"],
            "front_motion_flow_m3_s": record["pump_front_motion_flow_m3_s"],
            "front_available_pump_flow_m3_s": record[
                "pump_front_available_pump_flow_m3_s"],
            "front_pump_demand_ratio": record["pump_front_pump_demand_ratio"],
            "front_equivalent_exposure": record[
                "equivalent_exposure_pump_front"],
            "front_damage_increment": record["damage_increment_pump_front"],
        })
    pd.DataFrame(rows).to_csv(
        OUT / "d1_load_feedback_validation.csv", index=False,
        encoding="utf-8-sig")


def _plots(summary: pd.DataFrame, sensitivity: pd.DataFrame,
           traces: list[dict[str, Any]]) -> None:
    natural = summary[summary["scenario_source"] == "D1_NATURAL_30DAY"]
    natural = natural[natural["case_category"] != "stress_diagnostic"]
    timeline = natural.groupby("checkpoint_day", as_index=False).agg(
        max_tracking_error_deg=("max_tracking_error_deg", "max"),
        minimum_pump_flow_margin_lpm=("minimum_pump_flow_margin_lpm", "min"))
    fig, left = plt.subplots(figsize=(8, 4.5))
    left.plot(timeline["checkpoint_day"], timeline["max_tracking_error_deg"],
              marker="o", label="max wheel tracking error")
    left.set(xlabel="mission day", ylabel="tracking error (deg)")
    right = left.twinx()
    right.plot(timeline["checkpoint_day"], timeline["minimum_pump_flow_margin_lpm"],
               marker="s", color="tab:orange", label="minimum pump margin")
    right.set_ylabel("pump flow margin (L/min)")
    left.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT / "system_quality_timeline.png", dpi=180)
    plt.close(fig)

    heavy = sensitivity[sensitivity["severity"] == "heavy"]
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.bar(heavy["scenario_mode"], heavy["max_tracking_error_deg"],
           color="tab:red", alpha=0.75)
    ax.set(ylabel="max wheel tracking error (deg)", xlabel="specified degradation mode")
    ax.tick_params(axis="x", rotation=25)
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT / "degradation_sensitivity.png", dpi=180)
    plt.close(fig)

    chosen = [item for item in traces if item["state_label"] in
              {"combined_healthy", "combined_heavy"}]
    fig, axes = plt.subplots(2, 1, figsize=(9, 7), sharex=True)
    for item in chosen:
        sample = item["samples"]
        label = item["state_label"]
        axes[0].plot(sample["time_s"], sample["wheel_axle1_right_actual_deg"],
                     label=f"{label} actual")
        axes[0].plot(sample["time_s"], sample["wheel_axle1_right_command_deg"],
                     linestyle="--", alpha=0.65, label=f"{label} command")
        axes[1].plot(sample["time_s"], sample["supply_pressure_front_mpa_g"],
                     label=label)
    axes[0].set_ylabel("axle1 right angle (deg)")
    axes[1].set(xlabel="time (s)", ylabel="front supply pressure (MPa g)")
    for ax in axes:
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / "healthy_vs_degraded_dynamics.png", dpi=180)
    plt.close(fig)


def run(worker_count: int | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    OUT.mkdir(parents=True, exist_ok=True)
    quality = load_quality_config(D2_CONFIG)
    degradation = load_degradation_config(D1_CONFIG)
    healthy = load_parameters(HEALTHY)

    d1_started = time.perf_counter()
    spectrum = load_task_spectrum(SPECTRUM, expected_days=30)
    d1_prediction = D1Predictor(build_runner(), degradation).predict(spectrum)
    checkpoints = checkpoint_states(d1_prediction)
    d1_runtime = time.perf_counter() - d1_started
    _write_d1_feedback_evidence(degradation)

    jobs: list[dict[str, Any]] = []
    state_lookup: dict[str, DegradationState] = {}
    cases = [_case_payload(case) for case in standard_cases()]
    for day, state in checkpoints.items():
        label = f"natural_day_{int(day)}"
        state_lookup[label] = state
        jobs.append({"state_label": label, "source": "D1_NATURAL_30DAY",
                     "state": _state_payload(state), "cases": cases,
                     "metadata": {"checkpoint_day": day,
                                  "scenario_mode": "natural",
                                  "severity": "natural"},
                     "save_trace": False})

    levels = quality.raw["sensitivity_damage_levels"]
    for mode in ("front_pump", "rear_pump", "single_valve",
                 "single_cylinder", "combined"):
        if mode in ("single_valve", "single_cylinder", "combined"):
            sens_case = _case_payload(AssessmentCase(
                "SENS_L30", 30.0, 0.0, 3.50, 2.50,
                category="specified_sensitivity"))
        else:
            sens_case = _case_payload(AssessmentCase(
                "SENS_L10", 10.0, 5.0, 1.25, 0.8333333333,
                category="specified_sensitivity"))
        for severity, level in levels.items():
            state = _set_damage(DegradationState.healthy(CHANNEL_ORDER),
                                mode, float(level))
            label = f"{mode}_{severity}"
            state_lookup[label] = state
            jobs.append({"state_label": label,
                         "source": "SPECIFIED_DEGRADATION_SENSITIVITY",
                         "state": _state_payload(state), "cases": [sens_case],
                         "metadata": {"checkpoint_day": -1,
                                      "scenario_mode": mode,
                                      "severity": severity},
                         "save_trace": mode == "combined" and severity in
                                       ("healthy", "heavy")})

    count = worker_count or int(quality.integration["worker_count"])
    count = max(1, min(count, os.cpu_count() or 1, len(jobs)))
    bundles = [[] for _ in range(count)]
    natural_jobs = [job for job in jobs if job["source"] == "D1_NATURAL_30DAY"]
    sensitivity_jobs = [job for job in jobs if job["source"] != "D1_NATURAL_30DAY"]
    for index, job in enumerate(natural_jobs):
        bundles[index % count].append(job)
    for index, job in enumerate(sensitivity_jobs):
        bundles[index % count].append(job)

    dynamic_started = time.perf_counter()
    if count == 1:
        worker_results = [_assessment_worker(bundles[0])]
    else:
        with ProcessPoolExecutor(max_workers=count) as pool:
            worker_results = list(pool.map(_assessment_worker, bundles))
    dynamic_runtime = time.perf_counter() - dynamic_started
    rows = [row for result in worker_results for row in result["rows"]]
    traces = [trace for result in worker_results for trace in result["traces"]]
    summary = pd.DataFrame(rows).sort_values(
        ["scenario_source", "state_label", "case_id"])
    summary.to_csv(OUT / "quality_assessment_summary.csv", index=False,
                   encoding="utf-8-sig")

    component_rows: list[dict[str, Any]] = []
    parameter_rows: list[dict[str, Any]] = []
    for label, state in state_lookup.items():
        source = ("D1_NATURAL_30DAY" if label.startswith("natural")
                  else "SPECIFIED_DEGRADATION_SENSITIVITY")
        component_rows.extend(component_health_rows(label, source, state, quality))
        parameters = parameters_from_damage(healthy, state, degradation)
        if source == "SPECIFIED_DEGRADATION_SENSITIVITY" and (
                label.startswith("single_cylinder_") or label.startswith("combined_")):
            cylinders = dict(parameters.degradation.cylinders)
            limit = float(quality.raw["sensitivity_physical_limits"][
                "cylinder_internal_leakage_m3_s_per_pa"])
            cylinders["channel_rear_2"] = CylinderDegradationParameters(
                internal_leakage_m3_s_per_pa=(
                    limit * state.cylinders["channel_rear_2"].damage))
            parameters = with_component_degradation(parameters, cylinders=cylinders)
        for row in component_parameter_rows(
                parameters, state, degradation):
            if (source == "SPECIFIED_DEGRADATION_SENSITIVITY"
                    and (label.startswith("single_cylinder_")
                         or label.startswith("combined_"))
                    and row["component_type"] == "hydraulic_cylinder"
                    and row["component_id"] == "channel_rear_2"):
                row["source"] = quality.assumption_tag
                row["model_version"] = quality.model_version
            parameter_rows.append({"state_label": label, "scenario_source": source,
                                   **row})
    pd.DataFrame(component_rows).to_csv(
        OUT / "component_health_status.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(parameter_rows).to_csv(
        OUT / "component_parameters.csv", index=False, encoding="utf-8-sig")

    natural_all = summary[summary["scenario_source"] == "D1_NATURAL_30DAY"]
    natural = natural_all[natural_all["case_category"] != "stress_diagnostic"]
    numeric_metrics = list(quality.thresholds)
    aggregate = {name: (name, "min" if quality.thresholds[name]["direction"] == "min"
                         else "max") for name in numeric_metrics}
    timeline = natural.groupby("checkpoint_day", as_index=False).agg(
        quality_grade=("quality_grade", _worst_grade),
        grade_causes=("grade_causes", lambda values: "|".join(
            sorted({item for value in values for item in str(value).split("|") if item}))),
        **aggregate)
    stress = natural_all[natural_all["case_category"] == "stress_diagnostic"]
    stress_grade = stress.groupby("checkpoint_day", as_index=False).agg(
        stress_diagnostic_grade=("quality_grade", _worst_grade),
        stress_diagnostic_causes=("grade_causes", lambda values: "|".join(
            sorted({item for value in values for item in str(value).split("|") if item}))))
    timeline = timeline.merge(stress_grade, on="checkpoint_day", how="left")
    baseline = timeline[timeline["checkpoint_day"] == 0].iloc[0]
    for name in numeric_metrics:
        timeline[f"change_vs_day0_{name}"] = timeline[name] - baseline[name]
    timeline.to_csv(OUT / "system_quality_timeline.csv", index=False,
                    encoding="utf-8-sig")

    sensitivity = summary[
        summary["scenario_source"] == "SPECIFIED_DEGRADATION_SENSITIVITY"].copy()
    for mode in sensitivity["scenario_mode"].unique():
        mask = sensitivity["scenario_mode"] == mode
        base = sensitivity[mask & (sensitivity["severity"] == "healthy")].iloc[0]
        for name in numeric_metrics:
            sensitivity.loc[mask, f"change_vs_healthy_{name}"] = (
                sensitivity.loc[mask, name] - base[name])
    sensitivity.to_csv(OUT / "degradation_sensitivity.csv", index=False,
                       encoding="utf-8-sig")

    comparison = pd.concat((
        natural[natural["checkpoint_day"].isin((0.0, 30.0))], sensitivity),
        ignore_index=True)
    comparison.to_csv(OUT / "healthy_vs_degraded_performance.csv", index=False,
                      encoding="utf-8-sig")
    shutil.copyfile(D2_CONFIG, OUT / "assessment_thresholds.json")
    _plots(summary, sensitivity, traces)

    total_runtime = time.perf_counter() - started
    acceptance_runtime = d1_runtime + dynamic_runtime
    runtime = {
        "d1_prediction_s": d1_runtime,
        "quality_dynamic_s": dynamic_runtime,
        "total_s": total_runtime,
        "default_spectrum_plus_quality_s": acceptance_runtime,
        "default_under_60_s": acceptance_runtime < 60.0,
        "dynamic_case_count": len(summary),
        "natural_dynamic_case_count": len(natural_all),
        "rated_natural_dynamic_case_count": len(natural),
        "sensitivity_dynamic_case_count": len(sensitivity),
        "worker_count": count,
        "dt_hydraulic_s": float(quality.integration["dt_hydraulic_s"]),
        "cpu": platform.processor() or platform.machine(),
        "logical_cpu_count": os.cpu_count(),
        "platform": platform.platform(),
        "all_dynamic_completed": bool(summary["completed"].all()),
    }
    (OUT / "runtime_performance.json").write_text(
        json.dumps(runtime, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "REPRODUCE.md").write_text(
        "# PHASE D2 reproduction\n\n"
        "```powershell\n"
        "E:\\ProgramData\\condaData\\envs_dirs\\steering_sim\\python.exe "
        "scripts\\d2\\run_phase_d2.py\n"
        "E:\\ProgramData\\condaData\\envs_dirs\\steering_sim\\python.exe "
        "-m pytest tests\\quality_assessment tests\\degradation -q\n"
        "```\n\nD2 stops before RUL/Gamma Monte Carlo and does not modify the GUI.\n",
        encoding="utf-8")
    print(json.dumps(runtime, ensure_ascii=False, indent=2))
    return runtime


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=None)
    args = parser.parse_args()
    run(args.workers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
