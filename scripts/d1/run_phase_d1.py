"""生成 PHASE D1 模板、30 天示例、预测结果、物理回写证据和图。"""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import time
import zipfile

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from steering_sim.degradation.damage import load_degradation_config
from steering_sim.degradation.prediction import (
    D1Predictor, component_parameter_rows)
from steering_sim.degradation.spectrum import (OPTIONAL_COLUMNS, REQUIRED_COLUMNS,
                                                load_task_spectrum)
from steering_sim.hydraulics_engineering import (
    CylinderDegradationParameters, EngineeringHydraulicSystem,
    PumpDegradationParameters, ValveDegradationParameters,
    load_parameters, with_component_degradation)
from steering_sim.hydraulics_lumped import HydraulicInput
from steering_sim.j0_coupling.config import load_j0_config
from steering_sim.j0_coupling.config import J0CaseConfig
from steering_sim.j0_coupling.mechanism import (ENGINEERING_STEERING_MODEL,
                                                build_mechanism_model)
from steering_sim.j0_coupling.runner import J0Runner


OUT = ROOT / "outputs" / "degradation" / "phase_D1"
DATA = ROOT / "data" / "degradation"
CONFIG = ROOT / "configs" / "degradation" / "d1_degradation_models.json"
HEALTHY = ROOT / "configs" / "j1r2" / "engineering_hydraulics.json"
CHANNELS = ("channel_front", "channel_rear_1", "channel_rear_2", "channel_rear_3")


def _columns() -> list[str]:
    return list(REQUIRED_COLUMNS + OPTIONAL_COLUMNS)


def make_spectra() -> tuple[Path, Path]:
    DATA.mkdir(parents=True, exist_ok=True)
    template = pd.DataFrame(columns=_columns())
    template_csv = DATA / "task_spectrum_template.csv"
    template_xlsx = DATA / "task_spectrum_template.xlsx"
    template.to_csv(template_csv, index=False, encoding="utf-8-sig")
    template.to_excel(template_xlsx, index=False)

    daily = [
        ("停车_泵停", 0, 0, 21600, 0.75, False, 1.0, 35),
        ("启动直行", 10, 0, 3600, 0.75, True, 1.0, 40),
        ("左小角保持", 10, 5, 1800, 0.75, True, 1.0, 45),
        ("回正低速", 10, 0, 3600, 0.75, True, 1.0, 45),
        ("右转", 8, -10, 1800, 0.80, True, 1.1, 50),
        ("高速直行", 40, 0, 7200, 0.70, True, 1.0, 55),
        ("停车左大角", 0, 30, 600, 0.80, True, 1.3, 55),
        ("大角保持", 0, 30, 600, 0.80, True, 1.3, 55),
        ("大角回正", 0, 0, 600, 0.80, True, 1.3, 50),
        ("高速大角风险", 60, 20, 300, 0.65, True, 1.2, 50),
        ("日末直行", 20, 0, 44700, 0.70, True, 1.0, 45),
    ]
    rows: list[dict[str, object]] = []
    for day in range(1, 31):
        for position, (label, speed, angle, duration, mu, running, contam, temp) in enumerate(daily, 1):
            row: dict[str, object] = {
                "segment_id": f"D{day:02d}-S{position:02d}-{label}",
                "speed_kmh": speed, "target_outer_angle_deg": angle,
                "segment_duration_s": duration, "friction_coefficient": mu,
                "pump_running": running, "repeats": 1,
                "contamination_severity": contam, "oil_temperature_c": temp,
            }
            row.update({f"axle_mass_{i}_t": 11.5 for i in range(1, 7)})
            rows.append(row)
    frame = pd.DataFrame(rows, columns=_columns())
    example_csv = DATA / "task_spectrum_30day_example.csv"
    example_xlsx = DATA / "task_spectrum_30day_example.xlsx"
    frame.to_csv(example_csv, index=False, encoding="utf-8-sig")
    with pd.ExcelWriter(example_xlsx, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False, sheet_name="30day_spectrum")
        pd.DataFrame({
            "说明": ["每行一个连续工况段，严格保留顺序。",
                    "segment_duration_s × repeats 的总和必须等于指定时长。",
                    "污染严重度 1.0 为 D1 工程假设基准；全部系数待甲方标定。",
                    "高速大角工况会报告附着风险，但不会使预测崩溃。"]
        }).to_excel(writer, index=False, sheet_name="README")
    return example_csv, example_xlsx


def build_runner(parameters=None) -> J0Runner:
    config = load_j0_config(ROOT / "configs" / "j0" / "j0_config.json")
    if parameters is not None:
        config = replace(config, engineering_parameters=parameters)
    model = build_mechanism_model(
        ENGINEERING_STEERING_MODEL,
        ROOT / "mechanical_model_input_spec_v1.0.yaml",
        ROOT / "mechanics_ackermann_v2" / "config.json",
        ROOT / "mechanics_ackermann_redesigned" / "config.json",
        design_path=ROOT / "configs" / "j1" / "engineering_mechanism.json",
        engineering_config_path=ROOT / "configs" / "j1" / "engineering_config.json")
    return J0Runner(config, model, probe_authority=False,
                    mechanical_mode=ENGINEERING_STEERING_MODEL)


