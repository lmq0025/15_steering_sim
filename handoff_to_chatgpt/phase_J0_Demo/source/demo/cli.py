"""PHASE J0-DEMO 无界面入口（供批处理、测试与演示前检查使用）。

    python -m steering_sim.demo.cli assess   --angle 2 --speed 5
    python -m steering_sim.demo.cli run      --angle 2 --speed 5
    python -m steering_sim.demo.cli replay   --preset J0-02
    python -m steering_sim.demo.cli build-cache
    python -m steering_sim.demo.cli checks    # 三个演示前检查，写 JSON
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from . import degradation
from .assessment import assess_preflight, assess_supply
from .scenario import (CUSTOMER_LIMITS, ENGINEERING_DEFAULTS, VERIFIED_LIMITS,
                       DemoScenario, preset_scenarios)
from .service import DemoService, DemoServiceError, build_text_report


def _scenario(args) -> DemoScenario:
    loads = tuple(float(v) for v in (args.load or
                                     [ENGINEERING_DEFAULTS["axle_mass_t"]] * 6))
    return DemoScenario(
        target_outer_angle_deg=float(args.angle),
        speed_kmh=float(args.speed),
        friction_coefficient=float(args.mu),
        axle_mass_t=loads,
        duration_s=float(args.duration),
        case_id=str(args.case_id or "DEMO"))


def _print_assessment(report) -> None:
    print("=== 演示前检查 ===")
    for line in report.summary_lines:
        print("  " + line)
    for message in report.blockers:
        print("  [阻止] " + message)
    for message in report.warnings:
        print("  [警告] " + message)
    print(f"  runnable = {report.runnable}")
    print(f"  flags = {list(report.flags)}")


def cmd_assess(args) -> int:
    service = DemoService(probe_authority=False)
    report = service.assess(_scenario(args))
    _print_assessment(report)
    return 0 if report.runnable else 1


def cmd_run(args) -> int:
    service = DemoService(probe_authority=False)
    scenario = _scenario(args)
    result = service.run(scenario, progress=lambda m: print("  .. " + m))
    print(f"结果来源：{result.provenance_label}")
    print(f"判定：{result.status}  耗时 {result.duration_wall_s:.1f} s")
    for message in result.consistency.messages:
        print("  · " + message)
    print(f"图像目录：{result.figures[0].parent if result.figures else '—'}")
    print(f"CSV：{result.csv_path}")
    print(f"报告：{result.report_path}")
    return 0


def cmd_replay(args) -> int:
    service = DemoService(probe_authority=False)
    result = service.replay_preset(args.preset)
    print(f"结果来源：{result.provenance_label}")
    print(f"  {result.provenance_note}")
    print(f"判定：{result.status}")
    return 0


def cmd_build_cache(args) -> int:
    service = DemoService(probe_authority=False)
    built = service.build_preset_cache(progress=lambda m: print("  .. " + m),
                                       force=args.force)
    print(f"新建缓存 {len(built)} 个：{sorted(built)}")
    for preset in preset_scenarios():
        print(f"  {preset.key}: {'有缓存' if service.cache_exists(preset.key) else '无缓存'}")
    return 0


def cmd_rebuild_figures(args) -> int:
    """用已缓存的样本重新出图（不重新仿真，用于调整图面样式）。"""
    from . import plots
    from .service import _scenario_from_signature
    service = DemoService(probe_authority=False)
    rebuilt = 0
    for preset in preset_scenarios():
        if not service.cache_exists(preset.key):
            print(f"  {preset.key}: 无缓存，跳过")
            continue
        result = service.replay_preset(preset.key)
        out_dir = service.output_dir / preset.scenario.signature()
        figures = plots.plot_all(result, service.centers, out_dir)
        service.store_preset(preset.key, _as_live(result, figures, out_dir))
        rebuilt += 1
        print(f"  {preset.key}: 重绘 {len(figures)} 张 → {out_dir}")
    print(f"重绘完成 {rebuilt} 个预设")
    return 0


def _as_live(result, figures, out_dir):
    """把回放结果标记成 LIVE_RUN 以便写回缓存（样本未变，只是重绘）。"""
    from .service import DemoResult
    return DemoResult(
        scenario=result.scenario, preflight=result.preflight, samples=result.samples,
        summary=result.summary, consistency=result.consistency, figures=tuple(figures),
        csv_path=out_dir / "timeseries.csv", report_path=result.report_path,
        provenance="LIVE_RUN",
        provenance_note=result.provenance_note, completed=result.completed,
        failure_reason=result.failure_reason, duration_wall_s=result.duration_wall_s)


def cmd_checks(args) -> int:
    """三个演示前检查，输出可直接引用的 JSON 证据。"""
    service = DemoService(probe_authority=False)
    payload: dict = {
        "phase": "J0-DEMO",
        "customer_limits": {k: list(v) for k, v in CUSTOMER_LIMITS.items()},
        "verified_limits": {k: list(v) for k, v in VERIFIED_LIMITS.items()},
        "engineering_defaults": dict(ENGINEERING_DEFAULTS),
        "degradation_interfaces": degradation.describe_interfaces(),
        "presets": [],
    }
    for preset in preset_scenarios():
        report = service.assess(preset.scenario)
        payload["presets"].append({
            "key": preset.key,
            "name": preset.name,
            "expected_status": preset.expected_status,
            "scenario": preset.scenario.signature(),
            "flags": list(report.flags),
            "runnable": report.runnable,
            "mechanism": {
                "status": report.mechanism.status,
                "flags": list(report.mechanism.flags),
                "max_abs_deviation_deg": report.mechanism.max_abs_deviation_deg,
                "max_abs_deviation_wheel": report.mechanism.max_abs_deviation_wheel,
                "opposite_sign_wheels": list(report.mechanism.opposite_sign_wheels),
                "geometry_status": report.mechanism.geometry_status,
                "axles": [{
                    "axle": item.axle,
                    "ideal_left_deg": item.ideal_left_deg,
                    "ideal_right_deg": item.ideal_right_deg,
                    "mechanism_left_deg": item.mechanism_left_deg,
                    "mechanism_right_deg": item.mechanism_right_deg,
                    "deviation_left_deg": item.deviation_left_deg,
                    "deviation_right_deg": item.deviation_right_deg,
                    "left_right_opposite": item.left_right_opposite,
                } for item in report.mechanism.axles],
            },
            "supply": report.supply.to_dict(),
            "messages": list(report.mechanism.messages) + list(report.supply.messages),
        })
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                      encoding="utf-8")
    for item in payload["presets"]:
        print(f"{item['key']}: 机械={item['mechanism']['status']} "
              f"供油={item['supply']['status']} flags={item['flags']}")
    print(f"wrote {output}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="电液转向系统联合仿真平台（命令行）")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_scenario_options(target: argparse.ArgumentParser) -> None:
        target.add_argument("--angle", type=float, default=0.0,
                            help="一桥外侧目标转角 [deg]")
        target.add_argument("--speed", type=float, default=0.0, help="车速 [km/h]")
        target.add_argument("--mu", type=float,
                            default=ENGINEERING_DEFAULTS["friction_coefficient"],
                            help="地面摩擦系数")
        target.add_argument("--load", type=float, nargs=6, default=None,
                            help="六桥轴荷 [t]")
        target.add_argument("--duration", type=float,
                            default=ENGINEERING_DEFAULTS["duration_s"],
                            help="仿真时长 [s]")
        target.add_argument("--case-id", default=None)

    p_assess = sub.add_parser("assess", help="只做演示前检查，不仿真")
    add_scenario_options(p_assess)
    p_assess.set_defaults(func=cmd_assess)

    p_run = sub.add_parser("run", help="实时运行一个工况")
    add_scenario_options(p_run)
    p_run.set_defaults(func=cmd_run)

    p_replay = sub.add_parser("replay", help="回放预设缓存")
    p_replay.add_argument("--preset", required=True)
    p_replay.set_defaults(func=cmd_replay)

    p_cache = sub.add_parser("build-cache", help="构建四个预设工况缓存")
    p_cache.add_argument("--force", action="store_true")
    p_cache.set_defaults(func=cmd_build_cache)

    p_rebuild = sub.add_parser("rebuild-figures",
                               help="用已缓存样本重新出图（不重新仿真）")
    p_rebuild.set_defaults(func=cmd_rebuild_figures)

    p_checks = sub.add_parser("checks", help="三个演示前检查")
    p_checks.add_argument("--output", default="outputs/j0_demo/demo_checks.json")
    p_checks.set_defaults(func=cmd_checks)

    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except DemoServiceError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
