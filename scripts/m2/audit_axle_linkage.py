"""PHASE M2 审计 1：五、六桥转向机构的反号归因。

对每一桥，把"摆臂—边拉杆—车轮"看成一个四杆机构：

* 机架 (ground)  —— 摆臂铰点 → 车轮铰点
* 曲柄 (crank)   —— 摆臂铰点 → 摆臂上的边拉杆点
* 连杆 (coupler) —— 边拉杆
* 摇杆 (rocker)  —— 车轮铰点 → 车轮上的边拉杆点

输出每个机构在 q=0 的构件长度、连杆—摇杆相对角（死点判据）、
以及两侧的传动比符号。同时枚举闭链的全部装配分支。

只读，不修改任何甲方坐标。
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from steering_sim.mechanics import (SixAxleSteeringKinematics,
                                    reference_geometry_from_file)


def _world(reference, body: str, local: tuple[float, float]) -> np.ndarray:
    b = reference.bodies[body]
    return np.asarray(b.pivot, dtype=float) + np.asarray(local, dtype=float)


def fourbar(reference, axle: int, side: str) -> dict:
    """返回该侧四杆的构件向量与角度（单位 m / deg）。"""
    swing = f"SWING_{axle}_{side}"
    wheel = f"WHEEL_{axle}_{side}"
    tag = "MIRROR" if side == "POS_Y" else "SRC"
    s_pivot = np.asarray(reference.bodies[swing].pivot, dtype=float)
    w_pivot = np.asarray(reference.bodies[wheel].pivot, dtype=float)
    # 摆臂上的边拉杆点（该桥第 2 个自定义点）与车轮上的边拉杆点
    side_point = None
    for pid in reference.bodies[swing].local_hardpoints:
        if pid.endswith(tag) and "P" in pid:
            pass
    # 直接用量纲：边拉杆是该桥上唯一一个连接 SWING 与 WHEEL 的杆
    linkage = None
    for name, link in reference.links.items():
        a_body, a_pt = link.endpoint_a
        b_body, b_pt = link.endpoint_b
        if a_body == swing and b_body == wheel:
            linkage = (a_pt, b_pt, link.reference_length)
            break
        if a_body == wheel and b_body == swing:
            linkage = (b_pt, a_pt, link.reference_length)
            break
    if linkage is None:
        raise KeyError(f"{axle}-{side}: no side tie rod")
    s_pt_id, w_pt_id, length = linkage
    s_pt = _world(reference, swing, reference.bodies[swing].local_hardpoints[s_pt_id])
    w_pt = _world(reference, wheel, reference.bodies[wheel].local_hardpoints[w_pt_id])

    ground = w_pivot - s_pivot
    crank = s_pt - s_pivot
    coupler = w_pt - s_pt
    rocker = w_pt - w_pivot

    def ang(v):
        return math.degrees(math.atan2(v[1], v[0]))

    def norm(v):
        return float(np.linalg.norm(v))

    relative = (ang(coupler) - ang(rocker) + 180.0) % 360.0 - 180.0
    return {
        "axle": axle, "side": side,
        "ground_m": norm(ground), "crank_m": norm(crank),
        "coupler_m": norm(coupler), "rocker_m": norm(rocker),
        "ground_deg": ang(ground), "crank_deg": ang(crank),
        "coupler_deg": ang(coupler), "rocker_deg": ang(rocker),
        "coupler_rocker_relative_deg": relative,
        "min_coupler_rocker_deg": min(abs(relative), 180.0 - abs(relative)),
        "s_pivot": s_pivot.tolist(), "w_pivot": w_pivot.tolist(),
        "s_point": s_pt.tolist(), "w_point": w_pt.tolist(),
    }


def transmission(reference, axle: int, side: str, q_deg: float = 0.5) -> float:
    """用一维连续延拓数值求 d(车轮角)/d(摆臂角)。"""
    swing = f"SWING_{axle}_{side}"
    wheel = f"WHEEL_{axle}_{side}"
    dt = math.radians(q_deg)
    out = []
    for delta in (-dt, 0.0, dt):
        kin = SixAxleSteeringKinematics(reference)
        q = np.zeros(5)
        q[{1: 0, 2: 0, 3: 1, 4: 2, 5: 3, 6: 4}[axle]] = delta
        sol = None
        for factor in np.linspace(0.0, 1.0, 61):
            sol = kin.solve(q * factor)
        out.append((math.degrees(sol.swing_angles[swing]),
                    math.degrees(sol.wheel_angles[wheel])))
    (s0, w0), (s1, w1) = out[0], out[1]
    (s2, w2) = out[2]
    ds = (s2 - s0) / 2.0
    dw = (w2 - w0) / 2.0
    return dw / ds if abs(ds) > 1e-12 else float("nan")


def branches(reference, axle: int, q_deg: float) -> list[dict]:
    """枚举该桥闭链的全部装配分支。"""
    kin = SixAxleSteeringKinematics(reference)
    group = next(g for g in kin._groups if g.name == f"AXLE_{axle}")
    q = math.radians(q_deg)
    found: dict[tuple, float] = {}
    seeds = [np.zeros(4)]
    for sp in np.linspace(-0.5, 0.5, 13):
        for wn in np.linspace(-0.6, 0.6, 13):
            seeds.append([sp + q, sp - q, wn, wn])
            seeds.append([sp + q, sp - q, wn, -wn])
            seeds.append([sp + q, sp - q, -wn, wn])
    from scipy.optimize import least_squares
    for seed in seeds:
        res = least_squares(lambda x: group.residual_vector(q, np.asarray(x, float)),
                            np.asarray(seed, float), xtol=1e-14, ftol=1e-14,
                            gtol=1e-14, max_nfev=400)
        r = float(np.max(np.abs(group.residual_vector(q, res.x))))
        if r < 1e-10:
            found.setdefault(tuple(np.round(res.x, 7)), r)
    rows = []
    for key, r in found.items():
        s_neg, s_pos, w_neg, w_pos = np.degrees(key)
        rows.append({
            "swing_left_deg": float(s_pos), "swing_right_deg": float(s_neg),
            "wheel_left_deg": float(w_pos), "wheel_right_deg": float(w_neg),
            "same_sign": bool(np.sign(w_pos) == np.sign(w_neg)),
            "max_residual_m": r,
        })
    return sorted(rows, key=lambda item: abs(item["wheel_left_deg"]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(ROOT / "outputs" / "m2" / "axle_linkage_audit.json"))
    args = parser.parse_args()
    reference = reference_geometry_from_file(
        ROOT / "mechanical_model_input_spec_v1.0.yaml")

    payload = {"axles": [], "branches": {}}
    print(f"{'桥':>3} {'侧':>6} {'机架':>8} {'曲柄':>8} {'连杆':>8} {'摇杆':>8} "
          f"{'连杆-摇杆相对角':>16} {'距死点':>8} {'传动比 dw/ds':>12}")
    for axle in (1, 2, 4, 5, 6):
        for side in ("POS_Y", "NEG_Y"):
            item = fourbar(reference, axle, side)
            item["transmission_dw_ds"] = transmission(reference, axle, side)
            payload["axles"].append(item)
            print(f"{axle:>3} {side:>6} {item['ground_m']:>8.4f} {item['crank_m']:>8.4f} "
                  f"{item['coupler_m']:>8.4f} {item['rocker_m']:>8.4f} "
                  f"{item['coupler_rocker_relative_deg']:>16.3f} "
                  f"{item['min_coupler_rocker_deg']:>8.3f} "
                  f"{item['transmission_dw_ds']:>12.4f}")
        print("-" * 92)

    for axle in (4, 5, 6):
        for q_deg in (2.0, 5.0):
            rows = branches(reference, axle, q_deg)
            payload["branches"][f"axle{axle}_q{q_deg}"] = rows
            print(f"\nAXLE {axle} q={q_deg:+.1f}°  装配分支 {len(rows)} 个"
                  f"（同向分支 {sum(1 for r in rows if r['same_sign'])} 个）")
            for row in rows:
                print(f"    摆臂L={row['swing_left_deg']:+7.3f} 摆臂R={row['swing_right_deg']:+7.3f} "
                      f"车轮L={row['wheel_left_deg']:+8.3f} 车轮R={row['wheel_right_deg']:+8.3f} "
                      f"{'同向' if row['same_sign'] else '反号'}")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
