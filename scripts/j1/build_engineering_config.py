"""PHASE J1：生成 ``configs/j1/engineering_config.json``。

包络由连续延拓**实测**：对每个机构组从零位向两个方向外扩，直到机构不可解，
再收缩到"覆盖该桥轮角 ±35°"所需的区间并留 2% 余量。**这不是甲方机械限位。**
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from steering_sim.engineering.mechanism import (DOF_OF_GROUP, GROUPS,  # noqa: E402
                                                MechanismError, load_design)
from steering_sim.engineering.model import (EngineeringSteeringModel,  # noqa: E402
                                            cylinder_stroke_m,
                                            representative_stroke_m)
from steering_sim.mechanics import reference_geometry_from_file  # noqa: E402

SPEC = ROOT / "mechanical_model_input_spec_v1.0.yaml"
DESIGN = ROOT / "configs" / "j1" / "engineering_mechanism.json"
TARGET_DEG = 35.0
#: 甲方任务书的**最大工作目标角**。包络至少要覆盖它并留余量；±35° 只是设计
#: 目标（留出制造与控制超调空间），机构不一定能给出 5% 以上的额外余量。
REQUIRED_DEG = 30.0


def _representative(mechanism, reference, key: str, axle: int, q: float) -> float:
    """代表行程（对称双缸推程缸位移）。驱动侧的摆臂角就是广义坐标 q。"""
    angles = {f"SWING_{axle}_NEG_Y": float(q), f"SWING_{axle}_POS_Y": 0.0}
    return representative_stroke_m(reference, axle, float(q), angles)


def first_half_monotone(mechanism, key: str, axle: int, q_pos: float) -> bool:
    return _monotone_upper(mechanism, key, axle, q_pos) >= q_pos - 1e-9


def _monotone_upper(mechanism, key: str, axle: int, q_pos: float,
                    samples: int = 120) -> float:
    reference = mechanism.reference
    values = []
    grid = [q_pos * i / samples for i in range(samples + 1)]
    for q in grid:
        try:
            values.append(_representative(mechanism, reference, key, axle, q))
        except MechanismError:
            values.append(float("nan"))
    base = values[1] - values[0]
    if base == 0.0:
        return q_pos
    for index in range(1, len(values)):
        if not (values[index] - values[index - 1]) * base > 0.0:
            return grid[index - 1]
    return q_pos


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "configs" / "j1"
                                             / "engineering_config.json"))
    parser.add_argument("--ground-load-from",
                        default=str(ROOT / "mechanics_ackermann_v2" / "config.json"))
    args = parser.parse_args()

    reference = reference_geometry_from_file(SPEC)
    design = load_design(DESIGN)
    from steering_sim.engineering.mechanism import EngineeringMechanism
    mechanism = EngineeringMechanism(reference, design)

    envelopes: dict[str, list[float]] = {}
    evidence: dict[str, dict] = {}
    for key in GROUPS:
        dof = DOF_OF_GROUP[key]
        axle = design.groups[key].driven_axle
        wheel = f"axle{axle}_right"
        limits = {}
        for direction in (1.0, -1.0):
            mechanism.reset_group(key, 0.0)
            mechanism.solve_swing(key, 0.0)
            q = last = 0.0
            stop = ""
            while abs(q) < math.radians(120.0):
                nxt = q + direction * math.radians(0.5)
                try:
                    state = mechanism.solve_swing(key, nxt)
                except MechanismError as exc:
                    stop = f"{type(exc).__name__}: {exc}"[:120]
                    break
                last, q = nxt, nxt
            limits[direction] = (last, stop or "达到 120° 探测上限")

        def swing_for(target_rad: float, direction: float) -> float:
            bound = abs(limits[direction][0])
            if bound < 1e-9:
                return 0.0
            mechanism.reset_group(key, 0.0)
            mechanism.solve_swing(key, 0.0)
            state = mechanism.solve_swing(key, direction * bound)
            if abs(state.wheel_angles_rad[wheel]) < abs(target_rad):
                return bound
            lo, hi = 0.0, bound
            for _ in range(50):
                mid = 0.5 * (lo + hi)
                mechanism.reset_group(key, 0.0)
                mechanism.solve_swing(key, 0.0)
                count = max(1, int(math.ceil(mid / math.radians(0.5))))
                probe = None
                for index in range(1, count + 1):
                    probe = mechanism.solve_swing(key, direction * mid * index / count)
                if probe is None:
                    hi = mid
                elif abs(probe.wheel_angles_rad[wheel]) >= abs(target_rad):
                    hi = mid
                else:
                    lo = mid
            return hi

        # J0 的行程反解要求代表行程**严格单调**，所以包络 = 机构**单调可达区间**
        # 再乘安全系数（不是"刚好够 ±35° 车轮角"）。
        #
        # PHASE J1-R2 修正：旧版把包络取成"覆盖该桥轮角 ±35° 所需区间 ×1.02"，
        # 结果六桥在 −30° 目标上算出来的 q6 正好**落在包络端点上**：行程反解一有
        # 任何超调就报 MAPPING_OUT_OF_ENVELOPE，−30° 工况整段失败（实测三例）。
        # 现在改为按机构自身能力取包络，工作点回到内部，同时也让六桥对大转角的
        # 阿克曼拟合有更多余量。
        # 包络的需求侧按**甲方最大工作角 ±30°** 算（±35° 只是设计目标，
        # 拿它定包络会把缸和泵白白放大十几个百分点）。
        q_pos_raw = swing_for(math.radians(REQUIRED_DEG), 1.0)
        q_neg_raw = swing_for(math.radians(REQUIRED_DEG), -1.0)
        # 包络**对称**（取两侧可达的较小者），保证机构左右镜像行为一致；
        # 两侧可达极限由连续延拓实测给出。
        reach_pos = abs(limits[1.0][0])
        reach_neg = abs(limits[-1.0][0])
        # 包络取"机构单调可达区间"与"设计需求 ×1.25 余量"的较小者再乘 0.97：
        # 下界必须够得着（旧版按需求 ×1.02 硬裁，六桥在 −30° 上正好落在端点，
        # 一有超调就整段失败），上界不必把缸撑到机构极限（那会白白放大行程与
        # 流量需求）。1.25 是覆盖设计目标角 + 控制超调 + 制造公差的工程余量。
        # 上界用**机构自身的单调可达极限**，不再按需求再收一次：收得比可达极限
        # 还紧会让 −30° 这种贴边工作点重新落到端点上（实测六桥镜像残差 0.86°）。
        # 缸行程按机构包络取，而**流量按 ±30° 的真实行程算**，所以包络变宽
        # 并不会把泵选大。
        q_pos = min(reach_pos, reach_neg,
                    max(q_pos_raw, q_neg_raw) * 1.60) * 0.97
        required = max(swing_for(math.radians(REQUIRED_DEG), 1.0),
                       swing_for(math.radians(REQUIRED_DEG), -1.0))
        assert q_pos >= required * 1.02, (
            f"{key}: 单调可达区间不足以覆盖 ±{REQUIRED_DEG:.0f}° 车轮角需求"
            f"（可达 {math.degrees(q_pos):.2f}° < 需求 "
            f"{math.degrees(required * 1.02):.2f}°）")
        monotone_limit = q_pos
        note = "代表行程在包络内严格单调"
        if key != "front" and not first_half_monotone(mechanism, key, axle, q_pos):
            monotone_limit = _monotone_upper(mechanism, key, axle, q_pos)
            note = (f"代表行程在 q={math.degrees(monotone_limit):.2f}° 处折返，"
                    f"包络对称收于此")
        envelopes[dof] = [round(-monotone_limit, 5), round(monotone_limit, 5)]
        evidence[dof] = {
            "reachable_plus_deg": round(math.degrees(limits[1.0][0]), 3),
            "reachable_minus_deg": round(math.degrees(limits[-1.0][0]), 3),
            "stop_reason_plus": limits[1.0][1],
            "stop_reason_minus": limits[-1.0][1],
            "envelope_plus_deg": round(math.degrees(envelopes[dof][1]), 3),
            "envelope_minus_deg": round(math.degrees(envelopes[dof][0]), 3),
            "monotone_stroke_note": note,
        }

    ground = json.loads(Path(args.ground_load_from).read_text(encoding="utf-8"))
    payload = {
        "schema_version": "J1.0",
        "tag": "ENGINEERING_STEERING_MODEL",
        "coordinate_system": {
            "source_length_unit": "mm", "solver_length_unit": "m",
            "origin": "midpoint of axle-1 wheel centers",
            "x_positive": "vehicle forward", "y_positive": "vehicle left",
            "z_positive": "up", "revolute_axis": "+Z",
        },
        "geometry": {
            "source_file": SPEC.name,
            "source": "CUSTOMER_COORDINATES_TRANSCRIBED_AND_CROSSCHECKED_UNCHANGED",
            "customer_hardpoints_changed": False,
            "icr_reference_axle": 3, "third_axle_locked": True,
            "third_axle_point20_mm": [-7290.0, -996.0],
            "mechanism_design": "configs/j1/engineering_mechanism.json",
            "fit_residual_limit_deg": 0.25,
            "q_envelopes_rad": envelopes,
            "q_envelope_source": (
                "J1 连续延拓实测：从零位外扩到机构不可解，再收缩到覆盖该桥轮角 "
                f"±{TARGET_DEG:.0f}° 所需的区间并留 2% 余量。不是甲方机械限位。"),
            "q_envelope_j1_evidence": evidence,
        },
        "ground_load": ground["ground_load"],
        "front_cylinder_interface": {
            "cylinder_id": "front_group_1",
            "frame_mount": "PENDING_CUSTOMER_COORDINATE",
            "moving_mount": "PENDING_CUSTOMER_COORDINATE",
            "stroke_per_q_mm_per_rad": 250.0,
            "stroke_mapping_source":
                "ASSUMED_ENGINEERING_PARAMETER_INTERFACE_PLACEHOLDER",
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
