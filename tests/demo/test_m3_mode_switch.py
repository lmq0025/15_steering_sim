"""PHASE M3：界面/服务层的机械模式切换。

要点：两种机构的结果**绝不能混显示**，模式必须出现在界面与图上，
且原始机构的缺陷测试（见 ``test_demo_scenario_and_assessment.py``）继续有效。
"""
from __future__ import annotations

import pytest

from steering_sim.demo.scenario import DemoScenario

#: 原始机构在 q6 上只能到 ±6.42°，因此对照用它自己能跑的 +5° 工况。
SHORT = DemoScenario(5.0, 5.0, duration_s=0.6)
#: 优化设计机构才跑得动的大转角工况。
BIG = DemoScenario(20.0, 5.0, duration_s=0.6)


def test_the_default_service_uses_the_single_engineering_model():
    """PHASE J1 §九：界面只保留一套正式模型，默认必须是 ENGINEERING_STEERING_MODEL。"""
    from pathlib import Path
    from steering_sim.demo.service import DemoService
    from steering_sim.j0_coupling.mechanism import ENGINEERING_STEERING_MODEL
    output = Path(__file__).parents[2] / "outputs" / "_demo_test_tmp" / "default_mode"
    service = DemoService(output_dir=output)
    assert service.mechanical_mode == ENGINEERING_STEERING_MODEL
    assert "工程转向模型" in service.mode_label


def test_the_legacy_models_are_still_constructible_for_regression(redesigned_service):
    """历史机构不再是正式分支，但仍可构造，供回归与对照使用。"""
    assert redesigned_service.mechanical_mode == "REDESIGNED_ACKERMANN"
    assert "历史对照" in redesigned_service.mode_label



def test_as_built_service_keeps_the_customer_linkage(demo_service):
    assert demo_service.mechanical_mode == "AS_BUILT_REFERENCE"
    assert not demo_service.is_redesign


def test_caches_are_separated_between_the_two_modes(demo_service,
                                                    redesigned_service):
    assert demo_service.cache_dir != redesigned_service.cache_dir
    assert demo_service.mechanical_mode in str(demo_service.cache_dir)
    assert redesigned_service.mechanical_mode in str(redesigned_service.cache_dir)


def test_switching_mode_rebuilds_the_mechanism_and_clears_nothing_else():
    from steering_sim.demo.service import DemoService
    from pathlib import Path
    root = Path(__file__).parents[2]
    output = root / "outputs" / "_demo_test_tmp" / "mode_switch"
    service = DemoService(output_dir=output, mechanical_mode="AS_BUILT_REFERENCE")
    first = service.model
    service.set_mode("REDESIGNED_ACKERMANN")
    assert service.mechanical_mode == "REDESIGNED_ACKERMANN"
    assert service.model is not first
    assert service.runner.mechanical_mode == "REDESIGNED_ACKERMANN"
    service.set_mode("REDESIGNED_ACKERMANN")      # 幂等
    assert service.mechanical_mode == "REDESIGNED_ACKERMANN"


def test_unknown_mode_is_rejected():
    from steering_sim.j0_coupling.mechanism import UnknownMechanicalMode, normalise_mode
    with pytest.raises(UnknownMechanicalMode):
        normalise_mode("SOMETHING_ELSE")
    # 缺省（未指定）一律落到唯一正式模型。
    assert normalise_mode(None) == "ENGINEERING_STEERING_MODEL"


@pytest.mark.slow
def test_redesigned_run_reports_the_mode_and_correct_directions(redesigned_service):
    result = redesigned_service.run(SHORT, export=False)
    assert result.summary["mechanical_mode"] == "REDESIGNED_ACKERMANN"
    mechanism = result.summary["target_mechanism_wheel_angle_deg"]
    for axle in (4, 5, 6):
        left = mechanism[f"axle{axle}_left"]
        right = mechanism[f"axle{axle}_right"]
        assert left < -1.0 and right < -1.0, (axle, left, right)
    assert float(result.summary["third_axle_max_abs_deg"]) < 1.0e-9


@pytest.mark.slow
def test_as_built_run_still_shows_the_opposite_sign_defect(demo_service):
    result = demo_service.run(SHORT, export=False)
    mechanism = result.summary["target_mechanism_wheel_angle_deg"]
    assert mechanism["axle5_left"] * mechanism["axle5_right"] < 0.0


@pytest.mark.slow
def test_wheel_table_marks_the_defect_only_in_as_built_mode(demo_service,
                                                            redesigned_service):
    from steering_sim.demo.plots import wheel_table_rows
    as_built = demo_service.run(SHORT, export=False)
    redesigned = redesigned_service.run(SHORT, export=False)
    # 行格式是 (车桥, 左/右轮, ...)，所以键是 "右5桥" 这种形式。
    built_rows = {row[1] + row[0]: row[-1] for row in wheel_table_rows(as_built)}
    new_rows = {row[1] + row[0]: row[-1] for row in wheel_table_rows(redesigned)}
    built_states = [value for key, value in built_rows.items() if key.endswith("5桥")]
    new_states = [value for key, value in new_rows.items() if key.endswith("5桥")]
    assert built_states and new_states
    assert any("反号" in item for item in built_states), built_states
    assert all("反号" not in item for item in new_states), new_states


@pytest.mark.slow
def test_figures_of_a_redesigned_run_carry_the_design_proposal_banner(
        redesigned_service, scratch_dir):
    result = redesigned_service.run(SHORT, export=False)
    assert result.figures
    from steering_sim.demo.plots import MODE_BANNER
    assert "ENGINEERING_REDESIGN_PROPOSAL" in MODE_BANNER["REDESIGNED_ACKERMANN"]


@pytest.mark.slow
def test_redesigned_mode_accepts_a_large_target_that_the_old_model_refused(
        redesigned_service, demo_service):
    """±20° 在原始机构下被拒绝（超出真实可解范围），优化机构下必须能运行。"""
    from steering_sim.demo.assessment import assess_preflight
    old = assess_preflight(BIG, demo_service.runner)
    new = assess_preflight(BIG, redesigned_service.runner)
    assert not old.runnable
    assert new.runnable, new.blockers


def test_mode_disclaimer_text_is_present():
    from steering_sim.j0_coupling.mechanism import (AS_BUILT_REFERENCE,
                                                    ENGINEERING_STEERING_MODEL,
                                                    MODE_LABELS,
                                                    REDESIGNED_ACKERMANN,
                                                    REDESIGN_DISCLAIMER)
    assert "尚未通过实车验证" in REDESIGN_DISCLAIMER
    assert "工程转向模型" in MODE_LABELS[ENGINEERING_STEERING_MODEL]
    assert "历史对照" in MODE_LABELS[REDESIGNED_ACKERMANN]
    assert "历史对照" in MODE_LABELS[AS_BUILT_REFERENCE]
