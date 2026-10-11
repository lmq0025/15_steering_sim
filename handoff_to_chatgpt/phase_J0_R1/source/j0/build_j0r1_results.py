"""汇总 PHASE J0-R1 结果，生成 `phase_J0_R1_results.json` 与最终状态块。

只读取已经跑出的产物，不重新仿真：
  outputs/j0_r1/j0_summary.json          四工况（含 M1 地面负载）
  outputs/j0_r1_noload/j0_summary.json   任务书第 7 节测试 3（关闭地面负载）
  outputs/j0/diagnostics/j0_diagnostics.json  被控对象表征（F1/F2 证据）
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # 写到 outputs/ 下（而不是 handoff 目录），因为打包脚本会先清空交付目录。
    parser.add_argument("--output", default=str(ROOT / "outputs" / "j0_r1"))
    parser.add_argument("--pytest-passed", type=int, default=None)
    args = parser.parse_args()

    cases = _load(ROOT / "outputs" / "j0_r1" / "j0_summary.json")
    noload = _load(ROOT / "outputs" / "j0_r1_noload" / "j0_summary.json")
    diagnostics = _load(ROOT / "outputs" / "j0" / "diagnostics" / "j0_diagnostics.json")

    by_id = {item["case_id"]: item for item in cases.get("cases", [])}
    noload_by_id = {item["case_id"]: item for item in noload.get("cases", [])}
    plant = {item["channel"]: item for item in diagnostics.get("plant_characterisation", [])}
    authority = {item["channel"]: item for item in diagnostics.get("channel_authority", [])}

    def case_block(case_id: str) -> dict:
        item = by_id.get(case_id, {})
        if not item:
            return {"case_id": case_id, "status": "MISSING"}
        return {
            "case_id": case_id,
            "target_outer_angle_deg": item.get("target_outer_angle_deg"),
            "speed_kmh": item.get("speed_kmh"),
            "duration_s": item.get("duration_s"),
            "status": item.get("status"),
            "completed": item.get("completed"),
            "failure_reason": item.get("failure_reason"),
            # 单位约定：所有 *_mm 字段一律为毫米，所有 *_m 字段一律为米。
            # 旧版本的 final_stroke_mm 实际装的是 stroke_range_m（单位 m 的区间），
            # 属于命名与单位双错；此处拆成两个语义正确的字段。
            "target_x_ref_mm": {k: v * 1e3 for k, v in item.get("target_x_ref_m", {}).items()},
            "final_stroke_mm": {k: v * 1e3
                                for k, v in item.get("final_stroke_m", {}).items()},
            "final_stroke_error_mm": {k: v * 1e3
                                      for k, v in item.get("final_stroke_error_m", {}).items()},
            "stroke_range_mm": {k: [bounds[0] * 1e3, bounds[1] * 1e3]
                                for k, bounds in item.get("stroke_range_m", {}).items()},
            "steady_stroke_error_mm": {k: v * 1e3
                                       for k, v in item.get("steady_stroke_error_m", {}).items()},
            "stroke_tracking_fraction": item.get("stroke_tracking_fraction"),
            "steady_wheel_angle_error_vs_mechanism_deg":
                item.get("steady_wheel_angle_error_vs_mechanism_deg"),
            "max_steady_wheel_angle_error_vs_mechanism_deg":
                item.get("max_steady_wheel_angle_error_vs_mechanism_deg"),
            "max_steady_wheel_angle_error_vs_ideal_deg":
                item.get("max_steady_wheel_angle_error_vs_ideal_deg"),
            "max_mechanism_ackermann_error_deg": item.get("max_mechanism_ackermann_error_deg"),
            "final_wheel_angle_deg": item.get("final_wheel_angle_deg"),
            "target_mechanism_wheel_angle_deg": item.get("target_mechanism_wheel_angle_deg"),
            "max_pressure_mpa_g": item.get("max_pressure_mpa_g"),
            "max_abs_velocity_m_s": item.get("max_abs_velocity_m_s"),
            "max_abs_stroke_mm": (item.get("max_abs_stroke_m") or 0.0) * 1e3,
            "max_link_residual_m": item.get("max_link_residual_m"),
            "third_axle_max_abs_deg": item.get("third_axle_max_abs_deg"),
            "virtual_work_residual_max_abs": item.get("virtual_work_residual_max_abs"),
            "control_saturation_fraction": item.get("control_saturation_fraction"),
            "anti_windup_active_fraction": item.get("anti_windup_active_fraction"),
            "pump_capacity_warnings": item.get("pump_capacity_warnings"),
            "diagnostic_damping_n_s_per_m": item.get("diagnostic_damping_n_s_per_m"),
            "road_load_scale": item.get("road_load_scale"),
            "status_notes": item.get("status_notes"),
        }

    status_map = {case_id: by_id.get(case_id, {}).get("status", "MISSING")
                  for case_id in ("J0-01", "J0-02", "J0-03", "J0-04")}
    pass_fail = lambda value: "PASS" if value == "PASS" else (
        "CONDITIONAL" if value == "CONDITIONAL" else "FAIL")

    front_force = authority.get("channel_front", {}).get("force_window_n", [None, None])
    front_available = (min(abs(front_force[0]), abs(front_force[1]))
                       if front_force[0] is not None else None)
    damping_ok = all(item["d_force_d_velocity_n_s_per_m"] < 0.0 for item in plant.values())
    stiffness_ok = all(item["d_force_d_displacement_n_per_m"] < 0.0 for item in plant.values())

    payload = {
        "phase": "J0-R1",
        "scope": "修复 F1（力/容积符号不一致）与 F2（前桥无有效静态驱动力），恢复电液机械联合仿真",
        "artificial_diagnostic_damping_used": False,
        "f1_force_volume_consistency": {
            "status": "PASS" if (damping_ok and stiffness_ok) else "FAIL",
            "force_definition": "F_hyd = A_b*p_b - A_a*p_a",
            "plant_characterisation": {
                name: {
                    "d_force_d_velocity_n_s_per_m": item["d_force_d_velocity_n_s_per_m"],
                    "d_force_d_displacement_n_per_m": item["d_force_d_displacement_n_per_m"],
                    "force_offset_n": item["force_offset_n"],
                    "flags": item["flags"],
                } for name, item in plant.items()},
        },
        "f2_front_bidirectional_actuation": {
            "status": "PASS" if (front_available or 0) > 4.5e3 else "FAIL",
            "fix": "前阀工作口换位（IR V3 证据）+ 删除 A 腔硬置零特判 + 撤回 actuator002 人工内泄漏",
            "authority": authority.get("channel_front", {}),
            "required_front_load_n": 6.2e3,
            "note": "6.2 kN 来自 M1 工程假设道路负载，不是实车测量值",
        },
        "f3_redundant_valves": "DEFERRED",
        "cases": [case_block(case_id)
                  for case_id in ("J0-01", "J0-02", "J0-03", "J0-04")],
        "test3_no_road_load": {
            case_id: {
                "status": item.get("status"),
                "completed": item.get("completed"),
                "road_load_scale": item.get("road_load_scale"),
                "stroke_tracking_fraction": item.get("stroke_tracking_fraction"),
                "final_wheel_angle_deg": item.get("final_wheel_angle_deg"),
            } for case_id, item in noload_by_id.items()},
        "pytest_passed": args.pytest_passed,
        "final_status": {
            "STRAIGHT_0_DEG": pass_fail(status_map["J0-01"]),
            "LEFT_PLUS_2_DEG": pass_fail(status_map["J0-02"]),
            "RIGHT_MINUS_2_DEG": pass_fail(status_map["J0-03"]),
            "LEFT_PLUS_5_DEG": pass_fail(status_map["J0-04"]),
        },
    }

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "phase_J0_R1_results.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps(payload["final_status"], indent=2, ensure_ascii=False))
    print(f"wrote {output / 'phase_J0_R1_results.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
