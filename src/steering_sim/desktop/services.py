"""D4 service facade.  Qt pages call this layer, never numerical kernels directly."""
from __future__ import annotations

from dataclasses import replace,asdict
import copy
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
from .localization import cn

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / "outputs" / "desktop"
D1_CONFIG = ROOT / "configs" / "degradation" / "d1_degradation_models.json"
D2_CONFIG = ROOT / "configs" / "degradation" / "d2_quality_thresholds.json"
D3_CONFIG = ROOT / "configs" / "degradation" / "d3_rul_models.json"
HEALTHY = ROOT / "configs" / "j1r2" / "engineering_hydraulics.json"
EXAMPLE_SPECTRUM = ROOT / "data" / "degradation" / "r2" / "task_spectrum_30day_example.csv"
TEMPLATE_SPECTRUM = ROOT / "data" / "degradation" / "r2" / "task_spectrum_template.xlsx"
RESPONSE_CONFIG = ROOT / "configs" / "desktop" / "d4_r2_response_analysis.json"


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
        self._quality_baseline_cache={}

    def export_table(self, *, frame, path, raw=False, progress, is_cancelled):
        from .localization import chinese_frame
        target=Path(path)
        progress(.1,'正在后台整理表格字段')
        if is_cancelled(): return {}
        data=frame if raw else chinese_frame(frame)
        progress(.4,'正在后台写入表格，取消将在文件写完后生效')
        if target.suffix.lower()=='.xlsx': data.to_excel(target,index=False)
        else: data.to_csv(target,index=False,encoding='utf-8-sig')
        return {'kind':'export','path':str(target),'rows':len(data)}

    def run_simulation(self, *, scenario: dict[str, Any], progress, is_cancelled):
        service_started = time.perf_counter()
        progress(0.03, "正在加载正式机械与液压模型")
        service = DemoService(output_dir=self.output_dir / "simulation",
                              mechanical_mode=ENGINEERING_STEERING_MODEL,
                              hydraulic_model="ENGINEERING_HYDRAULIC_V1")
        command_type = str(scenario.get("command_type", "step"))
        initial_angle = float(scenario.get("initial_outer_angle_deg", 0.0))
        if command_type != "ramp":
            initial_angle = 0.0
        final_angle = float(scenario["target_outer_angle_deg"])
        seconds_per_degree = float(scenario.get("seconds_per_degree", 6.0))
        criteria = ResponseCriteria.load(RESPONSE_CONFIG)
        if command_type == "ramp":
            if not (np.isfinite(seconds_per_degree) and seconds_per_degree > 0):
                raise ValueError("每度转向时间必须为正数")
            if not (-30.0 <= initial_angle <= 30.0 and -30.0 <= final_angle <= 30.0):
                raise ValueError("起始转角和最终目标转角须位于已验证的 −30°～+30° 范围")
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
                # Preconditioning must use the same external load boundaries
                # as the subsequent run, not the defaults loaded from J0.
                service.runner.mu = item.friction_coefficient
                service.runner.axle_mass_t = item.axle_mass_t
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
                initial_target = service.runner.target(prepare)["x_ref"]
                initial_errors = [abs(prepared.final_state[service.runner.state_stride*i+2]
                                      - initial_target[c.channel])
                                  for i, c in enumerate(service.runner.config.channels)]
                if max(initial_errors) > criteria.cylinder_position_tolerance_m:
                    raise RuntimeError("非零初态未达到设定行程容差，请增加初态建立时长")
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
                allow_extended_duration=command_type == "ramp",
                reference_space="outer_angle" if command_type == "ramp" else "stroke")
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
                'input_scenario':dict(scenario),
                'input_scenario_sha256':hashlib.sha256(json.dumps(scenario,sort_keys=True,ensure_ascii=False).encode('utf-8')).hexdigest(),
                "samples": result.samples, "wheel_table": pd.DataFrame(wheel_rows),
                "csv_path": str(result.csv_path), "report_path": str(result.report_path or ""),
                "runtime_s": result.duration_wall_s,
                "service_runtime_s": time.perf_counter()-service_started,
                "simulation_horizon_s": float(result.samples['time_s'][-1]),
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

    def load_simulation_record(self, *, reference, progress,is_cancelled):
        """Read a project-selected record, without invoking any solver."""
        path=Path(reference['csv_path'])
        if not path.exists() or file_hash(path)!=reference['csv_sha256']:
            raise ValueError('历史时序文件不存在或哈希改变，不能按原结果回放')
        progress(.2,'正在读取项目指定的历史积分结果');frame=pd.read_csv(path)
        if is_cancelled():return {}
        criteria=ResponseCriteria(**reference['criteria'])
        response=analyze_response(frame.to_dict('series'),reference['command_completion_s'],criteria)
        result=dict(reference['result_metadata']);result.update(kind='simulation',samples={k:frame[k].to_numpy() for k in frame},
            response=response,wheel_table=response['wheel_table'][['wheel','final_target_deg','final_actual_deg']].copy(),wheel_response_table=response['wheel_table'],
            cylinder_response_table=response['cylinder_table'],csv_path=str(path),provenance_kind='HISTORICAL_REPLAY',
            replay_reference=reference)
        progress(1,'历史数据已载入，非本次新积分');return result

    def run_batch_estimate(self, *, scenarios: list[dict[str, Any]], progress,
                           is_cancelled):
        started=time.perf_counter()
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
        if is_cancelled(): return {}
        grids={field:sorted({float(row.get(field,.8)) for row in scenarios})
               for field in ('speed_kmh','target_outer_angle_deg','friction_coefficient')}
        metadata={'calculation_kind':'FAST_BATCH_ESTIMATE','input_count':len(scenarios),
                  'result_count':len(rows),'grids':grids,'runtime_s':time.perf_counter()-started}
        out=self.output_dir/'batch'/f'run_{time.time_ns()}';out.mkdir(parents=True,exist_ok=True)
        (out/'grid_metadata.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
        frame=pd.DataFrame(rows)
        from .localization import chinese_frame
        chinese_frame(frame).to_csv(out/'准稳态估计结果.csv',index=False,encoding='utf-8-sig')
        frame.to_csv(out/'raw_fast_batch_estimate.csv',index=False,encoding='utf-8-sig')
        return {"kind": "batch", "rows": pd.DataFrame(rows),
                'grids':grids,'row_count':len(rows),'output_dir':str(out),'runtime_s':metadata['runtime_s'],
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
                    "risks": risks, "spectrum": spectrum,
                    "rate_semantics": ("含旧任务谱兼容行：12°/s、最短0.4s；未自动改成6秒/度"
                         if any(s.seconds_per_degree is None for s in spectrum.segments)
                         else "各段显式角度斜坡，转向和保持均包含在整段时间内")}
        except Exception as exc:
            return {"valid": False, "days": 0.0, "status": "数据异常",
                    "segment_count": 0, "risks": [str(exc)]}

    def run_degradation(self, *, spectrum_path: str, initial_state: str,
                        progress, is_cancelled, stochastic=False, samples=128,
                        random_seed=20261013, **display_settings):
        from .degradation_service import run_degradation
        return run_degradation(self, spectrum_path, initial_state, progress,
                               is_cancelled, stochastic, samples, random_seed)


    def run_quality(self, *, state_source: str, severity: float,
                    progress, is_cancelled, multimode_state=None):
        started=time.perf_counter()
        progress(0.03, "正在构造退化参数并回写22状态模型")
        healthy = load_parameters(HEALTHY)
        d3 = load_d3_config(D3_CONFIG)
        state = multimode_state or MultiModeDegradationState.healthy()
        if state_source != "healthy" and multimode_state is None:
            for key in tuple(state.modes):
                state = state.with_mode(key, replace(state.modes[key], damage=float(severity)))
        parameters = parameters_from_multimode(healthy, state, d3)
        quality = load_quality_config(D2_CONFIG)
        geometry=_geometry()
        assessor = QualityAssessor(_runner(parameters, accelerated=True,geometry=geometry), quality)
        baseline_assessor=QualityAssessor(_runner(healthy,accelerated=True,geometry=geometry),quality)
        selected = [case for case in standard_cases()
                    if case.case_id in {"STD_L10", "STD_L30", "STD_MID_SPEED"}]
        rows, dynamics,healthy_rows,pairs,comparison = [], [],[],[],[]
        baseline_hashes={str(path.relative_to(ROOT)):file_hash(path) for path in (
            HEALTHY,D2_CONFIG,ROOT/'configs/j0/j0_config.json',
            ROOT/'configs/j1/engineering_mechanism.json',ROOT/'configs/j1/engineering_config.json',
            ROOT/'mechanical_model_input_spec_v1.0.yaml',
            ROOT/'src/steering_sim/j0_coupling/runner.py',
            ROOT/'src/steering_sim/hydraulics_engineering/model.py',
            ROOT/'src/steering_sim/quality_assessment/assessment.py')}
        for folder in ('src/steering_sim/hydraulics_engineering','src/steering_sim/j0_coupling',
                       'src/steering_sim/mechanics','mechanics_ackermann_redesigned'):
            baseline_hashes.update({p.relative_to(ROOT).as_posix():file_hash(p) for p in (ROOT/folder).glob('*.py')})
        for index, case in enumerate(selected):
            if is_cancelled():
                return {}
            progress(0.10 + 0.80 * index / len(selected),
                     f"正在运行标准工况 {cn(case.case_id)}（完整22状态）")
            result = assessor.run(state_source, "D4_REAL_22_STATE", case)
            key=self.quality_cache_key(case,baseline_hashes,quality.integration)
            cached=key in self._quality_baseline_cache
            if not cached:
                if is_cancelled():return {}
                baseline=baseline_assessor.run('healthy','D4_REAL_22_STATE',case)
                if baseline.dynamic.completed:self._quality_baseline_cache[key]=baseline
            else:baseline=self._quality_baseline_cache[key]
            baseline=copy.deepcopy(baseline)
            rows.append(dict(result.row))
            dynamics.append(result.dynamic)
            healthy_rows.append(dict(baseline.row))
            pairs.append(dict(case_id=case.case_id,healthy=baseline.dynamic,current=result.dynamic,
                              case_config=asdict(case),baseline_cache_key=key,baseline_cache_hit=cached))
            for metric in ('max_tracking_error_deg','rms_tracking_error_deg','steady_tracking_error_deg',
                'settling_delay_s','cylinder_displacement_error_mm','minimum_pump_flow_margin_lpm',
                'minimum_available_pump_flow_lpm','minimum_supply_pressure_margin_mpa',
                'valve_saturation_fraction','peak_pressure_mpa_g','peak_hydraulic_force_n','actuator_force_utilization'):
                a,b=baseline.row.get(metric,np.nan),result.row.get(metric,np.nan)
                comparison.append(dict(case_id=case.case_id,metric=metric,healthy_value=a,current_value=b,
                    change=(float(b)-float(a) if a is not None and b is not None else np.nan),quality_grade=result.row['quality_grade'],grade_causes=result.row.get('grade_causes','')))
        order = {"HEALTHY": 0, "SUBHEALTHY": 1, "DEGRADED": 2, "DANGEROUS": 3}
        grade = max((row["quality_grade"] for row in rows), key=order.get)
        out=self.output_dir/'quality'/f'run_{time.time_ns()}';out.mkdir(parents=True,exist_ok=True)
        from .localization import chinese_frame
        comparison_frame=pd.DataFrame(comparison)
        chinese_frame(comparison_frame).to_csv(out/'健康当前同工况指标.csv',index=False,encoding='utf-8-sig')
        trace_rows=[]
        for pair in pairs:
            for label in ('healthy','current'):
                frame=pd.DataFrame(pair[label].samples).copy();frame.insert(0,'state_label',label);frame.insert(0,'case_id',pair['case_id']);trace_rows.append(frame)
        pd.concat(trace_rows,ignore_index=True).to_csv(out/'paired_dynamic_raw.csv',index=False,encoding='utf-8-sig')
        (out/'comparison_conditions.json').write_text(json.dumps(dict(
            baseline_hashes=baseline_hashes,integration=dict(quality.integration),
            cases=[{k:v for k,v in p.items() if k not in ('healthy','current')} for p in pairs],
            mu=assessor.runner.mu,axle_mass_t=assessor.runner.axle_mass_t,
            controller_retuned=False),ensure_ascii=False,indent=2),encoding='utf-8')
        return {"kind": "quality", "grade": grade,
                "rows": pd.DataFrame(rows), "dynamics": dynamics,
                'healthy_rows':pd.DataFrame(healthy_rows),'comparison_dynamics':pairs,
                'comparison_frame':comparison_frame,'output_dir':str(out),
                'runtime_s':time.perf_counter()-started,
                "component_state": state, "source": state_source,
                "natural_or_sensitivity": ("自然/检查点状态" if state_source == "healthy" or multimode_state is not None
                                             else "人为指定退化敏感性试验")}

    @staticmethod
    def quality_cache_key(case,hashes,integration):
        payload=dict(case=asdict(case),model_hashes=hashes,integration=dict(integration),version='R3_PAIRED_22_STATE_V1')
        return hashlib.sha256(json.dumps(payload,sort_keys=True,default=str).encode('utf-8')).hexdigest()

    def run_rul(self, *, spectrum_path: str, initial_state: str,
                maximum_cycles: int, samples: int, random_seed: int,
                stochastic: bool, detailed: bool, progress, is_cancelled,
                quality_checkpoints: int = 5):
        if is_cancelled():
            return {}
        progress(0.03, "正在启动D3正式寿命预测服务")
        # D3 runner calls the in-memory D1/D2/D3 APIs and writes a fresh,
        # traceable result set for the current user selections.
        from scripts.d3.run_phase_d3 import run as run_d3
        source=self.output_dir/'rul'/f"run_{time.time_ns()}"
        source.mkdir(parents=True,exist_ok=True)
        original=Path(spectrum_path).resolve()
        snapshot=source/('mission_input'+original.suffix.lower())
        snapshot.write_bytes(original.read_bytes())
        input_reference=dict(original_input_path=str(original),input_snapshot=snapshot.name,
                             spectrum_sha256=file_hash(snapshot),initial_state_original=initial_state)
        selected_initial=initial_state
        if initial_state not in ('healthy','d1_day30'):
            state_snapshot=source/'initial_state_input.json'
            state_snapshot.write_bytes(Path(initial_state).read_bytes())
            selected_initial=str(state_snapshot)
            input_reference.update(initial_state_snapshot=state_snapshot.name,
                                   initial_state_sha256=file_hash(state_snapshot))
        (source/'desktop_input_reference.json').write_text(json.dumps(input_reference,ensure_ascii=False,indent=2),encoding='utf-8')
        summary = run_d3(snapshot, selected_initial,
                         sample_count=samples if stochastic else 1,
                         maximum_cycles=maximum_cycles, package=False,
                         output_dir=source,random_seed=random_seed,stochastic=stochastic,
                         detailed=detailed,should_stop=is_cancelled,on_progress=progress,record_all_states=True,
                         quality_checkpoints=quality_checkpoints)
        progress(0.92, "正在读取本次新生成的寿命结果")
        def csv(name: str) -> pd.DataFrame:
            path = source / name
            return pd.read_csv(path) if path.exists() else pd.DataFrame()
        checkpoints_path=source/'monte_carlo_checkpoints.npz'
        checkpoints=None
        if checkpoints_path.exists():
            with np.load(checkpoints_path,allow_pickle=False) as archive:checkpoints={key:archive[key].copy() for key in archive.files}
        return {"kind": "rul", "summary": summary,
                'mc_checkpoints':checkpoints,'mc_models':json.loads((source/'component_failure_thresholds.json').read_text('utf-8'))['modes'],
                'physical_reference_parameters':load_parameters(HEALTHY),
                "history": csv("mission_cycle_history.csv"),
                "deterministic_modes": csv("component_parameter_trajectories.csv"),
                "quality": csv("quality_over_mission_cycles.csv"),
                "quality_cases": csv("quality_checkpoint_case_details.csv"),
                "mc_summary": csv("monte_carlo_rul_summary.csv"),
                "mc_samples": csv("monte_carlo_rul_samples.csv"),
                "modes": csv("component_degradation_modes.csv"),
                "output_dir": str(source),
                'input_reference':input_reference,
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
