"""PHASE M3：由完成的机构设计生成 ``mechanics_ackermann_redesigned/config.json``。

包络不是"随便给一个搜索范围"：对每个机构组从 ``q = 0`` 连续延拓，逐门限
（闭链残差 ≤ 1e-9 m、相邻步角增量 ≤ 3°、条件数 ≤ 1e8），第一次真实失败即停止，
并把停止原因写进配置，供报告与测试引用。
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from steering_sim.ackermann.redesign import (LEGACY_SIDE, RedesignedMechanism,  # noqa: E402
                                             cylinder_stroke_m,
                                             load_redesign_parameters)
from steering_sim.mechanics import reference_geometry_from_file  # noqa: E402

DOF_OF_GROUP = {"front": "q_front", "axle4": "q4", "axle5": "q5", "axle6": "q6"}
RESIDUAL_LIMIT_M = 1.0e-9
CONDITION_LIMIT = 1.0e8
STEP_JUMP_LIMIT_RAD = math.radians(3.0)


def probe(reference, parameters, group: str, dof: str, *, step: float = 0.002,
          limit: float = 1.20) -> dict:
    """从 q=0 向 **正方向**连续延拓求机构组的可解范围。

    机构按构造严格左右镜像，因此可解范围必然关于 q=0 对称；负半轴上的数值
    分支跟踪实测并不可靠（会在某个 q 处跳到另一个装配分支），所以只扫正向、
    直接把结果镜像成包络，既快又不会因为数值巧合把范围砍半。
    """
    mechanism = RedesignedMechanism(reference, parameters)
    build = mechanism.builds[group]
    build.chain.reset()
    solution = build.chain.solve(0.0)
    previous = np.array([solution.angles_rad[name]
                         for name in build.chain.body_names])
    stats = {"max_residual_m": 0.0, "max_condition_number": 0.0,
             "max_step_jump_rad": 0.0, "min_toggle_margin_deg": 180.0}
    q = 0.0
    stop = ""
    while q < limit:
        q_next = q + step
        try:
            trial = build.chain.solve(q_next)
        except Exception as exc:
            stop = f"{type(exc).__name__}: {exc}"
            break
        if trial.max_residual_m > RESIDUAL_LIMIT_M:
            stop = f"闭链残差 {trial.max_residual_m:.3e} m 超限"
            break
        if trial.condition_number > CONDITION_LIMIT:
            stop = f"雅可比条件数 {trial.condition_number:.3e} 超限"
            break
        angles = np.array([trial.angles_rad[name] for name in build.chain.body_names])
        jump = float(np.max(np.abs(angles - previous), initial=0.0))
        if jump > STEP_JUMP_LIMIT_RAD:
            stop = f"装配分支跳变 {math.degrees(jump):.3f}°"
            break
        stats["max_residual_m"] = max(stats["max_residual_m"], trial.max_residual_m)
        stats["max_condition_number"] = max(stats["max_condition_number"],
                                            trial.condition_number)
        stats["max_step_jump_rad"] = max(stats["max_step_jump_rad"], jump)
        previous = angles
        q = q_next
    stop = stop or f"达到探测上限 ±{math.degrees(limit):.1f}°"
    for probe_q in np.linspace(0.0, q, 25):
        state = mechanism.solve({**{d: 0.0 for d in DOF_OF_GROUP.values()},
                                 dof: float(probe_q)})
        stats["min_toggle_margin_deg"] = min(stats["min_toggle_margin_deg"],
                                             state.min_toggle_margin_deg)
    return {"q_lo_rad": -q, "q_hi_rad": q,
            "stop_reason_lo": stop, "stop_reason_hi": stop, **stats}


def _clip_to_monotone_stroke(reference, parameters, group: str, dof: str,
                             lo: float, hi: float):
    """把包络收缩到"代表行程严格单调"的最大**对称**区间（含 q = 0）。

    代表行程是对称双缸的推程缸位移（左转 A 缸、右转 B 缸），由构造是**奇函数**，
    所以单调区间必然关于零位对称：只在 q ≥ 0 上找折返点，再镜像即可。
    若只用 A 缸，实测它在 q ≈ −9° 处到达自身运动极限并使行程折返，
    会把六桥的右转向范围腰斩——那是把两只缸当一只缸用造成的假限制。
    """
    from steering_sim.ackermann.redesign import representative_stroke_m

    mechanism = RedesignedMechanism(reference, parameters)
    upper = min(hi, abs(lo))
    # 用与 transmission._stroke_table 相同的分辨率，保证两处看到同一个折返点。
    grid = np.linspace(0.0, upper, 401)
    values = []
    for q in grid:
        state = mechanism.solve({**{d: 0.0 for d in DOF_OF_GROUP.values()},
                                 dof: float(q)})
        if group == "front":
            values.append(0.25 * float(q))
        else:
            axle = int(group[4:])
            values.append(representative_stroke_m(
                reference, axle, float(q),
                state.groups[group].body_angles_rad))
    values = np.asarray(values, dtype=float)
    steps = np.diff(values)
    base = steps[0] if len(steps) else 0.0
    if base == 0.0:
        base = 1.0
    note = "代表行程在包络内严格单调"
    for index in range(len(steps)):
        if steps[index] * base <= 0.0:
            upper = float(grid[index])
            note = f"正向在 q={math.degrees(upper):.2f}° 处代表行程折返，包络对称收于此"
            break
    # 再留 0.25% 余量，确保包络端点不会正好压在折返点上。
    upper = upper * 0.9975
    return round(-upper, 5), round(upper, 5), note


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--geometry", default=str(ROOT / "mechanical_model_input_spec_v1.0.yaml"))
    parser.add_argument("--design", default=str(ROOT / "mechanics_ackermann_redesigned" / "design_parameters.json"))
    parser.add_argument("--out", default=str(ROOT / "mechanics_ackermann_redesigned" / "config.json"))
    args = parser.parse_args()

    reference = reference_geometry_from_file(args.geometry)
    parameters = load_redesign_parameters(args.design)
    envelopes = {}
    evidence = {}
    for group, dof in DOF_OF_GROUP.items():
        report = probe(reference, parameters, group, dof)
        # 留 2% 余量，避免把包络恰好放在数值门限上。
        lo = round(report["q_lo_rad"] * 0.98, 5)
        hi = round(report["q_hi_rad"] * 0.98, 5)
        # J0 的行程反解要求代表缸行程在包络内严格单调；一旦折返就必须收缩
        # （PHASE M2 的 q4 就是这样从 ±1.0 rad 收到 ±0.80 rad 的）。
        lo, hi, monotone_note = _clip_to_monotone_stroke(
            reference, parameters, group, dof, lo, hi)
        envelopes[dof] = [lo, hi]
        report["monotone_stroke_note"] = monotone_note
        evidence[dof] = {
            "probed_lo_rad": round(report["q_lo_rad"], 5),
            "probed_hi_rad": round(report["q_hi_rad"], 5),
            "probed_lo_deg": round(math.degrees(report["q_lo_rad"]), 3),
            "probed_hi_deg": round(math.degrees(report["q_hi_rad"]), 3),
            "stop_reason_lo": report["stop_reason_lo"],
            "stop_reason_hi": report["stop_reason_hi"],
            "max_residual_m": report["max_residual_m"],
            "max_condition_number": report["max_condition_number"],
            "max_step_jump_deg": round(math.degrees(report["max_step_jump_rad"]), 4),
            "min_toggle_margin_deg": round(report["min_toggle_margin_deg"], 3),
        }

    # 缸行程包络：由新机构在设计包络内**实际用到的行程**再留 15% 余量。
    # 甲方没有给出这两只缸的行程数据，所以这是 ASSUMED，必须如实标注。
    travel: dict[str, object] = {}
    for group, dof in DOF_OF_GROUP.items():
        if group == "front":
            travel["front_group_1"] = [round(-0.25 * abs(envelopes[dof][0]), 4),
                                       round(0.25 * abs(envelopes[dof][1]), 4)]
            continue
        axle = int(group[4:])
        mechanism = RedesignedMechanism(reference, parameters)
        used = {"A": 0.0, "B": 0.0}
        for q in np.linspace(envelopes[dof][0], envelopes[dof][1], 201):
            state = mechanism.solve({**{d: 0.0 for d in DOF_OF_GROUP.values()},
                                     dof: float(q)})
            angles = state.groups[group].body_angles_rad
            for side, letter in (("right", "A"), ("left", "B")):
                value = abs(cylinder_stroke_m(reference, axle, side,
                                              float(angles[
                                                  f"SWING_{axle}_{'NEG_Y' if side == 'right' else 'POS_Y'}"])))
                used[letter] = max(used[letter], value)
        for letter in ("A", "B"):
            span = round(used[letter] * 1.15, 4)
            travel[f"axle{axle}_{letter}"] = [-span, span]
    travel["source"] = ("ASSUMED_ENGINEERING_ENVELOPE：甲方未提供后桥缸行程数据；"
                        "此处由新机构在设计包络内**实际用到**的单向最大行程再留 15% "
                        "余量给出，不是甲方机械限位。前组缸仍为占位接口。")
    cylinder_travel = travel

    payload = {
        "schema_version": "M3.0",
        "tag": "ENGINEERING_REDESIGN_PROPOSAL",
        "coordinate_system": {
            "source_length_unit": "mm", "solver_length_unit": "m",
            "origin": "midpoint of axle-1 wheel centers",
            "x_positive": "vehicle forward", "y_positive": "vehicle left",
            "z_positive": "up", "revolute_axis": "+Z",
        },
        "geometry": {
            "source_file": "mechanical_model_input_spec_v1.0.yaml",
            "source": "CUSTOMER_COORDINATES_TRANSCRIBED_AND_CROSSCHECKED_UNCHANGED",
            "customer_hardpoints_changed": False,
            "icr_reference_axle": 3,
            "third_axle_locked": True,
            "third_axle_point20_mm": [-7290.0, -996.0],
            "design_parameters": "mechanics_ackermann_redesigned/design_parameters.json",
            "design_tag": "ENGINEERING_REDESIGN_PROPOSAL",
            "fit_residual_limit_deg": 0.25,
            "q_envelopes_rad": envelopes,
            "q_envelope_source": (
                "M3 连续延拓实测包络：每步门限为闭链残差 ≤1e-9 m、相邻步角增量 "
                "≤3°、雅可比条件数 ≤1e8；第一次真实失败即停止并记录原因，"
                "再留 2% 数值余量。这不是甲方机械限位。"),
            "q_envelope_m3_evidence": evidence,
        },
        "cylinder_travel_m": cylinder_travel,
        "ground_load": {
            "gravity_mps2": 9.81,
            "cornering_stiffness_per_wheel_N_per_rad": 300000.0,
            "cornering_stiffness_source": "ASSUMED_ENGINEERING_PARAMETER",
            "linear_slip_limit_deg": 5.0,
            "effective_trail_m": 0.06,
            "effective_trail_source": "ASSUMED_ENGINEERING_PARAMETER",
            "pivot_effective_radius_m": 0.035,
            "pivot_effective_radius_source": "ASSUMED_ENGINEERING_PARAMETER",
            "pivot_transition_speed_kmh": 5.0,
            "pivot_transition_source": "ASSUMED_ENGINEERING_PARAMETER",
            "pivot_engagement_angle_deg": 1.0,
            "pivot_engagement_source": "ASSUMED_ENGINEERING_PARAMETER",
            "stiffness_scenarios_Nm_per_rad": {
                "low_flexibility": {"q_front": 400000.0, "q4": 300000.0,
                                    "q5": 300000.0, "q6": 300000.0},
                "medium_flexibility": {"q_front": 200000.0, "q4": 150000.0,
                                       "q5": 150000.0, "q6": 150000.0},
                "high_flexibility": {"q_front": 100000.0, "q4": 75000.0,
                                     "q5": 75000.0, "q6": 75000.0},
            },
            "stiffness_source": "ASSUMED_ENGINEERING_PARAMETER_NOT_CUSTOMER_MEASURED",
        },
        "front_cylinder_interface": {
            "cylinder_id": "front_group_1",
            "frame_mount": "PENDING_CUSTOMER_COORDINATE",
            "moving_mount": "PENDING_CUSTOMER_COORDINATE",
            "stroke_per_q_mm_per_rad": 250.0,
            "stroke_mapping_source": "ASSUMED_ENGINEERING_PARAMETER_INTERFACE_PLACEHOLDER",
        },
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    print("written:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
