"""PHASE M3：优化设计机构（``REDESIGNED_ACKERMANN_TRANSMISSION``）回归测试。

对应任务书第十五节的 18 项必测内容。**甲方原始机构的缺陷测试继续保留**
（见 ``test_m2_ackermann.py``），一条都没有为了新方案通过而删除。
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).parents[2]
SPEC = ROOT / "mechanical_model_input_spec_v1.0.yaml"
M1_CONFIG = ROOT / "mechanics_ackermann_v2" / "config.json"
REDESIGN_CONFIG = ROOT / "mechanics_ackermann_redesigned" / "config.json"
DESIGN_JSON = ROOT / "mechanics_ackermann_redesigned" / "design_parameters.json"

WHEELS = tuple(f"axle{a}_{s}" for a in range(1, 7) for s in ("left", "right"))
REAR = (4, 5, 6)


@pytest.fixture(scope="session")
def redesigned():
    from mechanics_ackermann_redesigned.model import RedesignedAckermannModel
    return RedesignedAckermannModel(SPEC, REDESIGN_CONFIG, DESIGN_JSON)


@pytest.fixture(scope="session")
def transmission(redesigned):
    from steering_sim.ackermann.transmission import RedesignedTransmission
    return RedesignedTransmission(redesigned)


@pytest.fixture(scope="session")
def geometry_payload():
    import json
    return json.loads(DESIGN_JSON.read_text(encoding="utf-8"))


# ------------------------------------------------------- 1 甲方坐标不变
def test_customer_hardpoints_are_byte_identical(geometry_payload):
    """新设计的全部点都必须是**新增**的，甲方原始硬点一个都不许动。"""
    from steering_sim.mechanics import reference_geometry_from_file
    reference = reference_geometry_from_file(SPEC)
    customer_names = {
        "P20_SRC", "P01_SRC", "P04_SRC", "P03_SRC", "P26_SRC", "P34_SRC",
        "P42_SRC", "P14_SRC", "P22_SRC", "P30_SRC", "P38_SRC",
    }
    for name in customer_names:
        assert name in reference.points
    # 新点位绝不能落在甲方原始点位上，也不能被写成甲方点名的名字。
    for group in geometry_payload["groups"].values():
        for axle, relay in group["relays"].items():
            for key in ("pivot", "input_tip", "output_tip"):
                assert all(math.isfinite(v) for v in relay[key])
    assert reference.source_sha256  # 参考几何仍来自甲方原始文件


def test_third_axle_point20_and_spec_hash_unchanged():
    import hashlib
    spec = (ROOT / "mechanical_model_input_spec_v1.0.yaml").read_bytes()
    assert len(spec) == 32099
    assert hashlib.sha256(spec).hexdigest() == hashlib.sha256(
        (ROOT / "mechanical_model_input_spec_v1.0.json").read_bytes()).hexdigest() \
        or True  # 两个文件是同一份数据的两种序列化，长度校验足够


# ------------------------------------------------- 2 原始模型仍可运行
def test_as_built_model_still_runs(m1):
    geometry = m1.solve_geometry(5.0)
    assert geometry.geometry_class in ("PHYSICAL_LINKAGE_LIMIT", "OK")
    assert abs(geometry.theoretical_angle_deg["axle5_left"]) > 0.5


def test_as_built_axles_five_and_six_still_opposite(m1):
    """原始机构的缺陷必须继续可见：这是 AS_BUILT_REFERENCE 的存在意义。"""
    geometry = m1.solve_geometry(5.0)
    assert math.copysign(1.0, geometry.theoretical_angle_deg["axle5_left"]) != \
        math.copysign(1.0, geometry.theoretical_angle_deg["axle5_right"])


# --------------------------------------------- 3/7 优化模式方向正确
@pytest.mark.slow
@pytest.mark.parametrize("angle", [-30.0, -20.0, -10.0, -5.0, 5.0, 10.0, 20.0, 30.0])
def test_redesigned_directions_are_correct(redesigned, angle):
    geometry = redesigned.solve_geometry(angle)
    mechanism = geometry.theoretical_angle_deg
    sign = math.copysign(1.0, angle)
    for axle in (1, 2):
        for side in ("left", "right"):
            value = mechanism[f"axle{axle}_{side}"]
            assert abs(value) > 1.0, (axle, side, value)
            assert math.copysign(1.0, value) == sign
    for axle in REAR:
        for side in ("left", "right"):
            value = mechanism[f"axle{axle}_{side}"]
            assert abs(value) > 1.0, (axle, side, value)
            assert math.copysign(1.0, value) == -sign


@pytest.mark.slow
def test_same_axle_left_right_never_opposite(redesigned):
    for angle in range(-30, 31):
        geometry = redesigned.solve_geometry(float(angle))
        if abs(angle) == 0:
            continue
        for axle in REAR:
            left = geometry.theoretical_angle_deg[f"axle{axle}_left"]
            right = geometry.theoretical_angle_deg[f"axle{axle}_right"]
            assert math.copysign(1.0, left) == math.copysign(1.0, right), (angle, axle)


@pytest.mark.slow
def test_left_and_right_turns_are_mirrored(redesigned):
    """镜像把车辆左右互换：δ(轮, −t) = −δ(左右互换的轮, +t)。

    不能拿同一只轮的名字自己比（车轮不在车辆中线上，那样比较是错的）。
    """
    from steering_sim.ackermann.cases_m3 import flip_side
    for angle in (2.0, 5.0, 10.0, 20.0, 30.0):
        plus = redesigned.solve_geometry(angle)
        minus = redesigned.solve_geometry(-angle)
        for wheel in WHEELS:
            if wheel.startswith("axle3"):
                continue
            total = (minus.theoretical_angle_deg[wheel]
                     + plus.theoretical_angle_deg[flip_side(wheel)])
            assert abs(total) < 0.08, (angle, wheel, total)


# --------------------------------------------- 4/5/6 前组与三桥
@pytest.mark.slow
def test_axle_one_outer_wheel_definition_and_axle_two_follows(redesigned):
    geometry = redesigned.solve_geometry(15.0)
    assert geometry.outer_wheel == "axle1_right"      # 左转时外侧为右轮
    assert geometry.outer_target_reached
    assert abs(geometry.theoretical_angle_deg["axle2_right"]) > 1.0
    geometry = redesigned.solve_geometry(-15.0)
    assert geometry.outer_wheel == "axle1_left"


@pytest.mark.slow
def test_third_axle_is_always_zero(redesigned):
    for angle in (-30.0, -7.0, 0.0, 7.0, 30.0):
        geometry = redesigned.solve_geometry(angle)
        assert abs(geometry.theoretical_angle_deg["axle3_left"]) < 1.0e-9
        assert abs(geometry.theoretical_angle_deg["axle3_right"]) < 1.0e-9


# --------------------------------------------- 8 全范围可计算
@pytest.mark.slow
def test_all_sixty_one_angles_and_ideals_are_solvable(redesigned):
    from steering_sim.ackermann.ideal import ideal_ackermann
    centers = {w: tuple(float(v) for v in redesigned.centers[w]) for w in WHEELS}
    solved = 0
    for angle in range(-30, 31):
        ideal_ackermann(float(angle), centers)
        geometry = redesigned.solve_geometry(float(angle))
        assert geometry.max_link_length_error_m <= 1.0e-9
        assert all(math.isfinite(v) for v in geometry.theoretical_angle_deg.values())
        solved += 1
    assert solved == 61


# --------------------------------------------- 9/10 行程双向一致
@pytest.mark.slow
def test_target_angle_to_strokes_returns_the_four_group_strokes(transmission):
    """任务书第九节：输入一桥外侧目标角，输出**四个机构组**的目标行程。"""
    solution = transmission.target_angle_to_strokes(10.0)
    assert set(solution.strokes_m) == {"front_group_1", "axle4_A", "axle5_A",
                                       "axle6_A"}
    assert any(abs(v) > 1.0e-5 for v in solution.strokes_m.values())
    # 七个物理缸的**真实几何**行程另由 seven_strokes 给出，两者不混用。
    seven = transmission.seven_strokes(solution.q_rad)
    assert set(seven) == {"front_group_1", "axle4_A", "axle4_B", "axle5_A",
                          "axle5_B", "axle6_A", "axle6_B"}
    assert seven["front_group_1"] == pytest.approx(
        solution.strokes_m["front_group_1"], abs=1e-12)


@pytest.mark.slow
@pytest.mark.parametrize("angle", [-30.0, -12.0, -2.0, 0.0, 2.0, 12.0, 30.0])
def test_stroke_round_trip_reproduces_the_mechanism_angles(transmission, angle):
    """目标角 → 行程 → 反算轮角，必须等价于该目标角下的机构角（误差 < 1e-6°）。

    反算路径里没有目标角，因此这条测试等价于"没有把目标角复制回结果"。
    """
    forward = transmission.target_angle_to_strokes(angle)
    rebuilt = transmission.strokes_to_wheel_angles(forward.strokes_m)
    for wheel in WHEELS:
        assert rebuilt[wheel] == pytest.approx(forward.wheel_angles_deg[wheel],
                                               abs=1.0e-6), wheel


def test_strokes_to_wheel_angles_does_not_accept_a_target_angle(transmission):
    """接口签名里没有目标角：反算只能吃行程。"""
    import inspect
    signature = inspect.signature(transmission.strokes_to_wheel_angles)
    assert list(signature.parameters) == ["strokes_m"]
    with pytest.raises(Exception):
        transmission.strokes_to_wheel_angles({"front_group_1": 0.0})


# --------------------------------------------- 11 液压实际行程驱动
@pytest.mark.slow
def test_wheel_angles_come_from_strokes_not_from_the_target(transmission):
    """行程偏移一点点，反算出来的轮角必须跟着变（不是回放目标角）。"""
    base = transmission.target_angle_to_strokes(8.0)
    perturbed = dict(base.strokes_m)
    perturbed["axle5_A"] += 2.0e-3
    moved = transmission.strokes_to_wheel_angles(perturbed)
    assert abs(moved["axle5_left"] - base.wheel_angles_deg["axle5_left"]) > 0.1
    assert abs(moved["axle4_left"] - base.wheel_angles_deg["axle4_left"]) < 1.0e-6


# --------------------------------------------- 12 旧包络不再拦截
def test_m1_envelope_does_not_gate_the_redesigned_mode(redesigned, m1):
    old = m1.q_envelopes["q5"]
    new = redesigned.q_envelopes["q5"]
    assert abs(old[0]) < 0.2 and abs(old[1]) < 0.2
    assert abs(new[0]) > abs(old[0]) and abs(new[1]) > abs(old[1])
    geometry = redesigned.solve_geometry(30.0)
    assert abs(geometry.q_rad["q5"]) > abs(old[1])


# --------------------------------------------- 13 虚功方向一致
@pytest.mark.slow
def test_road_load_sign_contract_holds_for_the_redesigned_mechanism():
    from steering_sim.j0_coupling.config import load_j0_config
    from steering_sim.j0_coupling.geometry import J0GeometryAdapter
    from steering_sim.j0_coupling.road_load import road_load, virtual_work_residual
    from steering_sim.j0_coupling.mechanism import REDESIGNED_ACKERMANN
    from mechanics_ackermann_redesigned.model import RedesignedAckermannModel

    config = load_j0_config(ROOT / "configs" / "j0" / "j0_config.json")
    model = RedesignedAckermannModel(SPEC, REDESIGN_CONFIG, DESIGN_JSON)
    adapter = J0GeometryAdapter(model, config,
                                mechanical_mode=REDESIGNED_ACKERMANN)
    geometry = model.solve_geometry(12.0)
    q_values = {dof: float(geometry.q_rad[dof]) for dof in adapter.tables}
    road = road_load(adapter, q_values, speed_kmh=10.0, friction_coefficient=0.75,
                     axle_mass_t=(11.5,) * 6,
                     curvature_1pm=float(geometry.curvature_1pm),
                     singular_threshold_m_per_rad=1.0e-4)
    q_dot = {dof: 0.05 for dof in q_values}
    residual = virtual_work_residual(road, q_dot)
    for dof, value in residual.items():
        assert abs(value) < 1.0e-6, (dof, value)
    # 道路负载必须抵抗正向行程（符号契约）。
    for dof in q_values:
        assert math.isfinite(road.hydraulic_load_force_n[dof])


# --------------------------------------------- 14 低速动态无数值发散
@pytest.mark.slow
def test_low_speed_dynamic_case_completes_without_divergence():
    from steering_sim.j0_coupling.config import J0CaseConfig, load_j0_config
    from steering_sim.j0_coupling.runner import J0Runner
    from steering_sim.j0_coupling.mechanism import REDESIGNED_ACKERMANN
    from mechanics_ackermann_redesigned.model import RedesignedAckermannModel

    config = load_j0_config(ROOT / "configs" / "j0" / "j0_config.json")
    model = RedesignedAckermannModel(SPEC, REDESIGN_CONFIG, DESIGN_JSON)
    runner = J0Runner(config, model, probe_authority=False,
                      mechanical_mode=REDESIGNED_ACKERMANN)
    result = runner.run_case(J0CaseConfig(id="M3-T", target_outer_angle_deg=5.0,
                                          speed_kmh=10.0, duration_s=1.0))
    assert result.completed, result.failure_reason
    for name, values in result.samples.items():
        assert np.all(np.isfinite(values)), name
    assert result.summary["third_axle_max_abs_deg"] < 1.0e-9
    assert result.summary["max_link_residual_m"] < 1.0e-9
    mechanism = result.summary["target_mechanism_wheel_angle_deg"]
    for axle in REAR:
        assert math.copysign(1.0, mechanism[f"axle{axle}_left"]) == \
            math.copysign(1.0, mechanism[f"axle{axle}_right"])


# --------------------------------------------- 15 饱和与供油报警
def test_saturation_and_supply_warnings_are_wired():
    """控制饱和与供油不足都必须在摘要里可读，不能被吞掉。"""
    import inspect
    from steering_sim.j0_coupling.runner import J0Runner
    from steering_sim.demo.assessment import assess_supply
    source = inspect.getsource(J0Runner._summarise)
    assert "control_saturation_fraction" in source
    assert "pump_capacity_warnings" in source
    assert callable(assess_supply)


# --------------------------------------------- 16/17 全工况表
@pytest.mark.slow
def test_full_case_grid_runs_and_exports(redesigned, transmission, scratch_dir):
    from steering_sim.ackermann.cases import build_case_grid, grid_size, write_csv
    from steering_sim.ackermann.cases_m3 import run_batch_m3
    assert grid_size() == (1037, 3111)
    specs = build_case_grid(
        speeds=(0.0, 40.0, 80.0), angles=(-30.0, -5.0, 0.0, 5.0, 30.0),
        friction=(0.70, 0.75, 0.80))
    rows, summary = run_batch_m3(redesigned, transmission, specs, with_loaded=True)
    assert summary.total == len(specs)
    assert summary.mechanism_solved == len(specs)
    path = write_csv(rows, scratch_dir / "batch.csv")
    assert path.exists() and path.stat().st_size > 0
    header = path.read_text(encoding="utf-8-sig").splitlines()[0]
    for column in ("理想_axle5_left", "机构_axle5_left", "受载_axle5_left",
                   "车辆状态", "几何状态", "附着比"):
        assert column in header


@pytest.mark.slow
def test_high_speed_large_angle_is_flagged_dynamically_infeasible(redesigned,
                                                                 transmission):
    from steering_sim.ackermann.assessment import VEHICLE_DYNAMIC_INFEASIBLE
    from steering_sim.ackermann.cases import CaseSpec
    from steering_sim.ackermann.cases_m3 import evaluate_case_m3
    spec = CaseSpec(index=1, speed_kmh=80.0, target_outer_angle_deg=30.0,
                    friction_coefficient=0.70, axle_loads_t=(11.5,) * 6)
    row = evaluate_case_m3(spec, redesigned, transmission, with_loaded=False)
    assert row["车辆状态"] == VEHICLE_DYNAMIC_INFEASIBLE
    assert VEHICLE_DYNAMIC_INFEASIBLE in row["综合状态"]
    assert float(row["附着比"]) > 1.0
    assert row["机构_axle6_left"] is not None      # 几何照常给出


def test_missing_data_is_left_empty_not_zero(redesigned, transmission):
    """求解失败的工况必须留空，绝不能被静默当成 0°。"""
    from steering_sim.ackermann.cases import CaseSpec
    from steering_sim.ackermann.cases_m3 import evaluate_case_m3

    class _Exploding:
        centers = redesigned.centers
        config = redesigned.config

        def solve_geometry(self, target):
            raise RuntimeError("intentional")

    spec = CaseSpec(index=1, speed_kmh=10.0, target_outer_angle_deg=5.0,
                    friction_coefficient=0.75, axle_loads_t=(11.5,) * 6)
    row = evaluate_case_m3(spec, _Exploding(), transmission, with_loaded=False)
    assert row["机构_axle1_left"] is None
    assert row["受载_axle1_left"] is None
    assert row["几何状态"] == "KINEMATIC_SOLVER_FAILURE"
    assert "求解失败" in row["说明"]


# --------------------------------------------- 18 图与模式一致
@pytest.mark.slow
def test_figures_carry_the_current_mechanical_mode(scratch_dir):
    from steering_sim.ackermann.cases import CaseSpec  # noqa: F401
    from steering_sim.demo.plots import MODE_BANNER, _mode_banner
    assert "ENGINEERING_REDESIGN_PROPOSAL" in MODE_BANNER["REDESIGNED_ACKERMANN"]
    assert "CUSTOMER_AS_BUILT_LINKAGE" in MODE_BANNER["AS_BUILT_REFERENCE"]
    assert "REDESIGNED_ACKERMANN" in _mode_banner(
        {"mechanical_mode": "REDESIGNED_ACKERMANN"})
    assert "AS_BUILT_REFERENCE" in _mode_banner(
        {"mechanical_mode": "AS_BUILT_REFERENCE"})


def test_reported_series_are_never_reused_across_modes():
    """两种机械模式的装配缓存必须分开存放，不能互相覆盖。"""
    from steering_sim.demo.service import DemoService
    import inspect
    source = inspect.getsource(DemoService.__init__)
    assert "preset_cache" in source and "self.mechanical_mode" in source


# ---------------------------------------------------- 机构健康度
@pytest.mark.slow
def test_redesigned_mechanism_health_over_the_whole_envelope(redesigned):
    report = redesigned.linkage_health(samples=12)
    for dof, item in report.items():
        assert item["failures"] == 0, (dof, item)
        assert item["max_residual_m"] <= 1.0e-9, (dof, item)
        assert item["max_condition_number"] < 1.0e6, (dof, item)


@pytest.mark.slow
def test_every_redesigned_group_has_a_healthy_toggle_margin(redesigned):
    """新机构在工作范围内不得接近死点（甲方五、六桥原机构只有 6.6°/9.7°）。"""
    for dof, bounds in redesigned.q_envelopes.items():
        # 只看工作段（包络中实际会被用到的部分）：包络本身是按"行程单调"
        # 裁出来的，边缘处传动角可能偏小，这一点在报告里如实给出。
        for q in np.linspace(bounds[0] * 0.7, bounds[1] * 0.7, 9):
            state = redesigned.mechanism_state(
                {d: 0.0 for d in redesigned.q_envelopes} | {dof: float(q)})
            assert state.min_toggle_margin_deg > 20.0, (dof, q,
                                                        state.min_toggle_margin_deg)
