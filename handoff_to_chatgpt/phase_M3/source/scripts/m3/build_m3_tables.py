"""PHASE M3：生成 61 转角几何/行程表、3111 全工况表与原始机构对照表。

交付物（全部落在 ``outputs/m3/``）：

``m3_angle_coverage.csv/.xlsx``
    ±30° 每 1° 的几何与行程覆盖检查（理想角、优化机构角、目标行程、
    方向、同桥同向、左右镜像、三桥锁零、行程是否超限、阿克曼 RMS）。
``m3_full_cases.csv/.xlsx``
    3111 组（17 车速 × 61 转角 × 3 摩擦系数）几何 + 地面载荷 + 适用性。
``m3_as_built_vs_redesigned.csv``
    甲方原始机构与优化设计机构的逐轮对照。
``m3_batch_summary.json``
    批量统计与结论。

批量**只跑快速机械几何 + 地面载荷 + 适用性**，不对 3111 组强制运行动态仿真。
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from steering_sim.ackermann.cases import (DEFAULT_ANGLES_DEG,  # noqa: E402
                                          DEFAULT_FRICTION, DEFAULT_SPEEDS_KMH,
                                          build_case_grid, grid_size, write_csv,
                                          write_template, write_xlsx)
from steering_sim.ackermann.cases_m3 import (angle_coverage,  # noqa: E402
                                             run_batch_m3)
from steering_sim.ackermann.redesign import WHEEL_ORDER  # noqa: E402
from steering_sim.ackermann.transmission import RedesignedTransmission  # noqa: E402
from steering_sim.mechanics import reference_geometry_from_file  # noqa: E402

SPEC = ROOT / "mechanical_model_input_spec_v1.0.yaml"
M1_CONFIG = ROOT / "mechanics_ackermann_v2" / "config.json"
REDESIGN_CONFIG = ROOT / "mechanics_ackermann_redesigned" / "config.json"
DESIGN_JSON = ROOT / "mechanics_ackermann_redesigned" / "design_parameters.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "outputs" / "m3"))
    parser.add_argument("--limit", type=int, default=0,
                        help=">0 时只跑前 N 组（调试用）；0 = 全量 3111 组")
    parser.add_argument("--no-loaded", action="store_true")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    from mechanics_ackermann_redesigned.model import RedesignedAckermannModel
    from mechanics_ackermann_v2.model import PhaseM1Model

    redesigned = RedesignedAckermannModel(SPEC, REDESIGN_CONFIG, DESIGN_JSON)
    as_built = PhaseM1Model(SPEC, M1_CONFIG)
    transmission = RedesignedTransmission(redesigned)

    # ---------------------------------------------------------- 61 转角表
    started = time.perf_counter()
    coverage = angle_coverage(redesigned, transmission, DEFAULT_ANGLES_DEG)
    coverage_rows = [item.to_dict() for item in coverage]
    write_csv(coverage_rows, out / "m3_angle_coverage.csv")
    try:
        write_xlsx(coverage_rows, out / "m3_angle_coverage.xlsx", sheet="61转角覆盖")
    except Exception as exc:
        print("XLSX 导出跳过：", exc)

    # ---------------------------------------------------- 原始机构对照
    compare_rows = []
    for item in coverage:
        target = item.angle_deg
        row = {"目标角_deg": target}
        try:
            original = as_built.solve_geometry(target)
            for wheel in WHEEL_ORDER:
                row[f"原始机构_{wheel}"] = round(
                    float(original.theoretical_angle_deg[wheel]), 4)
            row["原始机构几何状态"] = str(getattr(original, "geometry_class", "OK"))
        except Exception as exc:
            for wheel in WHEEL_ORDER:
                row[f"原始机构_{wheel}"] = None
            row["原始机构几何状态"] = f"求解失败：{type(exc).__name__}"
        new = redesigned.solve_geometry(target)
        for wheel in WHEEL_ORDER:
            row[f"优化机构_{wheel}"] = round(float(new.theoretical_angle_deg[wheel]), 4)
        for wheel in WHEEL_ORDER:
            row[f"理想_{wheel}"] = round(float(new.ideal_ackermann_angle_deg[wheel]), 4)
        row["优化机构几何状态"] = str(getattr(new, "geometry_class", "OK"))
        compare_rows.append(row)
    write_csv(compare_rows, out / "m3_as_built_vs_redesigned.csv")

    # ---------------------------------------------------------- 3111 工况
    specs = build_case_grid(DEFAULT_SPEEDS_KMH, DEFAULT_ANGLES_DEG, DEFAULT_FRICTION)
    if args.limit > 0:
        specs = specs[:args.limit]
    base, total = grid_size()
    print(f"工况网格：基础 {base} 组，含摩擦系数 {total} 组；本次运行 {len(specs)} 组")
    progress_state = {"t": time.perf_counter()}

    def progress(done: int, count: int) -> None:
        now = time.perf_counter()
        if done == count or now - progress_state["t"] > 20.0:
            progress_state["t"] = now
            print(f"  {done}/{count}（{done / max(count, 1) * 100:.1f}%）", flush=True)

    rows, summary = run_batch_m3(redesigned, transmission, specs,
                                 as_built_model=None,
                                 progress=progress,
                                 with_loaded=not args.no_loaded)
    write_csv(rows, out / "m3_full_cases.csv")
    try:
        write_xlsx(rows, out / "m3_full_cases.xlsx", sheet="全工况表")
    except Exception as exc:
        print("XLSX 导出跳过：", exc)
    write_template(out / "m3_case_template.csv")

    payload = {
        "mechanical_mode": "REDESIGNED_ACKERMANN",
        "tag": "ENGINEERING_REDESIGN_PROPOSAL",
        "grid": {"speeds": list(DEFAULT_SPEEDS_KMH), "angles": list(DEFAULT_ANGLES_DEG),
                 "friction": list(DEFAULT_FRICTION), "base": base, "total": total},
        "evaluated": len(specs),
        "batch_summary": summary.to_dict(),
        "angle_coverage": {
            "angles": len(coverage),
            "direction_ok": sum(1 for item in coverage if item.direction_ok),
            "left_right_ok": sum(1 for item in coverage if item.left_right_ok),
            "mirror_ok": sum(1 for item in coverage if item.mirror_ok),
            "third_axle_locked": sum(1 for item in coverage if item.third_axle_locked),
            "strokes_within_travel": sum(1 for item in coverage
                                         if item.strokes_within_travel),
            "max_ackermann_rms_deg": max(
                (item.ackermann_rms_deg or 0.0) for item in coverage),
            "max_abs_wheel_deg": max(
                (item.max_abs_wheel_deg or 0.0) for item in coverage),
        },
        "elapsed_s": round(time.perf_counter() - started, 2),
    }
    (out / "m3_batch_summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["angle_coverage"], ensure_ascii=False, indent=2))
    print(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2))
    print("输出目录：", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
