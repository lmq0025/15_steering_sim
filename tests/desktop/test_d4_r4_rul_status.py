"""Presentation-only regression: no lifetime is inferred from status labels."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from copy import deepcopy

import pandas as pd
import pytest
from PySide6.QtWidgets import QApplication

from steering_sim.desktop.pages import RULPage
from steering_sim.desktop.reporting import build_report
from steering_sim.desktop.rul_presentation import rul_outcome_text


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def summary(status):
    record = dict(prediction_status=status, remaining_complete_30day_cycles=None,
                  first_failure_cycle=None, first_failure_segment_id=None,
                  first_failure_day_in_cycle=None, limiting_factors=[], failure_reasons=[])
    if status == "FAILURE_REACHED":
        record.update(remaining_complete_30day_cycles=130, first_failure_cycle=131,
                      first_failure_segment_id="D07-S07", first_failure_day_in_cycle=6.465278,
                      limiting_factors=["valve:channel_front"])
    elif status == "FAILURE_BRACKETED":
        record.update(remaining_complete_30day_cycles=33, first_failure_cycle=66,
                      first_failure_segment_id="DYNAMIC_CHECKPOINT", first_failure_day_in_cycle=30.,
                      system_quality_failure_cycle_interval=[33, 66],
                      limiting_factors=["system_quality"])
    return record


def result_for(status):
    return dict(kind="rul", summary=summary(status),
                history=pd.DataFrame(columns=["mission_cycle"]), quality=pd.DataFrame(),
                modes=pd.DataFrame(), mc_samples=pd.DataFrame(columns=["failure_cycle"]),
                mc_summary=pd.DataFrame(columns=["metric", "value"]))


@pytest.mark.parametrize("status,expected", [
    ("FAILURE_REACHED", "130 次"),
    ("FAILURE_BRACKETED", "已检安全下界 33 次"),
    ("NOT_REACHED_WITHIN_HORIZON", "预测范围内未失效"),
    ("INDETERMINATE", "无法确定"),
])
def test_cards_and_report_share_status_semantics_without_changing_result(qt_app, monkeypatch, status, expected):
    page = RULPage()
    # This test isolates terminal wording; real plot integration has dedicated
    # tests and must not need an expensive prediction just to check four labels.
    monkeypatch.setattr(page.random_view, "set_result", lambda *_: None)
    result = result_for(status)
    original = deepcopy(result["summary"])
    page.task_finished(result)
    assert page.cycles_card.value_label.text() == expected
    report = build_report({}, {"rul": result}, {})
    assert expected in report
    texts = "\n".join([page.cycles_card.note_label.text(), page.failure_card.value_label.text(),
                       page.failure_card.note_label.text(), page.banner.label.text(), report])
    assert "None" not in texts
    assert "DYNAMIC_CHECKPOINT" not in texts
    assert result["summary"] == original
    if status == "FAILURE_REACHED":
        assert page.failure_card.value_label.text() == "第131次任务"
        assert "D07-S07段末检测；第6.465278天" in texts
        assert "不是段内精确失效瞬间" in texts
    elif status == "FAILURE_BRACKETED":
        assert "（33, 66]" in texts
        assert "不是精确求得" in texts
        assert "段末检测" not in texts
        assert "30.000000" not in texts
    elif status == "INDETERMINATE":
        assert page.failure_card.value_label.text() == "尚无法判断"
        assert "未检测到越限" not in texts
        assert "预测范围内未失效" not in texts
    else:
        assert "预测上限不是真实剩余寿命" in texts
    page.close()


def test_bracket_prefers_explicit_verified_interval_and_supports_saved_old_results():
    record = summary("FAILURE_BRACKETED")
    record["system_quality_failure_cycle_interval"] = [40, 60]
    assert rul_outcome_text(record)["complete_value"] == "已检安全下界 40 次"
    assert "（40, 60]" in rul_outcome_text(record)["failure_note"]
    record.pop("system_quality_failure_cycle_interval")
    assert "（33, 66]" in rul_outcome_text(record)["failure_note"]
    record.update(remaining_complete_30day_cycles=0, first_failure_cycle=0)
    assert "初始质量检查" in rul_outcome_text(record)["failure_note"]


def test_missing_detection_day_or_segment_does_not_invent_a_time():
    record = summary("FAILURE_REACHED")
    record["first_failure_day_in_cycle"] = None
    assert rul_outcome_text(record)["failure_note"] == "D07-S07段末检测"
    record["first_failure_segment_id"] = None
    assert "段末检测" not in rul_outcome_text(record)["failure_note"]
    assert "未记录可定位的任务段" in rul_outcome_text(record)["failure_note"]


def test_no_failure_quality_report_does_not_call_final_checkpoint_end_of_life():
    result = result_for("NOT_REACHED_WITHIN_HORIZON")
    result["quality"] = pd.DataFrame([dict(mission_cycle=0, rated_quality_grade="HEALTHY"),
                                      dict(mission_cycle=5, rated_quality_grade="HEALTHY")])
    report = build_report({}, {"rul": result}, {})
    assert "末个真实动力学检查点等级：健康" in report
    assert "寿命临界检查点" not in report
