"""PHASE D3 deterministic RUL, six-mode physics, rainflow and Gamma Monte Carlo."""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import platform
import sys
import time
from typing import Any, Mapping
import zipfile

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
for item in (ROOT, ROOT / "src"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from steering_sim.degradation import (
    ComponentDamageState, D1Predictor, MultiModeDegradationState,
    RepeatedMissionRULPredictor, build_cycle_profile, component_mode_rows,
    load_d3_config, load_degradation_config, load_task_spectrum,
    mode_key, monte_carlo_rul, parameters_from_multimode, rainflow_matrix)
from steering_sim.hydraulics_engineering import (EngineeringHydraulicSystem,
                                                  load_parameters)
from steering_sim.hydraulics_lumped import HydraulicInput
from steering_sim.j0_coupling.config import CHANNEL_ORDER, load_j0_config
from steering_sim.j0_coupling.mechanism import (ENGINEERING_STEERING_MODEL,
                                                build_mechanism_model)
from steering_sim.j0_coupling.runner import J0Runner
from steering_sim.quality_assessment import (QualityAssessor,
                                             load_quality_config,
                                             standard_cases)

OUT = ROOT / "outputs" / "degradation" / "phase_D3"
D1_CONFIG = ROOT / "configs" / "degradation" / "d1_degradation_models.json"
D2_CONFIG = ROOT / "configs" / "degradation" / "d2_quality_thresholds.json"
D3_CONFIG = ROOT / "configs" / "degradation" / "d3_rul_models.json"
HEALTHY = ROOT / "configs" / "j1r2" / "engineering_hydraulics.json"
DEFAULT_SPECTRUM = ROOT / "data" / "degradation" / "task_spectrum_30day_example.csv"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def model():
    return build_mechanism_model(
        ENGINEERING_STEERING_MODEL,
        ROOT / "mechanical_model_input_spec_v1.0.yaml",
        ROOT / "mechanics_ackermann_v2" / "config.json",
        ROOT / "mechanics_ackermann_redesigned" / "config.json",
        design_path=ROOT / "configs" / "j1" / "engineering_mechanism.json",
        engineering_config_path=ROOT / "configs" / "j1" / "engineering_config.json")


def runner(parameters, geometry, *, accelerated: bool) -> J0Runner:
    cfg = load_j0_config(ROOT / "configs" / "j0" / "j0_config.json")
    cfg = replace(cfg, engineering_parameters=parameters)
    if accelerated:
        quality = load_quality_config(D2_CONFIG)
        cfg = replace(cfg,
                      dt_hydraulic_s=float(quality.integration["dt_hydraulic_s"]),
                      dt_control_s=float(quality.integration["dt_control_s"]))
    return J0Runner(cfg, geometry, probe_authority=False,
                    mechanical_mode=ENGINEERING_STEERING_MODEL)


def load_initial_state(source: str, d1_predictor: D1Predictor, spectrum
                       ) -> tuple[MultiModeDegradationState, str]:
    if source == "healthy":
        return MultiModeDegradationState.healthy(), "NEW_HEALTHY"
    if source == "d1_day30":
        prediction = d1_predictor.predict(spectrum)
        return MultiModeDegradationState.from_d1(prediction.final_state), "D1_DAY30"
    path = Path(source)
    raw = json.loads(path.read_text(encoding="utf-8"))
    values = dict(MultiModeDegradationState.healthy().modes)
    payload = raw.get("modes", raw)
    for key, value in payload.items():
        if key not in values:
            raise ValueError(f"unknown manual D3 mode: {key}")
        if isinstance(value, Mapping):
            damage = float(value.get("damage", 0.0))
            exposure = float(value.get("exposure", 0.0))
        else:
            damage, exposure = float(value), 0.0
        if not 0.0 <= damage <= 1.0:
            raise ValueError(f"manual damage outside [0,1]: {key}={damage}")
        values[key] = ComponentDamageState(damage, exposure)
    return MultiModeDegradationState(values), f"MANUAL:{path.resolve()}"


def corrected_profile_factory(d1_predictor, healthy, d1_config, d3_config,
                              spectrum):
    """D1 geometry loads plus D3 state-dependent supply/friction corrections."""
    def factory(state: MultiModeDegradationState, initial_angle: float):
        prediction = d1_predictor.predict(
            spectrum, state.to_d1(), initial_outer_angle_deg=initial_angle)
        parameters = parameters_from_multimode(healthy, state, d3_config)
        hydraulic = EngineeringHydraulicSystem(parameters)
        records: list[dict[str, Any]] = []
        pump_cfg = d1_config.component("pump")
        cylinder_cfg = d1_config.component("cylinder")
        for source in prediction.segment_records:
            row = dict(source)
            for supply in ("front", "rear"):
                pressure = float(row[f"pump_{supply}_operating_pressure_pa"])
                old_ratio = min(5.0, max(0.0, float(
                    row[f"pump_{supply}_pump_demand_ratio"])))
                motion = float(row[f"pump_{supply}_motion_flow_m3_s"])
                names = [channel.name for channel in parameters.channels
                         if channel.supply == supply]
                lag = max(parameters.degradation.valve(name).lag_scale
                          for name in names)
                # Slower spool motion stretches the transient rather than
                # fabricating extra steady flow.
                motion /= max(1.0, lag)
                leakage = sum(
                    parameters.degradation.valve(name).internal_leakage_m3_s_per_pa
                    * max(0.0, pressure - parameters.tank_pressure_pa)
                    for name in names)
                demand = motion + leakage
                available = hydraulic.available_pump_flow(supply, pressure)
                new_ratio = demand / available if available > 0.0 else 5.0
                row[f"pump_{supply}_available_pump_flow_m3_s"] = available
                row[f"pump_{supply}_pump_demand_ratio"] = new_ratio
                row[f"pump_{supply}_demand_flow_m3_s"] = demand
                weight = float(pump_cfg["demand_flow_weight"])
                correction = ((1.0 + weight * min(5.0, new_ratio))
                              / max(1.0e-12, 1.0 + weight * old_ratio))
                row[f"equivalent_exposure_pump_{supply}"] = (
                    float(row[f"equivalent_exposure_pump_{supply}"]) * correction)
            for name in CHANNEL_ORDER:
                channel = parameters.channel(name)
                area = 0.5 * (channel.cylinder.area_a_m2
                              + channel.cylinder.area_b_m2)
                scale = parameters.degradation.cylinder(name).friction_scale
                extra_pressure = ((scale - 1.0) * channel.cylinder.coulomb_friction_n
                                  / max(area, 1.0e-12))
                old_pressure = float(row[f"{name}_pressure_diff_pa"])
                new_pressure = old_pressure + extra_pressure
                if old_pressure > 0.0:
                    ratio = (new_pressure / old_pressure) ** float(
                        cylinder_cfg["pressure_exponent"])
                    row[f"equivalent_exposure_cylinder_{name}"] = (
                        float(row[f"equivalent_exposure_cylinder_{name}"]) * ratio)
                row[f"{name}_pressure_diff_pa"] = new_pressure
            records.append(row)
        return build_cycle_profile(records, d3_config)
    return factory


def quality_callback_factory(healthy, d3_config, geometry):
    quality = load_quality_config(D2_CONFIG)
    wanted = set(d3_config.raw["mission"]["quality_case_ids"])
    cases = tuple(case for case in standard_cases() if case.case_id in wanted)
    order = {"HEALTHY": 0, "SUBHEALTHY": 1, "DEGRADED": 2, "DANGEROUS": 3}
    detailed_rows: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []

    def evaluate(state: MultiModeDegradationState, cycle: int) -> Mapping[str, Any]:
        parameters = parameters_from_multimode(healthy, state, d3_config)
        assess = QualityAssessor(runner(parameters, geometry, accelerated=True), quality)
        local: list[dict[str, Any]] = []
        for case in cases:
            result = assess.run(f"cycle_{cycle}", "D3_RUL_CHECKPOINT", case)
            row = dict(result.row)
            row["mission_cycle"] = cycle
            detailed_rows.append(row)
            local.append(row)
            samples = result.dynamic.samples
            traces.append({
                "mission_cycle": cycle, "case_id": case.case_id,
                "time_s": samples["time_s"].tolist(),
                "command_deg": samples["wheel_axle1_right_command_deg"].tolist(),
                "actual_deg": samples["wheel_axle1_right_actual_deg"].tolist(),
                "front_pressure_mpa": samples["supply_pressure_front_mpa_g"].tolist(),
            })
        worst = max((str(row["quality_grade"]) for row in local), key=order.get)
        return {
            "rated_quality_grade": worst,
            "case_count": len(local),
            "maximum_tracking_error_deg": max(float(row["max_tracking_error_deg"])
                                                for row in local),
            "minimum_pump_flow_margin_lpm": min(
                float(row["minimum_pump_flow_margin_lpm"]) for row in local),
            "grade_causes": "|".join(str(row["grade_causes"])
                                      for row in local if row["grade_causes"]),
            "stress_diagnostic_excluded": True,
        }
    return evaluate, detailed_rows, traces


def six_mode_physical_evidence(healthy, config) -> list[dict[str, Any]]:
    base_state = MultiModeDegradationState.healthy()
    base_system = EngineeringHydraulicSystem(
        parameters_from_multimode(healthy, base_state, config))
    state_vector = base_system.neutral_state()
    for index in range(4):
        state_vector[5 * index] = 12.0e6
        state_vector[5 * index + 1] = 3.0e6
        state_vector[5 * index + 3] = 0.02
        state_vector[5 * index + 4] = 0.2
    inputs = HydraulicInput((0.8,) * 4, (157.08,) * 4,
                            (5000.0,) * 4)
    base_derivative, base_output = base_system.evaluate(0.0, state_vector, inputs)
    targets = (
        ("pump", "front", "leakage_wear"),
        ("pump", "front", "mechanical_loss"),
        ("valve", "channel_front", "leakage_wear"),
        ("valve", "channel_front", "response_lag"),
        ("cylinder", "channel_front", "leakage_wear"),
        ("cylinder", "channel_front", "friction_growth"),
    )
    rows = []
    for kind, component, mode_name in targets:
        key = mode_key(kind, component, mode_name)
        worn = base_state.with_mode(key, ComponentDamageState(0.8))
        parameters = parameters_from_multimode(healthy, worn, config)
        system = EngineeringHydraulicSystem(parameters)
        derivative, output = system.evaluate(0.0, state_vector, inputs)
        index = 0
        row = {
            "mode": key, "injected_damage": 0.8,
            "rhs_delta_norm": float(np.linalg.norm(derivative - base_derivative)),
            "front_pump_flow_delta_m3_s": (output.pump_flow_m3_s[0]
                                             - base_output.pump_flow_m3_s[0]),
            "front_pump_input_power_delta_w": (output.pump_input_power_w[0]
                                                 - base_output.pump_input_power_w[0]),
            "front_valve_leakage_delta_m3_s": (
                output.channels[index].valve_leakage_flow_m3_s
                - base_output.channels[index].valve_leakage_flow_m3_s),
            "front_cylinder_leakage_delta_m3_s": (
                output.channels[index].cylinder_leakage_flow_m3_s
                - base_output.channels[index].cylinder_leakage_flow_m3_s),
            "front_valve_state_derivative_delta_per_s": (
                derivative[4] - base_derivative[4]),
            "front_acceleration_delta_m_s2": derivative[3] - base_derivative[3],
        }
        rows.append(row)
    return rows


def write_plots(history: pd.DataFrame, quality: pd.DataFrame,
                traces: list[dict[str, Any]], mc_samples: pd.DataFrame,
                paths: pd.DataFrame) -> None:
    fig, axes = plt.subplots(3, 1, figsize=(10, 9), sharex=True)
    for kind in ("pump", "valve", "cylinder"):
        columns = [name for name in history if name.startswith(f"{kind}_")]
        if columns:
            axes[0].plot(history["mission_cycle"], history[columns].max(axis=1),
                         label=f"maximum {kind} mode damage")
    axes[0].set_ylabel("damage (-)")
    axes[0].legend(fontsize=7)
    if not quality.empty:
        axes[1].plot(quality["mission_cycle"], quality["maximum_tracking_error_deg"],
                     marker="o", label="maximum tracking error (deg)")
        axes[1].set_ylabel("tracking error (deg)")
        grade_value = quality["rated_quality_grade"].map(
            {"HEALTHY": 0, "SUBHEALTHY": 1, "DEGRADED": 2, "DANGEROUS": 3})
        axes[2].step(quality["mission_cycle"], grade_value, where="post")
        axes[2].set_yticks((0, 1, 2, 3),
                           ("HEALTHY", "SUBHEALTHY", "DEGRADED", "DANGEROUS"))
    axes[2].set_ylabel("D2 rated grade")
    for axis in axes:
        axis.grid(True, alpha=0.3)
    axes[-1].set_xlabel("30-day mission cycle")
    fig.tight_layout()
    fig.savefig(OUT / "quality_vs_mission_cycles.png", dpi=180)
    plt.close(fig)

    if traces:
        first_cycle = min(item["mission_cycle"] for item in traces)
        last_cycle = max(item["mission_cycle"] for item in traces)
        selected = [item for item in traces
                    if item["mission_cycle"] in (first_cycle, last_cycle)
                    and item["case_id"] == "STD_L30"]
        fig, axes = plt.subplots(2, 1, figsize=(9, 7), sharex=True)
        for item in selected:
            label = f"cycle {item['mission_cycle']}"
            axes[0].plot(item["time_s"], item["actual_deg"], label=label)
            axes[0].plot(item["time_s"], item["command_deg"], "--", alpha=0.5)
            axes[1].plot(item["time_s"], item["front_pressure_mpa"], label=label)
        axes[0].set_ylabel("axle-1 right angle (deg)")
        axes[1].set_ylabel("front supply pressure (MPa)")
        axes[1].set_xlabel("time (s)")
        for axis in axes:
            axis.grid(True, alpha=0.3)
            axis.legend()
        fig.tight_layout()
        fig.savefig(OUT / "healthy_vs_eol_dynamics.png", dpi=180)
        plt.close(fig)

    observed = pd.to_numeric(mc_samples["failure_cycle"], errors="coerce").dropna()
    fig, ax = plt.subplots(figsize=(8, 4.5))
    if not observed.empty:
        ax.hist(observed, bins=min(20, max(5, observed.nunique())), alpha=0.8)
    ax.set(xlabel="first failure mission cycle", ylabel="stochastic paths")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT / "rul_distribution.png", dpi=180)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 5))
    for sample, group in paths.groupby("sample_id"):
        ax.plot(group["mission_cycle"], group["maximum_damage"], alpha=0.65,
                label=f"path {sample}")
    ax.set(xlabel="30-day mission cycle", ylabel="maximum mode damage")
    ax.grid(True, alpha=0.3)
    if paths["sample_id"].nunique() <= 12:
        ax.legend(fontsize=7, ncol=2)
    fig.tight_layout()
    fig.savefig(OUT / "stochastic_degradation_paths.png", dpi=180)
    plt.close(fig)