def physical_injection_evidence() -> list[dict[str, object]]:
    """在同一个 22 状态 RHS 上做健康/独立部件退化对照。"""
    healthy = load_parameters(HEALTHY)
    demo = with_component_degradation(
        healthy,
        pumps={"front": PumpDegradationParameters(
                   internal_leakage_m3_s_per_pa=3.0e-12),
               "rear": PumpDegradationParameters()},
        valves={name: (ValveDegradationParameters(
                    internal_leakage_m3_s_per_pa=2.0e-12)
                if name == "channel_rear_1" else ValveDegradationParameters())
                for name in CHANNELS},
        cylinders={name: (CylinderDegradationParameters(
                    internal_leakage_m3_s_per_pa=2.0e-12)
                if name == "channel_rear_2" else CylinderDegradationParameters())
                for name in CHANNELS})
    systems = {"healthy": EngineeringHydraulicSystem(healthy),
               "degraded": EngineeringHydraulicSystem(demo)}
    state = systems["healthy"].neutral_state()
    for index in range(4):
        state[5 * index] = 12.0e6
        state[5 * index + 1] = 3.0e6
        state[5 * index + 4] = 0.35
    inputs = HydraulicInput((0.35,) * 4, (157.08,) * 4,
                            (5000.0, 5000.0, 5000.0, 5000.0))
    evaluated = {name: system.evaluate(0.0, state.copy(), inputs)
                 for name, system in systems.items()}
    rows: list[dict[str, object]] = []
    for index, channel in enumerate(CHANNELS):
        h = evaluated["healthy"][1].channels[index]
        d = evaluated["degraded"][1].channels[index]
        rows.append({
            "component_test": channel,
            "healthy_valve_leakage_m3_s": h.valve_leakage_flow_m3_s,
            "degraded_valve_leakage_m3_s": d.valve_leakage_flow_m3_s,
            "healthy_cylinder_leakage_m3_s": h.cylinder_leakage_flow_m3_s,
            "degraded_cylinder_leakage_m3_s": d.cylinder_leakage_flow_m3_s,
            "pressure_derivative_delta_norm_pa_s": float(np.linalg.norm(
                evaluated["degraded"][0][5 * index:5 * index + 2]
                - evaluated["healthy"][0][5 * index:5 * index + 2])),
        })
    for supply_index, supply in enumerate(("front", "rear")):
        rows.append({
            "component_test": f"pump_{supply}",
            "healthy_pump_flow_m3_s": evaluated["healthy"][1].pump_flow_m3_s[supply_index],
            "degraded_pump_flow_m3_s": evaluated["degraded"][1].pump_flow_m3_s[supply_index],
            "supply_pressure_derivative_delta_pa_s": float(
                evaluated["degraded"][0][20 + supply_index]
                - evaluated["healthy"][0][20 + supply_index]),
        })
    return rows


def coupled_health_comparison(final_parameters) -> dict[str, object]:
    """同一 J1-R2 闭环工况分别使用健康参数和第 30 天内存参数。"""
    case = J0CaseConfig(id="D1_COUPLED_10DEG", target_outer_angle_deg=10.0,
                        speed_kmh=5.0, duration_s=1.2,
                        reference_time_s=0.8333333333333334)
    results = {}
    for name, parameters in (("healthy", load_parameters(HEALTHY)),
                             ("day30", final_parameters)):
        runner = build_runner(parameters)
        result = runner.run_case(case)
        results[name] = {
            "completed": result.completed,
            "failure_reason": result.failure_reason,
            "final_axle1_right_deg": float(
                result.samples["wheel_axle1_right_actual_deg"][-1]),
            "minimum_front_supply_pressure_mpa_g": float(np.min(
                result.samples["supply_pressure_front_mpa_g"])),
            "minimum_rear_supply_pressure_mpa_g": float(np.min(
                result.samples["supply_pressure_rear_mpa_g"])),
            "max_pressure_mpa_g": float(result.summary["max_pressure_mpa_g"]),
            "max_tracking_error_deg": float(
                result.summary["max_tracking_error_vs_command_deg"]),
        }
    results["delta_day30_minus_healthy"] = {
        key: float(results["day30"][key]) - float(results["healthy"][key])
        for key in ("final_axle1_right_deg", "minimum_front_supply_pressure_mpa_g",
                    "minimum_rear_supply_pressure_mpa_g", "max_pressure_mpa_g",
                    "max_tracking_error_deg")}
    return results


