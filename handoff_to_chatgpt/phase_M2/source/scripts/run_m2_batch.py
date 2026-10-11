"""PHASE M2：生成全工况表、校核证据与输入模板。

输出到 ``outputs/m2/``：

* ``linkage_audit.json``      四杆装配分支与可解范围审计
* ``envelope_check.json``     连续延拓包络校核（含停止原因）
* ``ideal_ackermann_check.json``  ±30° 理想阿克曼角独立校核
* ``full_cases.csv``          3111 组全工况表
* ``full_cases.xlsx``         XLSX（默认抽样 1000 行，可 --xlsx-all 全量）
* ``case_template.csv/.xlsx`` 甲方输入模板
* ``m2_summary.json``         汇总
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from steering_sim.ackermann.cases import (build_case_grid, grid_size, run_batch,
                                          write_csv, write_template, write_xlsx)
from steering_sim.ackermann.equivalent import build_equivalent_map
from steering_sim.ackermann.ideal import CHECK_ANGLES_DEG, ideal_ackermann
from steering_sim.ackermann.linkage import (audit_linkage, build_four_bars,
                                            verify_envelopes)
from steering_sim.mechanics import reference_geometry_from_file

SPEC = ROOT / "mechanical_model_input_spec_v1.0.yaml"
M1_CONFIG = ROOT / "mechanics_ackermann_v2" / "config.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(ROOT / "outputs" / "m2"))
    parser.add_argument("--xlsx-all", action="store_true",
                        help="XLSX 写出全部 3111 行（默认抽样 1000 行）")
    parser.add_argument("--skip-batch", action="store_true")
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    print("加载甲方参考几何与 M1 模型 …")
    reference = reference_geometry_from_file(SPEC)
    from mechanics_ackermann_v2.model import PhaseM1Model
    model = PhaseM1Model(SPEC, M1_CONFIG)
    centers = {f"axle{a}_{s}": tuple(map(float, reference.bodies[f"WHEEL_{a}_{l}"].pivot))
               for a in range(1, 7)
               for s, l in (("left", "POS_Y"), ("right", "NEG_Y"))}

    print("1/4 四杆装配分支与可解范围审计 …")
    audit = audit_linkage(reference, limit_deg=20.0, step_deg=0.05)
    (output / "linkage_audit.json").write_text(
        json.dumps(audit.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    print("2/4 机构坐标真实可解范围（连续延拓）…")
    envelopes = verify_envelopes(reference, step_rad=0.002, limit_rad=1.0)
    (output / "envelope_check.json").write_text(
        json.dumps({dof: item.to_dict() for dof, item in envelopes.items()},
                   indent=2, ensure_ascii=False), encoding="utf-8")

    print("3/4 理想阿克曼角独立校核 (±30°) …")
    checks = []
    worst = 0.0
    for target in CHECK_ANGLES_DEG:
        mine = ideal_ackermann(target, centers)
        theirs = {k: math.degrees(v)
                  for k, v in model.ideal_ackermann(target)[5].items()}
        gap = max(abs(mine.angles_deg[w] - theirs[w]) for w in mine.angles_deg)
        worst = max(worst, gap)
        checks.append({
            "target_deg": target,
            "turn_radius_m": mine.turn_radius_m,
            "x_icr_m": mine.x_icr_m, "y_icr_m": mine.y_icr_m,
            "direction_flags": list(mine.direction_flags()),
            "max_abs_difference_vs_m1_deg": gap,
            "angles_deg": {k: round(v, 9) for k, v in mine.angles_deg.items()},
        })
    (output / "ideal_ackermann_check.json").write_text(
        json.dumps({"check_angles_deg": list(CHECK_ANGLES_DEG),
                    "worst_abs_difference_vs_m1_deg": worst,
                    "cases": checks}, indent=2, ensure_ascii=False),
        encoding="utf-8")
    print(f"      独立实现与 M1 最大差 {worst:.3e}°")

    base, total = grid_size()
    summary: dict = {
        "grid_base": base, "grid_total": total,
        "ideal_ackermann_worst_difference_deg": worst,
        "envelope": {dof: item.to_dict() for dof, item in envelopes.items()},
    }
    if args.skip_batch:
        (output / "m2_summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        print("已跳过批量计算。")
        return 0

    print(f"4/4 全工况表（{total} 组）…")
    four_bars = build_four_bars(reference)
    equivalent = build_equivalent_map(reference, four_bars,
                                      need={"channel_rear_2": True,
                                            "channel_rear_3": True})
    specs = build_case_grid()
    started = time.perf_counter()
    rows, batch = run_batch(
        model, equivalent, specs, with_loaded=True,
        progress=lambda done, whole: print(f"      {done}/{whole}", end="\r",
                                           flush=True))
    print()
    elapsed = time.perf_counter() - started
    write_csv(rows, output / "full_cases.csv")
    write_xlsx(rows, output / "full_cases.xlsx",
               limit=None if args.xlsx_all else 1000)
    write_template(output / "case_template.csv", limit=200)

    summary["batch"] = batch.to_dict()
    summary["batch_seconds"] = round(elapsed, 2)
    summary["equivalent_channels"] = {
        key: channel.to_dict() for key, channel in equivalent.items()}
    (output / "m2_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8")

    print(f"完成，用时 {elapsed:.1f} s")
    print(f"  CSV  : {output / 'full_cases.csv'}")
    print(f"  XLSX : {output / 'full_cases.xlsx'}")
    print(f"  模板 : {output / 'case_template.csv'} / .xlsx")
    for status, count in batch.status_counts.items():
        print(f"  {status:32s} {count:6d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
