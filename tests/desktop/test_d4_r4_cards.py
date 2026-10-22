"""R4 result-card values/state follow one real official forecast, never old data."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import os

import numpy as np
import pandas as pd
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication

from steering_sim.degradation import (
    MultiModeDegradationState, component_mode_rows, load_d3_config,
    parameters_from_multimode,
)
from steering_sim.degradation.forecast import mission_forecast
from steering_sim.degradation.rul import MissionCycleProfile, MissionSegmentExposure
from steering_sim.desktop.degradation_cards import final_component_summary
from steering_sim.desktop.pages import DegradationPage
from steering_sim.hydraulics_engineering import load_parameters


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def qt():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module", params=[0, 128, 1000])
def forecast(request):
    """Synthetic exposure fixture through unchanged D3 equations and mapping.

    Unequal initial component states make incorrect component selection visible;
    official coefficients and actual 128/1000 independent paths are retained.
    """
    config = load_d3_config(ROOT / "configs/degradation/d3_rul_models.json")
    healthy = load_parameters(ROOT / "configs/j1r2/engineering_hydraulics.json")
    initial = MultiModeDegradationState.healthy()
    for key, damage in (("pump:rear:leakage_wear", .25),
                        ("valve:channel_rear_2:response_lag", .3),
                        ("cylinder:channel_rear_3:friction_growth", .4)):
        initial = initial.with_mode(key, replace(initial.modes[key], damage=damage))
    exposures = {key: 30.0 for key in initial.modes}
    profile = MissionCycleProfile(tuple(
        MissionSegmentExposure(f"TEST-{day}", 1, day * 86400, day, exposures)
        for day in (10, 20, 30)), {}, {}, ())
    result = mission_forecast(profile, initial, healthy, config,
                              sample_count=request.param, random_seed=21)
    parameters = parameters_from_multimode(healthy, result["final_state"], config)
    result.update(
        kind="degradation", models=config.raw["modes"], risks=[],
        component_frame=pd.DataFrame(component_mode_rows(result["final_state"], config, parameters)),
        rainflow_frame=pd.DataFrame(), checkpoint_frame=result["statistics"].copy(),
    )
    return result


def test_cards_use_same_final_physical_stats_and_export(qt, forecast, tmp_path):
    page = DegradationPage()
    assert page.pump_card.value_label.text() == "待计算"
    page.task_started()
    assert page.pump_card.value_label.text() == "正在预测"
    page.task_finished(forecast)
    center = "mean" if forecast["sample_count"] else "deterministic"
    expected = forecast["statistics"].query("day == 30").set_index("metric")
    for kind, metric in (
        ("pump", "pump:rear:volumetric_efficiency"),
        ("valve", "valve:channel_rear_2:lag_scale"),
        ("cylinder", "cylinder:channel_rear_3:friction_scale"),
    ):
        summary = page.component_summaries[kind]
        assert summary.metric == metric
        assert summary.numeric_value == expected.at[metric, center]
        assert ("随机均值" if forecast["sample_count"] else "确定性值") in summary.note
        assert "第30天" in summary.note
        page.card_detail_buttons[kind].click()
        assert page.tabs.currentWidget() is page.final_parameter_table
        assert page.final_parameter_table.proxy.rowCount() > 0
    raw = tmp_path / "final_physical_raw.csv"
    page.final_parameter_table.export(raw, raw=True)
    exported = pd.read_csv(raw).set_index("metric")
    for summary in page.component_summaries.values():
        assert exported.at[summary.metric, "value"] == pytest.approx(summary.numeric_value, rel=1e-14)
    # Real path counts are retained; card selection never resamples.
    if forecast["sample_count"]:
        assert forecast["paths"].shape == (4, forecast["sample_count"], 20)
    page.close()


def test_view_changes_and_repeat_lifecycle_keep_only_current_result(qt, forecast):
    page = DegradationPage()
    page.task_finished(forecast)
    original_stats = forecast["statistics"].copy(deep=True)
    original_paths = None if forecast["paths"] is None else forecast["paths"].copy()
    page.center.setCurrentIndex(1)
    page.component.setCurrentIndex(5)
    page.view_mode.setCurrentIndex(1)
    page.path_count.setCurrentIndex(1)
    page.show_paths.setChecked(True)
    assert page.last_result is forecast
    expected = original_stats.query("day == 30").set_index("metric")
    column = "p50" if forecast["sample_count"] else "deterministic"
    for summary in page.component_summaries.values():
        assert summary.numeric_value == expected.at[summary.metric, column]
    pd.testing.assert_frame_equal(original_stats, forecast["statistics"])
    if original_paths is not None:
        np.testing.assert_array_equal(original_paths, forecast["paths"])
        assert "随机P50" in page.pump_card.note_label.text()
        # Representative paths may be outside the central pointwise band;
        # auto-range must show their actual extrema, not crop them to P2.5/P97.5.
        shown = page.path_table.frame["value"].to_numpy(float)
        bottom, top = page.damage_plot.getViewBox().viewRange()[1]
        assert bottom <= shown.min() <= shown.max() <= top
    page.task_started()
    assert page.last_result is None and page.final_parameter_table.frame.empty
    assert not any(button.isEnabled() for button in page.card_detail_buttons.values())
    page.task_cancelled()
    assert page.pump_card.value_label.text() == "已取消"
    page.task_started()
    page.task_finished(forecast)
    assert page.pump_card.value_label.text() != "未计算"
    page.task_failed("任务谱输入错误")
    assert page.last_result is None and page.component_summaries == {}
    assert page.pump_card.value_label.text() == "计算失败"
    assert page.final_parameter_table.frame.empty
    page.invalidate_result("工程输入已恢复，历史结果不作为本次计算")
    assert page.pump_card.value_label.text() == "待计算"
    page.close()


def test_missing_or_invalid_final_stats_never_fallback_to_healthy(forecast):
    broken = dict(forecast)
    broken["statistics"] = forecast["statistics"].loc[
        forecast["statistics"].metric != "pump:rear:volumetric_efficiency"]
    with pytest.raises(ValueError, match="缺失"):
        final_component_summary(broken)
    broken["statistics"] = forecast["statistics"].query("day < 30")
    with pytest.raises(ValueError, match="第30天"):
        final_component_summary(broken)


def test_saved_settings_restore_without_reviving_old_cards(qt, forecast, tmp_path):
    from steering_sim.desktop.app import MainWindow
    from steering_sim.desktop.models import ProjectState
    window = MainWindow()
    page = window.pages[2]
    page.task_finished(forecast)
    page.center.setCurrentIndex(1)
    page.forecast_mode.setCurrentIndex(int(forecast["sample_count"] > 0))
    page.sample_count.setValue(forecast["sample_count"] or 128)
    state = ProjectState(page_inputs={"degradation": page.project_payload()})
    path = tmp_path / "卡片口径工程.d4project.json"
    state.save(path)
    page.invalidate_result("工程输入已恢复，历史结果不作为本次计算")
    window._apply_page_inputs(ProjectState.load(path).page_inputs)
    assert page.center.currentData() == "p50"
    assert page.last_result is None
    assert page.pump_card.value_label.text() == "待计算"
    page.task_started()
    page.task_finished(forecast)
    assert "随机P50" in page.pump_card.note_label.text() if forecast["sample_count"] else "确定性值" in page.pump_card.note_label.text()
    window.close()
