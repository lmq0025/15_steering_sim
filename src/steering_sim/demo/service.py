"""PHASE J0-DEMO 服务层：唯一的"跑一次仿真"入口。

界面、缓存、导出与批处理都走这一条路径，因此
**图像、结果摘要与时间序列必然来自同一次仿真**。

两种结果来源被严格区分，绝不混用：

``LIVE_RUN``
    刚刚真实积分得到的闭环结果（``DemoService.run``）。
``PRESET_REPLAY``
    预先算好并落盘的四个预设工况（``DemoService.replay_preset``）。
    回放会明确标注缓存时间与来源，不会被说成"刚刚完成的实时仿真"。
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import json
import math
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any, Callable, Mapping

import numpy as np

from steering_sim.j0_coupling.config import J0Config, load_j0_config
from steering_sim.j0_coupling.mechanism import (AS_BUILT_REFERENCE,
                                                ENGINEERING_STEERING_MODEL,
                                                MODE_LABELS, REDESIGNED_ACKERMANN,
                                                build_mechanism_model,
                                                normalise_mode)
from steering_sim.j0_coupling.reporting import (configure_chinese_font,
                                                write_samples_csv, write_summary_json)
from steering_sim.j0_coupling.runner import J0CaseResult, J0Runner

from . import plots
from .assessment import (ConsistencyReport, PreflightAssessment,
                         assess_preflight, check_run_consistency)
from .scenario import DemoScenario, preset_scenarios

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = ROOT / "configs" / "j0" / "j0_config.json"
DEFAULT_SPEC = ROOT / "mechanical_model_input_spec_v1.0.yaml"
DEFAULT_MECH_CONFIG = ROOT / "mechanics_ackermann_v2" / "config.json"
DEFAULT_REDESIGN_CONFIG = ROOT / "mechanics_ackermann_redesigned" / "config.json"
#: PHASE J1：唯一正式机械模型。
DEFAULT_ENGINEERING_CONFIG = ROOT / "configs" / "j1" / "engineering_config.json"
DEFAULT_ENGINEERING_DESIGN = ROOT / "configs" / "j1" / "engineering_mechanism.json"
DEFAULT_OUTPUT = ROOT / "outputs" / "j0_demo"
PRESET_CACHE_VERSION = "M3-1"


class DemoServiceError(RuntimeError):
    """界面可以直接展示的中文错误。"""


@dataclass
class DemoResult:
    scenario: DemoScenario
    preflight: PreflightAssessment
    samples: dict[str, np.ndarray]
    summary: dict[str, Any]
    consistency: ConsistencyReport
    figures: tuple[Path, ...]
    csv_path: Path
    report_path: Path | None
    provenance: str            # LIVE_RUN / PRESET_REPLAY
    provenance_note: str
    completed: bool
    failure_reason: str | None
    duration_wall_s: float

    @property
    def mechanical_mode(self) -> str:
        return str(self.summary.get("mechanical_mode", AS_BUILT_REFERENCE))

    @property
    def status(self) -> str:
        return str(self.summary.get("status", "FAIL"))

    @property
    def provenance_label(self) -> str:
        return ("预设结果回放" if self.provenance == "PRESET_REPLAY"
                else "重新运行仿真")

    def headline(self) -> str:
        notes = self.summary.get("status_notes") or []
        return "；".join(str(item) for item in notes) if notes else "—"


def _git_head() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, timeout=10,
                             capture_output=True, text=True, check=False)
        return out.stdout.strip() if out.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


class DemoService:
    """构建一次被控对象，之后可以反复评估与运行任意工况。"""

    def __init__(self, config_path: Path | str = DEFAULT_CONFIG,
                 spec_path: Path | str = DEFAULT_SPEC,
                 mech_config_path: Path | str = DEFAULT_MECH_CONFIG,
                 redesign_config_path: Path | str = DEFAULT_REDESIGN_CONFIG,
                 engineering_config_path: Path | str = DEFAULT_ENGINEERING_CONFIG,
                 engineering_design_path: Path | str = DEFAULT_ENGINEERING_DESIGN,
                 output_dir: Path | str = DEFAULT_OUTPUT,
                 probe_authority: bool = False,
                 mechanical_mode: str | None = None,
                 hydraulic_model: str | None = None) -> None:
        self.config: J0Config = load_j0_config(config_path)
        # PHASE J1-R2：缺省用正式工程液压模型；历史对照测试可显式退回 L1-Fast。
        if hydraulic_model is not None:
            self.config = replace(self.config,
                                  hydraulic_model=str(hydraulic_model).upper())
        self.config_path = Path(config_path)
        self.spec_path = Path(spec_path)
        self.mech_config_path = Path(mech_config_path)
        self.redesign_config_path = Path(redesign_config_path)
        self.engineering_config_path = Path(engineering_config_path)
        self.engineering_design_path = Path(engineering_design_path)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.mechanical_mode = normalise_mode(
            mechanical_mode if mechanical_mode is not None else
            self.config.mechanical_mode)
        self.cache_dir = self.output_dir / "preset_cache" / self.mechanical_mode
        self._probe_authority = bool(probe_authority)
        self._build_runner()
        self.git_head = _git_head()
        # 中文字体配置只改全局 rcParams 一次，且在构造（主线程）时完成，
        # 以免后台绘图线程与界面线程竞争写入。
        configure_chinese_font()

    # --------------------------------------------------------- 机械模式
    def _build_runner(self) -> None:
        try:
            model = build_mechanism_model(
                self.mechanical_mode, self.spec_path, self.mech_config_path,
                self.redesign_config_path,
                design_path=(self.engineering_design_path
                             if self.mechanical_mode == ENGINEERING_STEERING_MODEL
                             else None),
                engineering_config_path=self.engineering_config_path)
        except Exception as exc:  # pragma: no cover - 环境损坏时的中文提示
            raise DemoServiceError(
                f"无法加载机械模型（{self.mechanical_mode}）：{exc}") from exc
        self.model = model
        self.runner = J0Runner(self.config, model,
                               probe_authority=self._probe_authority,
                               mechanical_mode=self.mechanical_mode)
        self.centers = dict(model.centers)

    def set_mode(self, mode: str) -> None:
        """切换机械机构模式；切换后必须重新运行，缓存按模式分开存放。"""
        selected = normalise_mode(mode)
        if selected == self.mechanical_mode:
            return
        self.mechanical_mode = selected
        self.cache_dir = self.output_dir / "preset_cache" / selected
        self._build_runner()

    @property
    def mode_label(self) -> str:
        return MODE_LABELS.get(self.mechanical_mode, self.mechanical_mode)

    @property
    def is_redesign(self) -> bool:
        return self.mechanical_mode == REDESIGNED_ACKERMANN

    # ------------------------------------------------------------- 输入
    def _apply(self, scenario: DemoScenario) -> None:
        """把工况输入写入被控对象边界。

        只改外部边界（摩擦系数、轴荷），不改任何本构参数。
        """
        self.runner.mu = float(scenario.friction_coefficient)
        self.runner.axle_mass_t = tuple(float(v) for v in scenario.axle_mass_t)

    def assess(self, scenario: DemoScenario) -> PreflightAssessment:
        self._apply(scenario)
        return assess_preflight(scenario, self.runner)

    # ------------------------------------------------------------- 运行
    def run(self, scenario: DemoScenario, *,
            progress: Callable[[str], None] | None = None,
            on_fraction: Callable[[float], None] | None = None,
            export: bool = True,
            profile: Callable[[float], tuple[float, float]] | None = None,
            reference_start_outer_angle_deg: float = 0.0,
            initial_state: np.ndarray | None = None,
            should_stop: Callable[[], bool] | None = None,
            reference_time_s: float | None = None,
            output_suffix: str = "",
            generate_figures: bool = True,
            allow_extended_duration: bool = False) -> DemoResult:
        """真实积分一个工况；这是唯一的计算入口。

        ``on_fraction`` 接收 0~1 的积分完成比例，供界面进度条使用；
        它不影响任何数值结果。
        """
        report = progress or (lambda _message: None)
        preflight = self.assess(scenario)
        duration_only = (preflight.blockers and
                         all("仿真时长" in item for item in preflight.blockers))
        if not preflight.runnable and not (allow_extended_duration and duration_only):
            raise DemoServiceError("工况不满足运行条件：\n" + "\n".join(preflight.blockers))

        report(f"正在积分液压—机械闭环（{self.runner.dt_c * 1000:g} ms 控制 / "
               f"{self.runner.dt_h * 1000:g} ms 液压）…")
        from steering_sim.j0_coupling.config import J0CaseConfig
        case = J0CaseConfig(id=scenario.case_id,
                            target_outer_angle_deg=scenario.target_outer_angle_deg,
                            speed_kmh=scenario.speed_kmh,
                            duration_s=scenario.duration_s,
                            reference_time_s=reference_time_s)
        started = time.perf_counter()
        raw: J0CaseResult = self.runner.run_case(
            case, on_progress=on_fraction, profile=profile,
            reference_start_outer_angle_deg=reference_start_outer_angle_deg,
            initial_state=initial_state, should_stop=should_stop)
        wall = time.perf_counter() - started

        report("正在导出时间序列…")
        safe_suffix = "".join(ch for ch in output_suffix if ch.isalnum() or ch in "_-")
        out_dir = self.output_dir / (scenario.signature() + (f"_{safe_suffix}" if safe_suffix else ""))
        csv_path = write_samples_csv(raw, out_dir / "timeseries.csv")

        result = DemoResult(
            scenario=scenario, preflight=preflight, samples=raw.samples,
            summary=dict(raw.summary), consistency=None, figures=(),
            csv_path=csv_path, report_path=None, provenance="LIVE_RUN",
            provenance_note=f"由 DemoService.run 于 {time.strftime('%Y-%m-%d %H:%M:%S')} 实时积分",
            completed=raw.completed, failure_reason=raw.failure_reason,
            duration_wall_s=wall)

        report("正在生成演示图像…")
        result.figures = (plots.plot_all(result, self.centers, out_dir)
                          if raw.samples and generate_figures else ())
        result.consistency = check_run_consistency(
            raw.samples, raw.summary, [p.name for p in result.figures],
            str(csv_path), scenario)
        result.summary["preflight_flags"] = list(preflight.flags)
        result.summary["consistency_flags"] = list(result.consistency.flags)
        result.summary["scenario_signature"] = scenario.signature()
        result.summary["provenance"] = "LIVE_RUN"
        result.summary["extended_ramp_duration"] = bool(
            allow_extended_duration and scenario.duration_s > 60.0)
        write_summary_json(result.summary, out_dir / "summary.json")
        if export:
            result.report_path = self.write_report(result)
        return result

    # ------------------------------------------------------------- 缓存
    def cache_paths(self, key: str) -> tuple[Path, Path]:
        return (self.cache_dir / f"{key}.npz", self.cache_dir / f"{key}.json")

    def cache_exists(self, key: str) -> bool:
        npz, meta = self.cache_paths(key)
        return npz.exists() and meta.exists()

    def store_preset(self, key: str, result: DemoResult) -> None:
        """把一次真实运行的结果落盘为预设回放缓存。"""
        if result.provenance != "LIVE_RUN":
            raise DemoServiceError("只有实时运行的结果可以写入预设缓存。")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        npz, meta = self.cache_paths(key)
        np.savez_compressed(npz, **{k: np.asarray(v) for k, v in result.samples.items()})
        write_summary_json({
            "cache_version": PRESET_CACHE_VERSION,
            "key": key,
            "case_id": result.scenario.case_id,
            "signature": result.scenario.signature(),
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "git_head": self.git_head,
            "duration_wall_s": result.duration_wall_s,
            "summary": result.summary,
            "figures": [path.name for path in result.figures],
            "consistency_flags": list(result.consistency.flags),
        }, meta)
        for figure in result.figures:
            target = self.cache_dir / figure.name
            if figure.exists() and figure.resolve() != target.resolve():
                shutil.copy2(figure, target)
        self.export_csv(result, self.cache_dir / f"{key}_timeseries.csv")

    def replay_preset(self, key: str) -> DemoResult:
        """读取预设缓存。结果被明确标注为回放，不冒充实时仿真。"""
        npz, meta = self.cache_paths(key)
        if not (npz.exists() and meta.exists()):
            raise DemoServiceError(
                f"预设 {key} 尚无缓存。请先运行一次该工况并保存为预设缓存，"
                f"或直接选择「重新运行仿真」。")
        payload = json.loads(meta.read_text(encoding="utf-8"))
        if payload.get("cache_version") != PRESET_CACHE_VERSION:
            raise DemoServiceError(
                f"预设缓存 {key} 版本为 {payload.get('cache_version')}，"
                f"与当前 {PRESET_CACHE_VERSION} 不一致，请重建缓存。")
        # 缓存键就是工况号（J0-01…），用它还原 case_id，否则图题会退化成 "DEMO"。
        scenario = replace(_scenario_from_signature(payload["signature"]),
                           case_id=str(payload.get("case_id") or key))
        with np.load(npz) as data:
            samples = {name: data[name] for name in data.files}
        summary = dict(payload["summary"])
        figures = tuple(self.cache_dir / name for name in payload.get("figures", []))
        consistency = check_run_consistency(
            samples, summary, [p.name for p in figures],
            str(self.cache_dir / "timeseries.csv"), scenario)
        preflight = self.assess(scenario)
        created = payload.get("created_at", "未知时间")
        return DemoResult(
            scenario=scenario, preflight=preflight, samples=samples,
            summary=summary, consistency=consistency, figures=figures,
            csv_path=self.cache_dir / f"{key}_timeseries.csv", report_path=None,
            provenance="PRESET_REPLAY",
            provenance_note=(f"预设结果回放：缓存于 {created}，"
                             f"由 git {str(payload.get('git_head'))[:8]} 实时运行产生。"
                             f"这不是刚刚完成的实时仿真。"),
            completed=bool(summary.get("completed", False)),
            failure_reason=summary.get("failure_reason"),
            duration_wall_s=float(payload.get("duration_wall_s", 0.0)))

    def build_preset_cache(self, *, progress: Callable[[str], None] | None = None,
                           force: bool = False) -> dict[str, DemoResult]:
        """构建四个预设工况的快速展示缓存（每个都真实跑一次）。"""
        report = progress or (lambda _message: None)
        built: dict[str, DemoResult] = {}
        for preset in preset_scenarios():
            if self.cache_exists(preset.key) and not force:
                report(f"预设 {preset.key} 已有缓存，跳过。")
                continue
            report(f"正在运行预设 {preset.key}（{preset.name}）…")
            result = self.run(preset.scenario, progress=report)
            self.store_preset(preset.key, result)
            built[preset.key] = result
        return built

    # ------------------------------------------------------------- 导出
    def export_csv(self, result: DemoResult, target: Path | str) -> Path:
        """把当前结果的时间序列导出到用户选定位置。"""
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        keys = list(result.samples)
        with target.open("w", newline="", encoding="utf-8-sig") as handle:
            import csv
            writer = csv.writer(handle)
            writer.writerow(keys)
            for row in zip(*(result.samples[key] for key in keys)):
                writer.writerow([f"{value:.12g}" for value in row])
        return target

    def write_report(self, result: DemoResult) -> Path:
        text = build_text_report(result, self.git_head)
        path = self.output_dir / result.scenario.signature() / "demo_report.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path


def _scenario_from_signature(signature: str) -> DemoScenario:
    """从 ``DemoScenario.signature()`` 还原工况（缓存回放用）。"""
    head, _, tail = signature.partition("_v")
    angle = float(head[1:])
    speed, _, rest = tail.partition("_mu")
    mu, _, rest = rest.partition("_m")
    loads, _, duration = rest.partition("_t")
    return DemoScenario(
        target_outer_angle_deg=angle, speed_kmh=float(speed),
        friction_coefficient=float(mu),
        axle_mass_t=tuple(float(v) for v in loads.split("-")),
        duration_s=float(duration))


def build_text_report(result: DemoResult, git_head: str) -> str:
    """一次运行的简明结果报告（中文，面向甲方演示）。"""
    scenario = result.scenario
    summary = result.summary
    lines: list[str] = []
    lines.append("# 电液转向系统联合仿真平台 — 单工况结果报告")
    lines.append("")
    lines.append(f"- 结果来源：**{result.provenance_label}**（{result.provenance_note}）")
    lines.append(f"- 机械机构模式：**{MODE_LABELS.get(result.mechanical_mode, result.mechanical_mode)}**"
                 f"（`{result.mechanical_mode}`）")
    if result.mechanical_mode == ENGINEERING_STEERING_MODEL:
        lines.append("- 模型来源标记：`ENGINEERING_STEERING_MODEL`"
                     "（甲方原始硬点不变；中间传动机构为 ENGINEERING_DESIGN_ASSUMPTION）")
    elif result.mechanical_mode == REDESIGNED_ACKERMANN:
        lines.append("- 模型来源标记：`ENGINEERING_REDESIGN_PROPOSAL`（M3 历史方案）")
    else:
        lines.append("- 模型来源标记：`CUSTOMER_AS_BUILT_LINKAGE`（历史对照）")
    lines.append(f"- 工况：{scenario.describe()}")
    lines.append(f"- 代码版本：`{git_head}`")
    lines.append(f"- 判定：**{result.status}**")
    lines.append("")
    lines.append("## 1. 工程适用范围与假设")
    lines.append("")
    lines.append(f"- 摩擦系数与轴荷为工程假设：{scenario.friction_coefficient:.2f} / "
                 f"{scenario.axle_mass_t[0]:.2f} t（非实车测量值）")
    for item in result.preflight.ranges:
        if item.outside_verified:
            lines.append(f"- ⚠ {item.message()}")
    for flag in result.preflight.flags:
        lines.append(f"- 标记：`{flag}`")
    lines.append("")
    lines.append("## 2. 机械转向结果（十二轮）")
    lines.append("")
    lines.append("| 车轮 | 理想阿克曼角 [°] | 机构可达角 [°] | 实际角 [°] | 实际−机构 [°] |")
    lines.append("|---|---|---|---|---|")
    wheels = [f"axle{axle}_{side}" for axle in range(1, 7) for side in ("left", "right")]
    for wheel in wheels:
        actual = float(np.asarray(result.samples[f"wheel_{wheel}_actual_deg"])[-1])
        ideal = float(summary["target_wheel_angle_deg"][wheel])
        mech = float(summary["target_mechanism_wheel_angle_deg"][wheel])
        lines.append(f"| {wheel} | {ideal:+.3f} | {mech:+.3f} | {actual:+.3f} | "
                     f"{actual - mech:+.3f} |")
    lines.append("")
    lines.append("三桥固定："
                 f"最大 |{float(np.max(np.abs(result.samples['third_axle_max_abs_deg']))):.2e}|°")
    lines.append("")
    lines.append("## 3. 液压结果")
    lines.append("")
    lines.append("| 通道 | 目标行程 [mm] | 末行程 [mm] | A 腔峰值 [MPa] | B 腔峰值 [MPa] | 峰值液压力 [N] |")
    lines.append("|---|---|---|---|---|---|")
    for tag in summary["channel_names"]:
        samples = result.samples
        lines.append(
            f"| {tag} | {summary['target_x_ref_m'][tag] * 1e3:+.4f} | "
            f"{float(np.asarray(samples[f'{tag}_x_m'])[-1]) * 1e3:+.4f} | "
            f"{float(np.max(np.abs(samples[f'{tag}_pA_mpa_g']))):.3f} | "
            f"{float(np.max(np.abs(samples[f'{tag}_pB_mpa_g']))):.3f} | "
            f"{summary['peak_hydraulic_force_n'][tag]:.1f} |")
    lines.append("")
    for group, item in result.preflight.supply.to_dict()["groups"].items():
        lines.append(f"- 供油 {item['label']}：泵 {item['q_pump_l_per_min']:.2f} L/min，"
                     f"高压轨取流 {item['high_rail_demand_l_per_min']:.2f} L/min，"
                     f"余量 {item['margin_l_per_min']:.2f} L/min"
                     f"（{item['margin_fraction'] * 100:.1f}%）"
                     f"{'，**接近上限**' if item['near_limit'] else ''}"
                     f"{'，**供油不足**' if item['insufficient'] else ''}")
    lines.append("")
    lines.append("## 4. 控制结果")
    lines.append("")
    lines.append(f"- 最大行程误差：{summary.get('max_stroke_error_m', math.nan) * 1e3:.4f} mm")
    lines.append(f"- 对机构可达角的最大跟踪误差："
                 f"{summary.get('max_steady_wheel_angle_error_vs_mechanism_deg', math.nan):.4f}°")
    lines.append(f"- 对理想阿克曼角的最大偏差："
                 f"{summary.get('max_steady_wheel_angle_error_vs_ideal_deg', math.nan):.4f}°")
    lines.append(f"- 控制饱和占比：{summary.get('control_saturation_fraction', math.nan):.4f}")
    lines.append(f"- 积分抗饱和占比：{summary.get('anti_windup_active_fraction', math.nan):.4f}")
    lines.append("")
    lines.append("## 5. 工况与模型限制")
    lines.append("")
    lines.append(f"- 车速 {scenario.speed_kmh:.1f} km/h，"
                 f"最大横向加速度 {summary.get('max_adhesion_utilization', math.nan):.4f} "
                 f"（附着利用率）")
    lines.append(f"- 广义道路力矩峰值残差 "
                 f"{summary.get('virtual_work_residual_max_abs', math.nan):.3e} N·m/s")
    lines.append(f"- 闭链杆长残差 {summary.get('max_link_residual_m', math.nan):.3e} m")
    lines.append("")
    lines.append("## 6. 结论与说明")
    lines.append("")
    for note in (summary.get("status_notes") or []):
        lines.append(f"- {note}")
    for message in result.consistency.messages:
        lines.append(f"- {message}")
    if not result.completed:
        lines.append(f"- **仿真未跑完**：{result.failure_reason}")
    lines.append("")
    lines.append("> 本报告中的实际轮角全部由真实液压缸位移经机构闭链反求得到，"
                 "未复制任何目标角；机械自由度不作二次积分；"
                 "未使用任何人造诊断阻尼。")
    return "\n".join(lines) + "\n"
