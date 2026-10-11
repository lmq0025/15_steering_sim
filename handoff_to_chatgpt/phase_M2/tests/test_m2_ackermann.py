"""PHASE M2 关键测试（对应任务书第十二节 1~12 条）。"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from steering_sim.ackermann.assessment import (ACKERMANN_TARGET_MISMATCH,
                                               KINEMATIC_SOLVER_FAILURE,
                                               NUMERICAL_ENVELOPE_LIMIT, OK,
                                               PHYSICAL_LINKAGE_LIMIT,
                                               VEHICLE_DYNAMIC_INFEASIBLE,
                                               direction_violations,
                                               vehicle_feasibility)
from steering_sim.ackermann.cases import (DEFAULT_ANGLES_DEG, DEFAULT_FRICTION,
                                          DEFAULT_SPEEDS_KMH, build_case_grid,
                                          evaluate_case, grid_size, run_batch,
                                          write_csv, write_template, write_xlsx)
from steering_sim.ackermann.equivalent import (CUSTOMER_TAG, EQUIVALENT_TAG,
                                               build_equivalent_map)
from steering_sim.ackermann.ideal import (CHECK_ANGLES_DEG, IdealAckermannError,
                                          ideal_ackermann)
from steering_sim.ackermann.linkage import audit_linkage, find_dof_envelope

WHEELS = tuple(f"axle{a}_{s}" for a in range(1, 7) for s in ("left", "right"))


# ------------------------------------------------- 1. ±30° 理想阿克曼可计算
@pytest.mark.parametrize("target", CHECK_ANGLES_DEG)
def test_ideal_ackermann_is_computable_over_the_full_range(target, centers):
    result = ideal_ackermann(target, centers)
    assert set(result.angles_deg) == set(WHEELS)
    assert all(math.isfinite(value) for value in result.angles_deg.values())
    if abs(target) <= 1e-12:
        assert all(abs(value) < 1e-12 for value in result.angles_deg.values())
    else:
        assert result.turn_radius_m is not None and result.turn_radius_m > 0


def test_ideal_ackermann_matches_m1_signed_formula(m1, centers):
    """独立实现与 M1（带角度折叠）在 ±30° 内必须一致。"""
    worst = 0.0
    for target in CHECK_ANGLES_DEG:
        mine = ideal_ackermann(target, centers).angles_deg
        theirs = {k: math.degrees(v) for k, v in m1.ideal_ackermann(target)[5].items()}
        worst = max(worst, max(abs(mine[w] - theirs[w]) for w in WHEELS))
    assert worst < 1.0e-9


def test_ideal_ackermann_rejects_impossible_input(centers):
    with pytest.raises(IdealAckermannError):
        ideal_ackermann(120.0, centers)
    with pytest.raises(IdealAckermannError):
        ideal_ackermann(float("nan"), centers)


# ------------------------------------------------------ 2. 三桥永远 0°
@pytest.mark.parametrize("target", CHECK_ANGLES_DEG)
def test_third_axle_is_always_zero(target, centers):
    angles = ideal_ackermann(target, centers).angles_deg
    assert angles["axle3_left"] == 0.0 and angles["axle3_right"] == 0.0


@pytest.mark.slow
@pytest.mark.parametrize("target", (2.0, 5.0, 10.0, -5.0))
def test_third_axle_is_locked_in_the_real_mechanism(target, m1):
    geometry = m1.solve_geometry(target)
    assert abs(geometry.theoretical_angle_deg["axle3_left"]) < 1e-12
    assert abs(geometry.theoretical_angle_deg["axle3_right"]) < 1e-12


# ------------------------------------------------------- 3. 左右转镜像
@pytest.mark.parametrize("target", (2.0, 5.0, 10.0, 20.0, 30.0))
def test_left_and_right_turns_are_mirror_images(target, centers):
    left = ideal_ackermann(target, centers).angles_deg
    right = ideal_ackermann(-target, centers).angles_deg
    for axle in range(1, 7):
        assert left[f"axle{axle}_left"] == pytest.approx(
            -right[f"axle{axle}_right"], abs=1e-12)
        assert left[f"axle{axle}_right"] == pytest.approx(
            -right[f"axle{axle}_left"], abs=1e-12)


# ----------------------------- 4. 四至六桥理想方向正确、同桥同向
@pytest.mark.parametrize("target", (1.0, 2.0, 5.0, 10.0, 20.0, 30.0, -1.0,
                                    -5.0, -30.0))
def test_ideal_direction_and_same_sign_per_axle(target, centers):
    result = ideal_ackermann(target, centers)
    assert result.direction_flags() == ()
    angles = result.angles_deg
    sign = math.copysign(1.0, target)
    for axle in (1, 2):
        for side in ("left", "right"):
            assert math.copysign(1.0, angles[f"axle{axle}_{side}"]) == sign
    for axle in (4, 5, 6):
        for side in ("left", "right"):
            assert math.copysign(1.0, angles[f"axle{axle}_{side}"]) == -sign
    for axle in range(1, 7):
        left, right = angles[f"axle{axle}_left"], angles[f"axle{axle}_right"]
        assert math.copysign(1.0, left) == math.copysign(1.0, right) or \
            abs(left) < 1e-12


def test_ideal_ackermann_uses_geometry_not_a_fixed_scale(centers):
    """把某个轮心挪动后角度必须随之变化，说明用的是几何公式而非比例。"""
    moved = dict(centers)
    moved["axle6_left"] = (centers["axle6_left"][0] - 1.0, centers["axle6_left"][1])
    base = ideal_ackermann(10.0, centers).angles_deg
    other = ideal_ackermann(10.0, moved).angles_deg
    assert abs(base["axle6_left"] - other["axle6_left"]) > 0.5


# ------------------------------------- 5. 真实闭链杆长保持
@pytest.mark.slow
@pytest.mark.parametrize("target", (2.0, 5.0, 10.0, 20.0, 30.0, -30.0))
def test_real_closed_chain_preserves_link_lengths(target, m1):
    geometry = m1.solve_geometry(target)
    assert geometry.max_link_length_error_m <= 1.0e-9


@pytest.mark.slow
def test_four_bar_branch_residual_stays_tiny(four_bars):
    from steering_sim.ackermann.linkage import trace_side
    for key in ("axle4_left", "axle5_right", "axle6_left"):
        branch = trace_side(four_bars[key], limit_deg=12.0)
        assert branch.max_residual_m < 1.0e-9
        assert branch.points, key


# ------------------- 6. 数值搜索限制与物理不可达分离
@pytest.mark.slow
def test_envelope_limit_and_solver_failure_are_distinct_concepts(reference):
    envelope = find_dof_envelope(reference, "q5", step_rad=0.004, limit_rad=0.5)
    assert envelope.q_hi_rad > 0.0
    # q5 的真实延拓上限由"闭链无解"决定，而不是"程序搜索范围"。
    assert "Unreachable" in envelope.stop_reason_hi or "unreachable" in \
        envelope.stop_reason_hi.lower()
    assert envelope.max_residual_m < 1.0e-9
    assert envelope.max_condition_number < 1.0e8


@pytest.mark.slow
def test_geometry_class_separates_mismatch_from_infeasible(m1):
    matched = m1.solve_geometry(0.0)
    assert matched.geometry_class == OK
    mismatched = m1.solve_geometry(5.0)
    # 五六桥左右反号 → 物理机构无法满足阿克曼方向，绝不能再报 OK。
    assert mismatched.geometry_class == PHYSICAL_LINKAGE_LIMIT
    assert mismatched.geometry_class != NUMERICAL_ENVELOPE_LIMIT
    assert mismatched.geometry_class != KINEMATIC_SOLVER_FAILURE
    assert "LEFT_RIGHT_OPPOSITE" in mismatched.geometry_status


@pytest.mark.slow
def test_widened_envelope_still_solves_and_keeps_monotone_stroke(reference):
    envelope = find_dof_envelope(reference, "q6", step_rad=0.004, limit_rad=0.5)
    assert math.degrees(envelope.q_hi_rad) > 5.7      # 已超过旧的 0.10 rad 包络


# ---------------------- 7/8. 阿克曼匹配标注与五六桥反号的证据归因
@pytest.mark.slow
def test_axle_five_and_six_opposite_direction_is_attributed_with_evidence(reference):
    audit = audit_linkage(reference)
    # 五桥：同向区间只有 ±0.05°，实际完全无法同向转向。
    five = audit.axles[5]
    assert not five.direction_consistent
    if five.same_sign_wheel_range_deg is not None:
        low, high = five.same_sign_wheel_range_deg
        assert abs(low) < 0.5 and abs(high) < 0.5
    # 六桥：只在 ±2.8° 以内同向，超出即反号——比五桥好，但仍远不够阿克曼要求。
    six = audit.axles[6]
    assert six.direction_consistent
    low, high = six.same_sign_wheel_range_deg
    assert max(abs(low), abs(high)) < 3.0
    for axle in (5, 6):
        report = audit.axles[axle]
        # 距死点很近，而一、四桥很远——这是可复核的几何证据。
        assert report.left.distance_from_toggle_deg < 10.0
        assert abs(report.left.transmission_at_zero) < 0.35
    assert audit.axles[4].direction_consistent
    assert audit.axles[4].left.distance_from_toggle_deg > 70.0
    assert abs(audit.axles[4].left.transmission_at_zero) > 0.6


@pytest.mark.slow
@pytest.mark.parametrize("target", (2.0, 5.0))
def test_real_mechanism_left_right_opposite_appears_beyond_the_small_window(
        target, m1):
    geometry = m1.solve_geometry(target)
    left = geometry.theoretical_angle_deg["axle5_left"]
    right = geometry.theoretical_angle_deg["axle5_right"]
    assert math.copysign(1.0, left) != math.copysign(1.0, right)


@pytest.mark.slow
def test_axle_five_right_wheel_cannot_turn_right_at_all(reference):
    """这是反号的根因：右轮的可达角范围本身就是单向的。"""
    audit = audit_linkage(reference)
    right5 = audit.axles[5].right
    left5 = audit.axles[5].left
    assert right5.wheel_min_deg > -0.05      # 右轮几乎不能往负方向转
    assert left5.wheel_max_deg < 0.05        # 左轮几乎不能往正方向转
    assert right5.wheel_max_deg > 5.0
    assert left5.wheel_min_deg < -5.0


@pytest.mark.slow
def test_customer_hardpoints_are_not_modified(reference):
    """审计与等效模式都不得改动甲方坐标。"""
    body = reference.bodies["WHEEL_5_NEG_Y"]
    assert tuple(float(v) for v in body.pivot) == pytest.approx((-13.690, -0.996))
    assert tuple(float(v) for v in reference.bodies["SWING_5_NEG_Y"].pivot) ==         pytest.approx((-11.975, -0.570))
    link = next(l for l in reference.links.values()
                if {l.endpoint_a[0], l.endpoint_b[0]} ==
                {"SWING_5_NEG_Y", "WHEEL_5_NEG_Y"})
    assert link.reference_length == pytest.approx(2.4908, abs=1.0e-3)


# ------------------------- 9. 无载 / 受载 / 液压角不混淆
@pytest.mark.slow
def test_four_angle_kinds_are_kept_separate(m1, centers):
    from steering_sim.ackermann.assessment import WheelAngleSet
    geometry = m1.solve_geometry(5.0)
    ideal = ideal_ackermann(5.0, centers)
    angle_set = WheelAngleSet(
        ideal_deg=dict(ideal.angles_deg),
        theoretical_mechanical_deg=dict(geometry.theoretical_angle_deg),
        actual_loaded_deg={w: geometry.theoretical_angle_deg[w] - 0.05 for w in WHEELS})
    assert angle_set.ideal_deg is not angle_set.theoretical_mechanical_deg
    deviation = angle_set.ackermann_deviation_deg("theoretical_mechanical")
    assert abs(deviation["axle6_right"]) > 5.0
    loaded_deviation = angle_set.ackermann_deviation_deg("actual_loaded")
    assert loaded_deviation["axle1_left"] != deviation["axle1_left"]


def test_direction_violations_detect_wrong_sign_and_opposites():
    angles = {w: 0.0 for w in WHEELS}
    angles["axle1_left"] = 2.0
    angles["axle1_right"] = 2.0
    angles["axle5_left"] = -1.0
    angles["axle5_right"] = +1.0
    flags = direction_violations(angles, 2.0)
    assert any(item.endswith("LEFT_RIGHT_OPPOSITE") for item in flags)
    # 五桥右轮为 +1°，而该桥应反向（负），因此同时也是方向错误。
    assert "axle5_right:WRONG_DIRECTION" in flags
    assert "axle5_left:WRONG_DIRECTION" not in flags
    assert "axle1_left:WRONG_DIRECTION" not in flags


# -------------------------------- 10. 全工况批量表
def test_case_grid_sizes_match_the_customer_requirement():
    assert len(DEFAULT_SPEEDS_KMH) == 17
    assert len(DEFAULT_ANGLES_DEG) == 61
    assert grid_size() == (1037, 3111)
    specs = build_case_grid()
    assert len(specs) == 3111
    assert {spec.friction_coefficient for spec in specs} == set(DEFAULT_FRICTION)


@pytest.mark.slow
def test_batch_rows_are_complete_and_never_silently_zero(m1, equivalent, scratch_dir):
    specs = build_case_grid(speeds=(0.0, 40.0), angles=(-30.0, 0.0, 30.0),
                            friction=(0.7, 0.8))
    rows, summary = run_batch(m1, equivalent, specs, with_loaded=False)
    assert len(rows) == 12 and summary.total == 12
    for row in rows:
        assert row["综合状态"]
        for wheel in WHEELS:
            assert row[f"理想_{wheel}"] is not None
        if row["目标角_deg"] == 0.0:
            assert all(row[f"理想_{w}"] == 0.0 for w in WHEELS)
        # 机构解不出来时必须是 None 而不是 0
        if row["几何状态"] == KINEMATIC_SOLVER_FAILURE:
            assert row["机构_axle1_left"] is None
    csv_path = write_csv(rows, scratch_dir / "cases.csv")
    assert csv_path.exists() and csv_path.stat().st_size > 500
    text = csv_path.read_text(encoding="utf-8-sig")
    assert "理想_axle1_left" in text.splitlines()[0]


@pytest.mark.slow
def test_batch_exports_xlsx_and_template(m1, equivalent, scratch_dir):
    specs = build_case_grid(speeds=(0.0, 20.0), angles=(0.0, 5.0), friction=(0.75,))
    rows, _ = run_batch(m1, equivalent, specs, with_loaded=False)
    xlsx = write_xlsx(rows, scratch_dir / "cases.xlsx")
    assert xlsx.exists() and xlsx.stat().st_size > 3000
    template = write_template(scratch_dir / "template.csv", limit=20)
    assert template.exists()
    lines = template.read_text(encoding="utf-8-sig").splitlines()
    assert len(lines) == 21
    assert lines[0].startswith("序号,车速_kmh,一桥外侧目标角_deg")


@pytest.mark.slow
def test_full_3111_grid_runs_and_reports_statuses(m1, equivalent):
    specs = build_case_grid()
    rows, summary = run_batch(m1, equivalent, specs, with_loaded=False)
    assert summary.total == 3111
    assert summary.ideal_ok == 3111
    assert sum(summary.status_counts.values()) == 3111
    assert summary.vehicle_infeasible > 0        # 高速大转角必然不满足附着
    assert OK in summary.status_counts           # 直行可解


# -------------------------- 11. 高速大角度附着不足报警
def test_vehicle_dynamics_flags_excess_lateral_acceleration():
    tight = vehicle_feasibility(80.0, 0.7, 11.65)
    assert tight.status == VEHICLE_DYNAMIC_INFEASIBLE
    assert tight.adhesion_ratio > 1.0
    assert "附着不足" in tight.message
    gentle = vehicle_feasibility(5.0, 0.75, 208.05)
    assert gentle.status == OK and gentle.adhesion_ratio < 1.0
    straight = vehicle_feasibility(80.0, 0.7, None)
    assert straight.status == OK


@pytest.mark.slow
def test_batch_marks_high_speed_large_angle_as_dynamically_infeasible(m1, equivalent):
    specs = build_case_grid(speeds=(80.0,), angles=(30.0,), friction=(0.7,))
    rows, _ = run_batch(m1, equivalent, specs, with_loaded=False)
    assert rows[0]["车辆状态"] == VEHICLE_DYNAMIC_INFEASIBLE
    assert "a_y" in rows[0]["说明"]
    # 几何结果仍然照常输出，只是标记动力学不可行。
    assert rows[0]["理想_axle6_left"] is not None


# --------------------------- 工程等效模式
@pytest.mark.slow
def test_equivalent_mode_is_bounded_monotone_and_same_sign(m1, equivalent):
    channel = equivalent["channel_rear_2"]
    assert channel.tag == EQUIVALENT_TAG
    swings = np.linspace(-math.radians(channel.swing_max_deg),
                         math.radians(channel.swing_max_deg), 101)
    wheels = [channel.wheel_rad(s) for s in swings]
    increasing = all(a <= b + 1e-12 for a, b in zip(wheels, wheels[1:]))
    decreasing = all(a >= b - 1e-12 for a, b in zip(wheels, wheels[1:]))
    assert increasing or decreasing          # 严格单调（反相桥为单调递减）
    assert max(abs(v) for v in wheels) <= math.radians(
        channel.wheel_amplitude_max_deg) + 1e-12                     # 有界
    positive = channel.wheel_rad(math.radians(5.0))
    negative = channel.wheel_rad(math.radians(-5.0))
    assert positive == pytest.approx(-negative, abs=1e-12)           # 奇函数
    assert positive < 0.0                                            # 反相桥符号正确


@pytest.mark.slow
def test_equivalent_mode_is_only_used_where_the_real_linkage_fails(
        reference, four_bars, equivalent):
    assert equivalent["channel_rear_1"].uses_real_linkage is True    # 四桥真实机构可用
    assert equivalent["channel_rear_2"].uses_real_linkage is False
    assert equivalent["channel_rear_3"].uses_real_linkage is False
    for channel in equivalent.values():
        assert channel.assumptions
        if not channel.uses_real_linkage:
            assert channel.tag == EQUIVALENT_TAG
        else:
            assert channel.tag == CUSTOMER_TAG


@pytest.mark.slow
def test_equivalent_mode_exposes_its_assumptions(equivalent):
    channel = equivalent["channel_rear_3"]
    payload = channel.to_dict()
    assert payload["tag"] == EQUIVALENT_TAG
    assert any("ASSUMED" in item for item in payload["assumptions"])
    assert payload["wheel_amplitude_max_deg"] > 0
    assert payload["stroke_span_m"] > 0


@pytest.mark.slow
def test_equivalent_stroke_is_bounded_by_the_real_cylinder(equivalent):
    channel = equivalent["channel_rear_2"]
    over = channel.stroke_m(math.radians(channel.swing_max_deg * 3))
    at_limit = channel.stroke_m(math.radians(channel.swing_max_deg))
    assert over == pytest.approx(at_limit)          # 大角度下自然饱和，不外推