def package_delivery() -> Path:
    target = ROOT / "handoff_to_chatgpt" / "phase_D3.zip"
    files = [
        D1_CONFIG, D2_CONFIG, D3_CONFIG, DEFAULT_SPECTRUM,
        ROOT / "docs" / "degradation" / "phase_D3_report.md",
        ROOT / "scripts" / "d3" / "run_phase_d3.py",
        ROOT / "src" / "steering_sim" / "hydraulics_engineering" / "parameters.py",
        ROOT / "src" / "steering_sim" / "hydraulics_engineering" / "model.py",
        ROOT / "src" / "steering_sim" / "quality_assessment" / "assessment.py",
    ]
    files.extend((ROOT / "src" / "steering_sim" / "degradation").glob("*.py"))
    files.extend((ROOT / "tests" / "degradation").glob("test_d3*.py"))
    files.extend(path for path in OUT.rglob("*") if path.is_file())
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(set(files)):
            if path.exists():
                archive.write(path, path.relative_to(ROOT))
    return target


def run(spectrum_path: Path, initial_source: str, *, sample_count: int | None,
        maximum_cycles: int | None, package: bool) -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    hashes_before = {str(path.relative_to(ROOT)): sha256(path)
                     for path in (HEALTHY, D1_CONFIG, D2_CONFIG, D3_CONFIG, spectrum_path)}
    spectrum = load_task_spectrum(spectrum_path, expected_days=30.0)
    d1_config = load_degradation_config(D1_CONFIG)
    d3_config = load_d3_config(D3_CONFIG)
    healthy = load_parameters(HEALTHY)
    geometry = model()
    base_runner = runner(healthy, geometry, accelerated=False)
    d1_predictor = D1Predictor(base_runner, d1_config)
    initial_state, initial_label = load_initial_state(
        initial_source, d1_predictor, spectrum)
    profile_factory = corrected_profile_factory(
        d1_predictor, healthy, d1_config, d3_config, spectrum)
    quality_evaluator, detailed_quality, traces = quality_callback_factory(
        healthy, d3_config, geometry)

    deterministic_started = time.perf_counter()
    prediction = RepeatedMissionRULPredictor(d3_config, profile_factory).predict(
        initial_state, quality_evaluator=quality_evaluator,
        maximum_cycles=maximum_cycles)
    deterministic_runtime = time.perf_counter() - deterministic_started
    profile = profile_factory(initial_state, 0.0)

    stochastic_started = time.perf_counter()
    monte_carlo = monte_carlo_rul(
        initial_state, profile, d3_config, sample_count=sample_count,
        maximum_cycles=maximum_cycles)
    stochastic_runtime = time.perf_counter() - stochastic_started

    summary = {
        "prediction_status": prediction.status,
        "remaining_complete_30day_cycles": prediction.remaining_complete_cycles,
        "first_failure_cycle": prediction.first_failure_cycle,
        "first_failure_day_in_cycle": prediction.first_failure_day_in_cycle,
        "first_failure_segment_id": prediction.first_failure_segment_id,
        "remaining_time_days": prediction.remaining_time_days,
        "limiting_factors": list(prediction.limiting_factors),
        "failure_reasons": list(prediction.failure_reasons),
        "termination_basis": prediction.termination_basis,
        "initial_state": initial_label,
        "prior_complete_30day_cycles_from_new": (
            1 if initial_label == "D1_DAY30" else 0 if initial_label == "NEW_HEALTHY" else None),
        "total_complete_30day_cycles_from_new": (
            (prediction.remaining_complete_cycles + 1)
            if initial_label == "D1_DAY30"
            and prediction.remaining_complete_cycles is not None else
            prediction.remaining_complete_cycles if initial_label == "NEW_HEALTHY" else None),
        "mission_days": spectrum.total_days,
        "hydraulic_model": "ENGINEERING_HYDRAULIC_V1",
        "mechanical_model": "ENGINEERING_STEERING_MODEL",
        "model_version": d3_config.model_version,
        "assumption_tag": d3_config.assumption_tag,
        "calibration_status": "PENDING_CLIENT_CALIBRATION",
        "spectrum_sha256": sha256(spectrum_path),
        "d3_config_sha256": sha256(D3_CONFIG),
        "quality_thresholds_sha256": sha256(D2_CONFIG),
        "random_seed": monte_carlo.random_seed,
        "prediction_method": "ordered analytic six-mode advance + state refresh + sparse 22-state D2 checks",
        "deterministic_runtime_s": deterministic_runtime,
        "monte_carlo_runtime_s": stochastic_runtime,
        "total_runtime_s": time.perf_counter() - started,
    }
    (OUT / "rul_prediction_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame([summary | {
        "limiting_factors": "|".join(prediction.limiting_factors),
        "failure_reasons": "|".join(prediction.failure_reasons)}]).to_csv(
            OUT / "rul_prediction_summary.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(prediction.cycle_history).to_csv(
        OUT / "mission_cycle_history.csv", index=False, encoding="utf-8-sig")
    failure = summary | {"verified_quality_checkpoints": list(prediction.quality_history)}
    (OUT / "first_failure_details.json").write_text(
        json.dumps(failure, ensure_ascii=False, indent=2), encoding="utf-8")

    final_parameters = parameters_from_multimode(healthy, prediction.final_state, d3_config)
    modes = pd.DataFrame(component_mode_rows(
        prediction.final_state, d3_config, final_parameters))
    modes.to_csv(OUT / "component_degradation_modes.csv", index=False,
                 encoding="utf-8-sig")
    trajectories = []
    for cycle, state in enumerate(prediction.state_history):
        params = parameters_from_multimode(healthy, state, d3_config)
        for row in component_mode_rows(state, d3_config, params):
            trajectories.append({"mission_cycle": cycle, **row})
    pd.DataFrame(trajectories).to_csv(
        OUT / "component_parameter_trajectories.csv", index=False,
        encoding="utf-8-sig")
    thresholds = {
        "distinction": "D3 hard failure limits; not D2 health-grade boundaries",
        "assumption_tag": d3_config.assumption_tag,
        "calibration_status": "PENDING_CLIENT_CALIBRATION",
        "modes": d3_config.raw["modes"],
        "mission_rules": d3_config.raw["mission"],
    }
    (OUT / "component_failure_thresholds.json").write_text(
        json.dumps(thresholds, ensure_ascii=False, indent=2), encoding="utf-8")

    pd.DataFrame(prediction.quality_history).to_csv(
        OUT / "quality_over_mission_cycles.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(detailed_quality).to_csv(
        OUT / "quality_checkpoint_case_details.csv", index=False, encoding="utf-8-sig")

    cycle_rows, matrix_rows, equivalent_rows = [], [], []
    for name, cycles in profile.rainflow_cycles.items():
        for item in cycles:
            cycle_rows.append({"component_id": name, "load": "signed_cylinder_force_n",
                               "range_n": item.range_value,
                               "amplitude_n": item.amplitude,
                               "mean_n": item.mean_value, "cycle_count": item.count,
                               "start_record_index": item.start_index,
                               "end_record_index": item.end_index})
        matrix_rows.extend({"component_id": name, **row}
                           for row in rainflow_matrix(cycles))
        equivalent_rows.append({"component_id": name,
                                "load": "signed_cylinder_force_n",
                                **profile.rainflow_equivalents[name],
                                "used_by_mode": "cylinder.friction_growth"})
    pd.DataFrame(cycle_rows).to_csv(OUT / "rainflow_cycle_count.csv", index=False,
                                    encoding="utf-8-sig")
    pd.DataFrame(matrix_rows).to_csv(OUT / "rainflow_matrix.csv", index=False,
                                     encoding="utf-8-sig")
    pd.DataFrame(equivalent_rows).to_csv(
        OUT / "equivalent_cycle_loads.csv", index=False, encoding="utf-8-sig")

    samples = pd.DataFrame(monte_carlo.sample_rows)
    samples.to_csv(OUT / "monte_carlo_rul_samples.csv", index=False,
                   encoding="utf-8-sig")
    mc_summary_rows = ([{"metric": key, "value": value,
                         "interpretation": "stochastic path lifetime quantile"}
                        for key, value in monte_carlo.quantiles.items()]
                       + [{"metric": "sample_count", "value": monte_carlo.sample_count},
                          {"metric": "right_censored_count", "value": monte_carlo.censored_count},
                          {"metric": "right_censored_fraction", "value": monte_carlo.censored_fraction},
                          {"metric": "random_seed", "value": monte_carlo.random_seed}]
                       + [{"metric": f"limiter_count:{key}", "value": value}
                          for key, value in monte_carlo.limiting_factor_counts.items()])
    pd.DataFrame(mc_summary_rows).to_csv(
        OUT / "monte_carlo_rul_summary.csv", index=False, encoding="utf-8-sig")
    paths = pd.DataFrame(monte_carlo.path_rows)
    paths.to_csv(OUT / "stochastic_degradation_paths.csv", index=False,
                 encoding="utf-8-sig")
    pd.DataFrame(six_mode_physical_evidence(healthy, d3_config)).to_csv(
        OUT / "six_mode_physical_injection.csv", index=False, encoding="utf-8-sig")

    history = pd.DataFrame(prediction.cycle_history)
    quality_frame = pd.DataFrame(prediction.quality_history)
    write_plots(history, quality_frame, traces, samples, paths)
    hashes_after = {str(path.relative_to(ROOT)): sha256(path)
                    for path in (HEALTHY, D1_CONFIG, D2_CONFIG, D3_CONFIG, spectrum_path)}
    reproducibility = {
        "input_hashes_before": hashes_before,
        "input_hashes_after": hashes_after,
        "healthy_baseline_unchanged": hashes_before[str(HEALTHY.relative_to(ROOT))]
                                      == hashes_after[str(HEALTHY.relative_to(ROOT))],
        "python": sys.executable, "python_version": sys.version,
        "platform": platform.platform(), "processor": platform.processor(),
        "logical_cpu_count": __import__("os").cpu_count(),
        "deterministic_runtime_s": deterministic_runtime,
        "monte_carlo_runtime_s": stochastic_runtime,
        "total_runtime_s": time.perf_counter() - started,
        "dynamic_case_count": len(detailed_quality),
        "random_seed": monte_carlo.random_seed,
        "command": (f"{sys.executable} scripts/d3/run_phase_d3.py "
                    f"--spectrum {spectrum_path} --initial-state {initial_source}"),
    }
    (OUT / "reproducibility_and_performance.json").write_text(
        json.dumps(reproducibility, ensure_ascii=False, indent=2), encoding="utf-8")
    if package:
        summary["delivery_zip"] = str(package_delivery())
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spectrum", type=Path, default=DEFAULT_SPECTRUM)
    parser.add_argument("--initial-state", default="d1_day30",
                        help="healthy, d1_day30, or a D3 mode-state JSON path")
    parser.add_argument("--samples", type=int)
    parser.add_argument("--maximum-cycles", type=int)
    parser.add_argument("--package", action="store_true")
    args = parser.parse_args()
    result = run(args.spectrum.resolve(), args.initial_state,
                 sample_count=args.samples, maximum_cycles=args.maximum_cycles,
                 package=args.package)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