def _plot(curve: pd.DataFrame, target: Path) -> None:
    fig, axes = plt.subplots(3, 1, figsize=(11, 10), sharex=True)
    groups = (("pump", "Gear-pump damage"), ("valve", "Steering-valve damage"),
              ("cylinder", "Cylinder-seal damage"))
    for axis, (prefix, title) in zip(axes, groups):
        for column in curve.columns:
            if column.startswith(f"cumulative_damage_{prefix}_"):
                axis.plot(curve["day"], curve[column], label=column.replace(
                    f"cumulative_damage_{prefix}_", ""))
        axis.set_ylabel("D (-)")
        axis.set_title(title)
        axis.grid(True, alpha=0.3)
        axis.legend(ncol=4, fontsize=8)
    axes[-1].set_xlabel("Mission time (day)")
    fig.tight_layout()
    fig.savefig(target, dpi=160)
    plt.close(fig)


def run(spectrum_path: Path, *, package: bool = False) -> dict[str, object]:
    OUT.mkdir(parents=True, exist_ok=True)
    healthy_hash_before = hashlib.sha256(HEALTHY.read_bytes()).hexdigest()
    spectrum = load_task_spectrum(spectrum_path, expected_days=30.0)
    config = load_degradation_config(CONFIG)
    runner = build_runner()
    prediction_started = time.perf_counter()
    prediction = D1Predictor(runner, config).predict(spectrum)
    prediction_wall_s = time.perf_counter() - prediction_started

    segments = pd.DataFrame(prediction.segment_records)
    curve = pd.DataFrame(prediction.curve_records)
    parameters = pd.DataFrame(component_parameter_rows(
        prediction.final_parameters, prediction.final_state, config))
    segments.to_csv(OUT / "segment_load_damage.csv", index=False,
                    encoding="utf-8-sig")
    curve.to_csv(OUT / "degradation_curves_0_30day.csv", index=False,
                 encoding="utf-8-sig")
    parameters.to_csv(OUT / "final_component_parameters_day30.csv", index=False,
                      encoding="utf-8-sig")
    (OUT / "final_component_parameters_day30.json").write_text(json.dumps({
        "model_version": config.model_version,
        "assumption_tag": config.assumption_tag,
        "parameters": parameters.to_dict(orient="records"),
        "engineering_hydraulic_degradation":
            prediction.final_parameters.degradation.to_dict(),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(prediction.risks).to_csv(OUT / "task_spectrum_risks.csv",
                                          index=False, encoding="utf-8-sig")
    evidence = physical_injection_evidence()
    pd.DataFrame(evidence).to_csv(OUT / "healthy_degraded_physics_comparison.csv",
                                  index=False, encoding="utf-8-sig")
    coupled = coupled_health_comparison(prediction.final_parameters)
    (OUT / "healthy_day30_coupled_comparison.json").write_text(
        json.dumps(coupled, ensure_ascii=False, indent=2), encoding="utf-8")
    _plot(curve, OUT / "degradation_curves_0_30day.png")

    healthy_hash_after = hashlib.sha256(HEALTHY.read_bytes()).hexdigest()
    summary: dict[str, object] = {
        "phase": "D1", "model_version": config.model_version,
        "spectrum": str(spectrum.source), "segments_expanded": len(segments),
        "total_duration_s": spectrum.total_duration_s,
        "total_days": spectrum.total_days,
        "prediction_wall_s": prediction_wall_s,
        "under_60_seconds": prediction_wall_s < 60.0,
        "cache_hits": prediction.cache_hits, "cache_misses": prediction.cache_misses,
        "risk_count": len(prediction.risks),
        "healthy_parameter_sha256_before": healthy_hash_before,
        "healthy_parameter_sha256_after": healthy_hash_after,
        "healthy_parameter_unchanged": healthy_hash_before == healthy_hash_after,
        "deterministic": True, "random_seed": None,
        "engineering_assumption": True,
        "calibration_status": "PENDING_CLIENT_CALIBRATION",
    }
    (OUT / "performance_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if package:
        package_phase_d1()
    return summary


def package_phase_d1() -> Path:
    target = ROOT / "handoff_to_chatgpt" / "phase_D1.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    include = [
        ROOT / "src" / "steering_sim" / "degradation",
        ROOT / "src" / "steering_sim" / "hydraulics_engineering",
        ROOT / "src" / "steering_sim" / "demo" / "degradation.py",
        ROOT / "src" / "steering_sim" / "demo" / "assessment.py",
        ROOT / "src" / "steering_sim" / "j0_coupling" / "runner.py",
        CONFIG, DATA, OUT, ROOT / "tests" / "degradation",
        ROOT / "scripts" / "d1", ROOT / "docs" / "degradation" / "phase_D1_report.md",
    ]
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for item in include:
            if item.is_dir():
                paths = sorted(path for path in item.rglob("*") if path.is_file()
                               and "__pycache__" not in path.parts
                               and path.name != "test_short_spectrum.csv")
            elif item.is_file():
                paths = [item]
            else:
                continue
            for path in paths:
                archive.write(path, path.relative_to(ROOT).as_posix())
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spectrum", type=Path)
    parser.add_argument("--package", action="store_true")
    args = parser.parse_args()
    example_csv, _ = make_spectra()
    summary = run(args.spectrum or example_csv, package=args.package)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
