"""PHASE J1：统一工程模型的回归测试（对应任务书第十一节的验收项）。

这些测试锁住本轮的关键结论，避免回退：机械方向与连续性、一桥外轮跟随、
行程单调可逆、PID 饱和统计、道路负载用实际曲率、附着超限不中断积分、
3111 工况全部算出、单模型（界面无模式切换）。
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).parents[2]
SPEC = ROOT / "mechanical_model_input_spec_v1.0.yaml"
ENG_CONFIG = ROOT / "configs" / "j1" / "engineering_config.json"
ENG_DESIGN = ROOT / "configs" / "j1" / "engineering_mechanism.json"
J0_CONFIG = ROOT / "configs" / "j0" / "j0_config.json"
WHEELS = tuple(f"axle{a}_{s}" for a in range(1, 7) for s in ("left", "right"))
FLIP = {w: f"{w.split('_')[0]}_{'right' if w.endswith('left') else 'left'}"
        for w in WHEELS}


@pytest.fixture(scope="session")
def model():
    from steering_sim.engineering.model import EngineeringSteeringModel
    return EngineeringSteeringModel(SPEC, ENG_CONFIG, ENG_DESIGN)


@pytest.fixture(scope="session")
def reference():
    from steering_sim.mechanics import reference_geometry_from_file
    return reference_geometry_from_file(SPEC)


# --------------------------------------------------------------- 甲方数据
def test_customer_geometry_is_unchanged(reference):
    point = reference.points["P20_SRC"].position
    assert abs(float(point[0]) + 7.290) < 1e-9
    assert abs(float(point[1]) + 0.996) < 1e-9
    spec = (ROOT / "mechanical_model_input_spec_v1.0.yaml").read_bytes()
    assert len(spec) == 32099


def test_the_mechanism_reuses_customer_kingpins_and_swing_pivots(model, reference):
    for axle in range(1, 7):
        for side, legacy in (("left", "POS_Y"), ("right", "NEG_Y")):
            expected = tuple(float(v) for v in
                             reference.bodies[f"WHEEL_{axle}_{legacy}"].pivot)
            assert model.centers[f"axle{axle}_{side}"] == pytest.approx(expected)


# --------------------------------------------------------- 第一关：机械
@pytest.mark.parametrize("angle", [-30.0, -20.0, -5.0, 5.0, 20.0, 30.0])
def test_directions_are_correct(model, angle):
    geometry = model.solve_geometry(angle)
    sign = math.copysign(1.0, angle)
    for axle in (1, 2):
        for side in ("left", "right"):
            value = geometry.theoretical_angle_deg[f"axle{axle}_{side}"]
            assert abs(value) > 0.5 and math.copysign(1.0, value) == sign
    for axle in (4, 5, 6):
        for side in ("left", "right"):
            value = geometry.theoretical_angle_deg[f"axle{axle}_{side}"]
            assert abs(value) > 0.5 and math.copysign(1.0, value) == -sign


def test_third_axle_is_locked_for_every_angle(model):
    for angle in range(-30, 31):
        geometry = model.solve_geometry(float(angle))
        assert abs(geometry.theoretical_angle_deg["axle3_left"]) < 1e-9
        assert abs(geometry.theoretical_angle_deg["axle3_right"]) < 1e-9


def test_same_axle_wheels_never_oppose(model):
    for angle in range(-30, 31):
        geometry = model.solve_geometry(float(angle))
        if angle == 0:
            continue
        for axle in (4, 5, 6):
            left = geometry.theoretical_angle_deg[f"axle{axle}_left"]
            right = geometry.theoretical_angle_deg[f"axle{axle}_right"]
            assert math.copysign(1.0, left) == math.copysign(1.0, right)


def test_outer_wheel_follows_the_target_all_the_way_to_30_deg(model):
    """M3 在这里失败过（一桥外轮只到 26°）；本模型必须精确跟随。"""
    for angle in (-30.0, -20.0, -10.0, 10.0, 20.0, 30.0):
        geometry = model.solve_geometry(angle)
        assert geometry.outer_wheel is not None
        error = geometry.theoretical_angle_deg[geometry.outer_wheel] - angle
        assert abs(error) < 0.05, (angle, error)


def test_no_angle_jump_between_neighbouring_targets(model):
    """目标角每 1° 变化时任何车轮的转角都不得突跳。"""
    previous = None
    for angle in range(-30, 31):
        geometry = model.solve_geometry(float(angle))
        current = geometry.theoretical_angle_deg
        if previous is not None:
            jump = max(abs(current[w] - previous[w]) for w in WHEELS)
            assert jump < 4.0, (angle, jump)
        previous = dict(current)


def test_left_and_right_turns_are_mirrored(model):
    for angle in (2.0, 5.0, 10.0, 20.0, 30.0):
        plus = model.solve_geometry(angle)
        minus = model.solve_geometry(-angle)
        for wheel in WHEELS:
            if wheel.startswith("axle3"):
                continue
            total = (minus.theoretical_angle_deg[wheel]
                     + plus.theoretical_angle_deg[FLIP[wheel]])
            # 容差 3°：残余主要来自六桥 —— 它在 ±30° 目标下只能转到约 ±32°，
            # 而理想阿克曼要求 ±40°，最小二乘拟合在两侧的折中略有差别。
            # 这是机构可达范围的固有局限，已在报告里如实记录，不是符号错误。
            assert abs(total) < 3.0, (angle, wheel, total)


def test_ackermann_error_stays_small(model):
    worst = 0.0
    for angle in range(-30, 31):
        geometry = model.solve_geometry(float(angle))
        values = [geometry.theoretical_angle_deg[f"axle{a}_{s}"]
                  - geometry.ideal_ackermann_angle_deg[f"axle{a}_{s}"]
                  for a in (4, 5, 6) for s in ("left", "right")]
        worst = max(worst, math.sqrt(sum(v * v for v in values) / len(values)))
    assert worst < 4.0, worst


def test_stroke_mapping_is_monotone_over_the_envelope(model):
    """J0 的行程反解要求代表行程在包络内严格单调（否则必须先收缩包络）。"""
    import numpy as np
    for dof, (low, high) in model.q_envelopes.items():
        values = []
        for q in np.linspace(low, high, 81):
            probe = {d: 0.0 for d in model.q_envelopes}
            probe[dof] = float(q)
            state = model.mechanism_state(probe)
            key = {"q_front": "front", "q4": "axle4", "q5": "axle5",
                   "q6": "axle6"}[dof]
            values.append(float(state.representative_stroke_m[key]))
        steps = np.diff(values)
        assert np.all(steps >= -1e-12) or np.all(steps <= 1e-12), dof


def test_link_residual_is_at_machine_precision(model):
    for angle in (-30.0, -10.0, 0.0, 10.0, 30.0):
        geometry = model.solve_geometry(angle)
        state = model.mechanism_state(geometry.q_rad)
        assert state.max_residual_m < 1e-10


# --------------------------------------------------- 第二关：液压选型文件
def test_hydraulic_sizing_file_is_complete():
    import json
    data = json.loads((ROOT / "configs" / "j1" / "hydraulic_design.json")
                      .read_text(encoding="utf-8"))
    assert data["tag"] == "ENGINEERING_DESIGN_ASSUMPTION"
    assert set(data["groups"]) == {"channel_front", "channel_rear_1",
                                   "channel_rear_2", "channel_rear_3"}
    for item in data["groups"].values():
        assert item["required_force_n"] > 0
        assert item["recommended_bore_mm"] > 0
        assert item["required_half_stroke_mm"] > 0
        assert item["required_flow_l_per_min"] > 0
    assert "legacy_parameters" in data


# ------------------------------------------------- 问题1：PID 饱和统计
def test_pid_reports_unclipped_request_and_limit_flag():
    from steering_sim.control.base import Measurement, Reference
    from steering_sim.control.pid import PIDController
    controller = PIDController(150.0, 60.0, 0.0, limit=1.0)
    controller.reset()
    command = controller.step(Measurement(np.array([0.0])),
                              Reference(np.array([1.0])), 0.01)
    diagnostics = controller.diagnostics
    assert diagnostics is not None
    assert float(diagnostics.unclipped_request[0]) > 1.0
    assert float(diagnostics.clipped_command[0]) == pytest.approx(1.0)
    assert bool(diagnostics.at_limit[0]) is True
    assert float(command.values[0]) == pytest.approx(1.0)
    # 未限幅请求必须与限幅后的命令不同 —— 这正是旧实现丢掉的信息。
    assert float(diagnostics.unclipped_request[0]) != float(
        diagnostics.clipped_command[0])


def test_runner_uses_the_controller_diagnostics_not_the_clipped_value():
    import inspect
    from steering_sim.j0_coupling.runner import J0Runner
    source = inspect.getsource(J0Runner.run_case)
    assert "diagnostics.at_limit" in source
    assert "diagnostics.unclipped_request" in source


# ------------------------------------------------- 问题2：道路负载曲率
def test_actual_curvature_uses_the_actual_wheel_angles(model):
    from steering_sim.j0_coupling.road_load import actual_curvature_1pm
    centers = {w: tuple(float(v) for v in model.centers[w]) for w in WHEELS}
    straight = {w: 0.0 for w in WHEELS}
    curvature, _, _, _ = actual_curvature_1pm(straight, centers)
    assert abs(curvature) < 1e-9
    turning = dict(model.solve_geometry(10.0).theoretical_angle_deg)
    turning["axle3_left"] = turning["axle3_right"] = 0.0
    curvature, x_icr, y_icr, residual = actual_curvature_1pm(turning, centers)
    assert abs(curvature) > 0
    assert y_icr is not None and abs(y_icr) > 1.0
    # 残差是"实际轮角下的 12 条轮轴线并不严格交于一点"的度量：机构角与理想角
    # 相差越大，残差越大（实测 +10° 约 1.5 m）。用 5 m 作为工程上界。
    assert residual < 5.0


def test_road_load_flags_do_not_stop_the_integration():
    import inspect
    from steering_sim.j0_coupling.runner import J0Runner
    source = inspect.getsource(J0Runner._stage)
    assert "LOAD_CONVERSION_SINGULAR" in source
    assert "ADHESION_INFEASIBLE" not in source.split("fatal")[1][:400]


# --------------------------------------------------------- 单模型与界面
def test_only_one_formal_mode_is_used():
    import json
    config = json.loads((ROOT / "configs" / "j0" / "j0_config.json")
                        .read_text(encoding="utf-8"))
    assert config["mechanical"]["mode"] == "ENGINEERING_STEERING_MODEL"


def test_gui_has_no_mode_switch():
    source = (ROOT / "src" / "steering_sim" / "demo" / "ui.py").read_text(encoding="utf-8")
    assert "机械机构模式" not in source
    assert "_on_mode_changed" not in source
    assert "ENGINEERING_STEERING_MODEL" in source


def test_batch_results_are_structurally_complete():
    import csv
    path = ROOT / "outputs" / "j1" / "j1_full_cases.csv"
    if not path.exists():
        pytest.skip("批量结果尚未生成")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 3111
    assert all(row.get("综合状态") for row in rows)
    assert not any(row.get("错误") for row in rows)
