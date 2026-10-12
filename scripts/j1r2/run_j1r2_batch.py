"""PHASE J1-R2 第八节：3111 工况批量计算（``FAST_BATCH_ESTIMATE``）。

算法与能力边界都在 :mod:`steering_sim.demo.batch` 里 —— 界面上的"批量计算"按钮
调用的就是同一段代码，不存在第二套算法。本脚本只是它的命令行外壳，外加
默认的 3111 工况网格（车速 0~80 km/h 每 5 km/h、目标角 −30°~+30° 每 1°、
摩擦系数 0.70/0.75/0.80）。

要求 3111/3111 全部得到结构完整的结果：任何工况都不允许 KeyError / NaN /
中途停止。超过附着极限的工况照常输出并标记 ``VEHICLE_DYNAMIC_INFEASIBLE``。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from steering_sim.demo.batch import (build_context, columns_of, run_batch,  # noqa: E402
                                     write_csv, write_xlsx)
from steering_sim.demo.scenario import (AXLE_COUNT, DemoScenario,  # noqa: E402
                                        recommended_duration_s)
from steering_sim.engineering.mechanism import WHEEL_ORDER  # noqa: E402

SPEEDS = tuple(float(v) for v in range(0, 81, 5))
ANGLES = tuple(float(v) for v in range(-30, 31))
FRICTION = (0.70, 0.75, 0.80)


def default_scenarios(axle_mass_t: float) -> list[DemoScenario]:
    loads = (axle_mass_t,) * AXLE_COUNT
    scenarios = []
    for mu in FRICTION:
        for speed in SPEEDS:
            for angle in ANGLES:
                scenarios.append(DemoScenario(
                    angle, speed, friction_coefficient=mu, axle_mass_t=loads,
                    duration_s=recommended_duration_s(angle),
                    case_id=f"R2-{mu:.2f}-{speed:.0f}-{angle:+.0f}"))
    return scenarios


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "outputs" / "j1r2"))
    parser.add_argument("--axle-mass", type=float, default=11.5)
    parser.add_argument("--cases", default="",
                        help="可选的 CSV/XLSX 工况文件；缺省用 3111 标准工况网格")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--no-xlsx", action="store_true")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    if args.cases:
        from steering_sim.demo.batch import read_cases
        scenarios = read_cases(args.cases)
        stem = Path(args.cases).stem
    else:
        scenarios = default_scenarios(args.axle_mass)
        stem = "j1r2_full_cases"
    if args.limit > 0:
        scenarios = scenarios[:args.limit]

    started = time.perf_counter()
    context = build_context()
    rows = run_batch(context, scenarios,
                     on_progress=lambda fraction: print(
                         f"  {int(fraction * len(scenarios))}/{len(scenarios)}",
                         flush=True))
    path = write_csv(rows, out / f"{stem}.csv")
    if not args.no_xlsx:
        write_xlsx(rows, out / f"{stem}.xlsx")

    complete = sum(1 for r in rows if r.get("几何状态") not in (None, "SOLVER_EXCEPTION"))
    errors = sum(1 for r in rows if "错误" in r)
    missing = sum(1 for row in rows
                  if any(row.get(f"液压预测_{wheel}") is None for wheel in WHEEL_ORDER))
    status_counts: dict[str, int] = {}
    capability_ok: dict[str, int] = {}
    for row in rows:
        key = str(row.get("综合状态"))
        status_counts[key] = status_counts.get(key, 0) + 1
        for name in context.channel_names:
            field = f"作动能力_{name}"
            if row.get(field) == "OK":
                capability_ok[field] = capability_ok.get(field, 0) + 1
    summary = {
        "cases": len(rows),
        "structurally_complete": complete,
        "solver_errors": errors,
        "rows_missing_actuator_prediction": missing,
        "status_counts": status_counts,
        "capability_ok_by_channel": capability_ok,
        "elapsed_s": round(time.perf_counter() - started, 1),
        "mode": "FAST_BATCH_ESTIMATE",
        "hydraulic_model": context.parameters.tag,
        "path_steps": 24,
    }
    (out / f"{stem}_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("written:", path, "columns:", len(columns_of(rows)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
