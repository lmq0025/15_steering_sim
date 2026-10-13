"""D4 service facade.  Qt pages call this layer, never numerical kernels directly."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import time
from typing import Any, Callable

import numpy as np
import pandas as pd

from steering_sim.degradation import (
    D1Predictor, DegradationState, MultiModeDegradationState,
    build_cycle_profile, component_mode_rows, load_d3_config,
    load_degradation_config, load_task_spectrum, parameters_from_multimode)
from steering_sim.degradation.rul import advance_segment
from steering_sim.demo.batch import build_context, run_batch
from steering_sim.demo.scenario import DemoScenario
from steering_sim.demo.service import DemoService
from steering_sim.hydraulics_engineering import load_parameters
from steering_sim.j0_coupling.config import CHANNEL_ORDER, load_j0_config
from steering_sim.j0_coupling.mechanism import (ENGINEERING_STEERING_MODEL,
                                                build_mechanism_model)
from steering_sim.j0_coupling.runner import J0Runner
from steering_sim.quality_assessment import (QualityAssessor,
                                             load_quality_config,
                                             standard_cases)
from .response_analysis import (ResponseCriteria, analyze_response,
                                linear_ramp_profile)

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / "outputs" / "desktop"
D1_CONFIG = ROOT / "configs" / "degradation" / "d1_degradation_models.json"
D2_CONFIG = ROOT / "configs" / "degradation" / "d2_quality_thresholds.json"
D3_CONFIG = ROOT / "configs" / "degradation" / "d3_rul_models.json"
HEALTHY = ROOT / "configs" / "j1r2" / "engineering_hydraulics.json"
EXAMPLE_SPECTRUM = ROOT / "data" / "degradation" / "task_spectrum_30day_example.csv"
TEMPLATE_SPECTRUM = ROOT / "data" / "degradation" / "task_spectrum_template.xlsx"
RESPONSE_CONFIG = ROOT / "configs" / "desktop" / "d4_r1_response_analysis.json"


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _geometry():
    return build_mechanism_model(
        ENGINEERING_STEERING_MODEL,
        ROOT / "mechanical_model_input_spec_v1.0.yaml",
        ROOT / "mechanics_ackermann_v2" / "config.json",
        ROOT / "mechanics_ackermann_redesigned" / "config.json",
        design_path=ROOT / "configs" / "j1" / "engineering_mechanism.json",
        engineering_config_path=ROOT / "configs" / "j1" / "engineering_config.json")


def _runner(parameters=None, *, accelerated: bool = False, geometry=None) -> J0Runner:
    config = load_j0_config(ROOT / "configs" / "j0" / "j0_config.json")
    if parameters is not None:
        config = replace(config, engineering_parameters=parameters)
    if accelerated:
        quality = load_quality_config(D2_CONFIG)
        config = replace(config,
                         dt_hydraulic_s=float(quality.integration["dt_hydraulic_s"]),
                         dt_control_s=float(quality.integration["dt_control_s"]))
    return J0Runner(config, geometry or _geometry(), probe_authority=False,
                    mechanical_mode=ENGINEERING_STEERING_MODEL)


class DesktopCalculationService:
    """Stateless user-facing operations with auditable input/output paths."""

    def __init__(self, output_dir: Path = OUTPUT) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run_simulation(self, *, scenario: dict[str, Any], progress, is_cancelled):
        progress(0.03, "正在加载正式机械与液压模型")
        service = DemoService(output_dir=self.output_dir / "simulation",
                              mechanical_mode=ENGINEERING_STEERING_MODEL,
                              hydraulic_model="ENGINEERING_HYDRAULIC_V1")
        command_type = str(scenario.get("command_type", "step"))
        initial_angle = float(scenario.get("initial_outer_angle_deg", 0.0))
        final_angle = float(scenario["target_outer_angle_deg"])
        seconds_per_degree = float(scenario.get("seconds_per_degree", 6.0))
        criteria = ResponseCriteria.load(RESPONSE_CONFIG)
        if command_type == "ramp":
            command_completion = abs(final_angle - initial_angle) * seconds_per_degree
            duration_s = command_completion + float(scenario.get(
                "hold_observation_s", criteria.maximum_hold_observation_s))
        else:
            command_completion = 0.0
            duration_s = float(scenario["duration_s"])
        item = DemoScenario(
            target_outer_angle_deg=final_angle,
            speed_kmh=float(scenario["speed_kmh"]),
            friction_coefficient=float(scenario["friction_coefficient"]),
            axle_mass_t=tuple(float(value) for value in scenario["axle_mass_t"]),
            duration_s=duration_s, case_id="D4_R1_GUI")
        if is_cancelled():
            return {}
        initial_state = None
        profile = None
        original_timing = (service.runner.dt_h, service.runner.substeps,
                           service.runner.stride)
        if command_type == "ramp":
            service.runner.dt_h = criteria.slow_ramp_hydraulic_step_s
            service.runner.substeps = max(1, int(round(
                service.runner.dt_c / service.runner.dt_h)))
            service.runner.stride = max(1, int(round(0.01 / service.runner.dt_h)))
            profile = linear_ramp_profile(command_completion)
            if abs(initial_angle) > 1.0e-12:
                progress(0.07, "正在建立非零初始转角的真实液压状态")
                from steering_sim.j0_coupling.config import J0CaseConfig
                prepare = J0CaseConfig(
                    id="D4_R1_PRECONDITION", target_outer_angle_deg=initial_angle,
                    speed_kmh=float(scenario["speed_kmh"]),
                    duration_s=max(3.0, abs(initial_angle) / 12.0 + 2.0))
                prepared = service.runner.run_case(prepare, should_stop=is_cancelled)
                if is_cancelled():
                    return {}
                if not prepared.completed or prepared.final_state is None:
                    raise RuntimeError(f"非零初始状态建立失败：{prepared.failure_reason}")
                initial_state = prepared.final_state
        try:
            result = service.run(
                item, progress=lambda message: progress(0.15, message),
                on_fraction=lambda value: progress(0.15 + 0.75 * value,
                                                    "22状态联合动力学积分中"),
                profile=profile,
                reference_start_outer_angle_deg=initial_angle,
                initial_state=initial_state,
                should_stop=is_cancelled,
                reference_time_s=command_completion if command_type == "ramp" else None,
                output_suffix="RAMP" if command_type == "ramp" else "",
                generate_figures=False,
                allow_extended_duration=command_type == "ramp")
        finally:
            service.runner.dt_h, service.runner.substeps, service.runner.stride = original_timing
        if is_cancelled():
            return {}
        progress(0.95, "正在整理十二轮、液压缸和供油结果")
        wheel_rows = []
        for axle in range(1, 7):
            for side in ("left", "right"):
                prefix = f"wheel_axle{axle}_{side}"
                wheel_rows.append({
                    "车轮": f"{axle}桥{'左' if side == 'left' else '右'}轮",
                    "目标角/°": float(result.samples[f"{prefix}_command_deg"][-1]),
                    "实际角/°": float(result.samples[f"{prefix}_actual_deg"][-1]),
                    "液压跟踪误差/°": float(result.samples[f"{prefix}_actual_deg"][-1]
                                            - result.samples[f"{prefix}_command_deg"][-1]),
                })
        response = analyze_response(result.samples, command_completion, criteria)
        result_dir = Path(result.csv_path).parent
        response["wheel_table"].to_csv(result_dir / "wheel_response_times.csv",
                                       index=False, encoding="utf-8-sig")
        response["cylinder_table"].to_csv(result_dir / "cylinder_response_times.csv",
                                          index=False, encoding="utf-8-sig")
        return {"kind": "simulation", "summary": result.summary,
                "samples": result.samples, "wheel_table": pd.DataFrame(wheel_rows),
                "csv_path": str(result.csv_path), "report_path": str(result.report_path or ""),
                "runtime_s": result.duration_wall_s,
                "calculation_success": bool(result.completed),
                # Reuse the formal J1-R2 judgement instead of inventing a
                # desktop-only display threshold.
                "tracking_pass": bool(result.summary.get("TRACKING_PASS")) and
                                 bool(result.summary.get("TRANSIENT_TRACKING_PASS")),
                "trajectory_feasible": float(result.summary.get(
                    "target_path_adhesion_ratio", 0.0)) <= 1.0,
                "command_type": command_type,
                "initial_outer_angle_deg": initial_angle,
                "seconds_per_degree": seconds_per_degree,
                "response": response,
                "wheel_response_table": response["wheel_table"],
                "cylinder_response_table": response["cylinder_table"]}

    def run_batch_estimate(self, *, scenarios: list[dict[str, Any]], progress,
                           is_cancelled):
        progress(0.03, "正在构建3111准稳态能力估计上下文")
        context = build_context()
        items = [DemoScenario(
            target_outer_angle_deg=float(row["target_outer_angle_deg"]),
            speed_kmh=float(row["speed_kmh"]),
            friction_coefficient=float(row.get("friction_coefficient", 0.8)),
            axle_mass_t=tuple(float(value) for value in row.get("axle_mass_t", (11.5,) * 6)),
            duration_s=1.0, case_id=f"D4_BATCH_{index}")
            for index, row in enumerate(scenarios)]
        rows = run_batch(context, items,
                         on_progress=lambda value: progress(value, "准稳态能力估计中"),
                         should_stop=is_cancelled)
        return {"kind": "batch", "rows": pd.DataFrame(rows),
                "note": "FAST_BATCH_ESTIMATE：准稳态能力估计，不是完整22状态动态仿真"}

    def validate_spectrum(self, path: str | Path) -> dict[str, Any]:
        source = Path(path)
        try:
            spectrum = load_task_spectrum(source, expected_days=None)
            days = spectrum.total_days
            status = ("等于30天" if abs(days - 30.0) <= 1.0 / 86400.0 else
                      "不足30天" if days < 30.0 else "超过30天")
            risks = []
            for segment in spectrum.segments:
                if segment.speed_kmh >= 40 and abs(segment.target_outer_angle_deg) >= 15:
                    risks.append(f"{segment.segment_id}：高速大转角，需检查附着可行性")
            return {"valid": True, "days": days, "status": status,
                    "segment_count": sum(item.repeats for item in spectrum.segments),
                    "risks": risks, "spectrum": spectrum}
        except Exception as exc:
            return {"valid": False, "days": 0.0, "status": "数据异常",
                    "segment_count": 0, "risks": [str(exc)]}

    def run_degradation(self, *, spectrum_path: str, initial_state: str,
                        progress, is_cancelled):
        progress(0.03, "正在读取30天任务谱")
        spectrum = load_task_spectrum(spectrum_path, expected_days=30.0)
        d1_config = load_degradation_config(D1_CONFIG)
        d3_config = load_d3_config(D3_CONFIG)
        healthy = load_parameters(HEALTHY)
        predictor = D1Predictor(_runner(healthy), d1_config)
        initial_d1 = DegradationState.healthy(CHANNEL_ORDER)
        if initial_state == "d1_day30":
            progress(0.10, "正在生成D1第30天初始检查点")
            initial_d1 = predictor.predict(spectrum).final_state
        if is_cancelled():
            return {}
        progress(0.30, "正在逐段计算泵、阀、缸载荷与损伤")
        prediction = predictor.predict(spectrum, initial_d1)
        multimode = MultiModeDegradationState.from_d1(initial_d1)
        profile = build_cycle_profile(prediction.segment_records, d3_config)
        mode_rows = []
        for index, segment in enumerate(profile.segments):
            if is_cancelled():
                break
            multimode, increments = advance_segment(multimode, segment, d3_config)
            if index % 25 == 0:
                progress(0.30 + 0.55 * index / max(1, len(profile.segments)),
                         f"已完成 {index + 1}/{len(profile.segments)} 个任务段")
            mode_rows.append({"segment_id": segment.segment_id,
                              "elapsed_day": segment.elapsed_day,
                              **{f"increment_{key.replace(':', '_')}": value
                                 for key, value in increments.items()},
                              **multimode.flat_damage()})
        parameters = parameters_from_multimode(healthy, multimode, d3_config)
        rainflow_rows = []
        for channel, values in profile.rainflow_equivalents.items():
            rainflow_rows.append({"等效缸": channel, **values,
                                  "损伤用途": "缸摩擦增长模式"})
        progress(0.92, "正在整理退化曲线与雨流结果")
        return {"kind": "degradation", "d1_prediction": prediction,
                "final_state": multimode,
                "segment_frame": pd.DataFrame(mode_rows),
                "curve_frame": pd.DataFrame(prediction.curve_records),
                "component_frame": pd.DataFrame(component_mode_rows(
                    multimode, d3_config, parameters)),
                "rainflow_frame": pd.DataFrame(rainflow_rows),
                "risks": list(prediction.risks), "runtime_s": prediction.runtime_s,
                "assumption": "ENGINEERING_DESIGN_ASSUMPTION / PENDING_CLIENT_CALIBRATION"}

    def run_quality(self, *, state_source: str, severity: float,
                    progress, is_cancelled):
        progress(0.03, "正在构造退化参数并回写22状态模型")
        healthy = load_parameters(HEALTHY)
        d3 = load_d3_config(D3_CONFIG)
        state = MultiModeDegradationState.healthy()
        if state_source != "healthy":
            for key in tuple(state.modes):
                state = state.with_mode(key, replace(state.modes[key], damage=float(severity)))
        parameters = parameters_from_multimode(healthy, state, d3)
        quality = load_quality_config(D2_CONFIG)
        assessor = QualityAssessor(_runner(parameters, accelerated=True), quality)
        selected = [case for case in standard_cases()
                    if case.case_id in {"STD_L10", "STD_L30", "STD_MID_SPEED"}]
        rows, dynamics = [], []
        for index, case in enumerate(selected):
            if is_cancelled():
                break
            progress(0.10 + 0.80 * index / len(selected),
                     f"正在运行标准工况 {case.case_id}（完整22状态）")
            result = assessor.run(state_source, "D4_REAL_22_STATE", case)
            rows.append(dict(result.row))
            dynamics.append(result.dynamic)
        order = {"HEALTHY": 0, "SUBHEALTHY": 1, "DEGRADED": 2, "DANGEROUS": 3}
        grade = max((row["quality_grade"] for row in rows), key=order.get)
        return {"kind": "quality", "grade": grade,
                "rows": pd.DataFrame(rows), "dynamics": dynamics,
                "component_state": state, "source": state_source,
                "natural_or_sensitivity": ("自然/检查点状态" if state_source == "healthy"
                                             else "人为指定退化敏感性试验")}

    def run_rul(self, *, spectrum_path: str, initial_state: str,
                maximum_cycles: int, samples: int, random_seed: int,
                stochastic: bool, detailed: bool, progress, is_cancelled):
        if is_cancelled():
            return {}
        progress(0.03, "正在启动D3正式寿命预测服务")
        # D3 runner calls the in-memory D1/D2/D3 APIs and writes a fresh,
        # traceable result set for the current user selections.
        from scripts.d3.run_phase_d3 import run as run_d3
        summary = run_d3(Path(spectrum_path).resolve(), initial_state,
                         sample_count=samples if stochastic else 1,
                         maximum_cycles=maximum_cycles, package=False)
        progress(0.92, "正在读取本次新生成的寿命结果")
        source = ROOT / "outputs" / "degradation" / "phase_D3"
        def csv(name: str) -> pd.DataFrame:
            path = source / name
            return pd.read_csv(path) if path.exists() else pd.DataFrame()
        return {"kind": "rul", "summary": summary,
                "history": csv("mission_cycle_history.csv"),
                "quality": csv("quality_over_mission_cycles.csv"),
                "mc_summary": csv("monte_carlo_rul_summary.csv"),
                "mc_samples": csv("monte_carlo_rul_samples.csv"),
                "modes": csv("component_degradation_modes.csv"),
                "output_dir": str(source),
                "random_analysis_note": (
                    "快速Gamma载荷推进；并非每条随机路径都经过完整22状态验证"),
                "detection_note": (
                    "循环内时刻为工况段末首次越限检测时刻，不代表已求得段内真实失效瞬间")}

    def copy_template(self, target: str | Path) -> Path:
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(TEMPLATE_SPECTRUM, target)
        return target

    def provenance(self, spectrum_path: str = "") -> dict[str, Any]:
        result = {
            "mechanical_model": "ENGINEERING_STEERING_MODEL",
            "hydraulic_model": "ENGINEERING_HYDRAULIC_V1",
            "healthy_parameters_sha256": file_hash(HEALTHY),
            "d1_config_sha256": file_hash(D1_CONFIG),
            "d2_config_sha256": file_hash(D2_CONFIG),
            "d3_config_sha256": file_hash(D3_CONFIG),
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        if spectrum_path and Path(spectrum_path).exists():
            result["spectrum_sha256"] = file_hash(Path(spectrum_path))
        return result
