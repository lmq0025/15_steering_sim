"""PHASE M3：优化设计机构与甲方原始机构的对照图。

每个后桥一张，两栏：

* 左：机构平面布置（零位 + 正负转向三个构型叠加），甲方原始硬点用空心圆，
  新增工程点用实心三角；
* 右：同桥左右轮转角随机构坐标的变化，优化机构 vs 甲方原始机构。

**图不会为了好看改数值**：纵轴范围由真实数据决定，反号区间原样画出。
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

SPEC = ROOT / "mechanical_model_input_spec_v1.0.yaml"
M1_CONFIG = ROOT / "mechanics_ackermann_v2" / "config.json"
REDESIGN_CONFIG = ROOT / "mechanics_ackermann_redesigned" / "config.json"
DESIGN_JSON = ROOT / "mechanics_ackermann_redesigned" / "design_parameters.json"

LEGACY = {"left": "POS_Y", "right": "NEG_Y"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "outputs" / "m3" / "figures"))
    parser.add_argument("--axles", default="4,5,6")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    import matplotlib
    matplotlib.use("Agg")
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg

    from steering_sim.j0_coupling.reporting import configure_chinese_font
    from steering_sim.mechanics import reference_geometry_from_file
    from steering_sim.ackermann.redesign import (DOF_OF_GROUP,
                                                 solve_chain_continuation)
    from mechanics_ackermann_redesigned.model import RedesignedAckermannModel
    from mechanics_ackermann_v2.model import PhaseM1Model

    configure_chinese_font()
    reference = reference_geometry_from_file(SPEC)
    new_model = RedesignedAckermannModel(SPEC, REDESIGN_CONFIG, DESIGN_JSON)
    old_model = PhaseM1Model(SPEC, M1_CONFIG)

    for axle in [int(v) for v in args.axles.split(",")]:
        group = f"axle{axle}"
        dof = DOF_OF_GROUP[group]
        build = new_model.mechanism.builds[group]
        lo, hi = new_model.q_envelopes[dof]
        figure = Figure(figsize=(14, 6.2))
        FigureCanvasAgg(figure)
        left = figure.add_subplot(1, 2, 1)
        right = figure.add_subplot(1, 2, 2)

        # ---- 左：机构布置（三个构型叠加）
        for q, color, label in ((0.0, "#333333", "零位"),
                                (hi * 0.75, "#1b5e20", "正转向"),
                                (lo * 0.75, "#b00020", "负转向")):
            solution = solve_chain_continuation(build.chain, float(q))
            angles = solution.angles_rad
            for name, (end_a, end_b) in build.links.items():
                body_a, point_a = end_a
                body_b, point_b = end_b
                pa = build.chain.bodies[build.chain.body_index[body_a]].world_point(
                    point_a, angles[body_a])
                pb = build.chain.bodies[build.chain.body_index[body_b]].world_point(
                    point_b, angles[body_b])
                left.plot([pa[0], pb[0]], [pa[1], pb[1]], color=color, linewidth=1.4,
                          alpha=0.85, label=label if name.startswith("DRAG_R") else None)
            for name in build.chain.body_names:
                body = build.chain.bodies[build.chain.body_index[name]]
                left.plot([body.pivot[0]], [body.pivot[1]], marker="o", markersize=4,
                          markerfacecolor="white", markeredgecolor=color)
            wheel_body = build.chain.bodies[
                build.chain.body_index[f"WHEEL_{axle}_NEG_Y"]]
            angle = angles[f"WHEEL_{axle}_NEG_Y"]
            pivot = wheel_body.pivot
            left.plot([pivot[0] - 0.55 * math.cos(angle), pivot[0] + 0.55 * math.cos(angle)],
                      [pivot[1] - 0.55 * math.sin(angle), pivot[1] + 0.55 * math.sin(angle)],
                      color="#e8291c", linewidth=3.0, solid_capstyle="round")
        left.set_aspect("equal")
        left.grid(alpha=0.25)
        left.set_title(f"{axle} 桥优化设计机构布置（真实比例，三个构型叠加）\n"
                       f"空心圆 = 枢轴（甲方主销/摆臂轴为原值，中间摇臂为新设计）")
        left.set_xlabel("x [m]（+ 车头方向）")
        left.set_ylabel("y [m]（+ 车辆左侧）")
        left.legend(fontsize=8, loc="best")

        # ---- 右：轮角 vs 机构坐标
        grid = np.linspace(lo, hi, 61)
        new_left, new_right = [], []
        for q in grid:
            state = new_model.mechanism_state(
                {**{d: 0.0 for d in DOF_OF_GROUP.values()}, dof: float(q)})
            new_left.append(state.wheel_angles_deg[f"axle{axle}_left"])
            new_right.append(state.wheel_angles_deg[f"axle{axle}_right"])
        right.plot(np.degrees(grid), new_left, color="#1b5e20", linewidth=2.0,
                   label="优化机构 左轮")
        right.plot(np.degrees(grid), new_right, color="#1b5e20", linewidth=2.0,
                   linestyle="--", label="优化机构 右轮")
        old_grid = np.linspace(*old_model.q_envelopes[dof], 61)
        old_left, old_right = [], []
        for q in old_grid:
            lookup = old_model.lookups[dof]
            old_left.append(math.degrees(lookup.angle(f"axle{axle}_left", float(q))))
            old_right.append(math.degrees(lookup.angle(f"axle{axle}_right", float(q))))
        right.plot(np.degrees(old_grid), old_left, color="#b00020", linewidth=1.4,
                   label="原始机构 左轮")
        right.plot(np.degrees(old_grid), old_right, color="#b00020", linewidth=1.4,
                   linestyle="--", label="原始机构 右轮")
        right.axhline(0.0, color="k", linewidth=0.8)
        right.grid(alpha=0.3)
        right.set_xlabel(f"{dof} [°]（机构坐标）")
        right.set_ylabel("车轮转角 [°]")
        right.set_title(f"{axle} 桥：左右轮转角随机构坐标变化\n"
                        f"原始机构左右轮反号（红）——优化机构左右轮同向（绿）")
        right.legend(fontsize=8, ncol=2)
        figure.suptitle(
            f"优化设计机构 REDESIGNED_ACKERMANN —— ENGINEERING_REDESIGN_PROPOSAL"
            f"（甲方原始硬点不变，尚未实车验证）", fontsize=11)
        figure.tight_layout(rect=(0, 0, 1, 0.93))
        path = out / f"m3_mechanism_axle{axle}.png"
        figure.savefig(path, dpi=130)
        print("written:", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
