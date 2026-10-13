from __future__ import annotations

import os
from pathlib import Path
import time

import pandas as pd
from PySide6.QtWidgets import QApplication

from steering_sim.desktop.app import MainWindow
from steering_sim.desktop.models import ProjectState
from steering_sim.desktop.reporting import build_report
from steering_sim.desktop.services import (DesktopCalculationService,
                                             EXAMPLE_SPECTRUM, HEALTHY,
                                             file_hash)
from steering_sim.desktop.worker import TaskController

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def app():
    return QApplication.instance() or QApplication([])


def test_five_pages_and_chinese_navigation():
    qt = app()
    window = MainWindow()
    assert window.stack.count() == 5
    assert [window.navigation.item(i).text() for i in range(5)] == [
        "01  联合仿真", "02  任务载荷谱", "03  部件退化预测",
        "04  当前质量评估", "05  剩余任务循环预测"]
    window.close()


def test_spectrum_example_loads_and_is_exactly_30_days():
    service = DesktopCalculationService()
    result = service.validate_spectrum(EXAMPLE_SPECTRUM)
    assert result["valid"]
    assert result["status"] == "等于30天"
    assert result["segment_count"] == 330


def test_invalid_spectrum_has_explicit_error():
    path = Path("outputs/desktop/test_temp/bad.csv")
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"segment_id": ["BAD"]}).to_csv(path, index=False)
    result = DesktopCalculationService().validate_spectrum(path)
    assert not result["valid"]
    assert result["status"] == "数据异常"
    assert result["risks"]


def test_csv_and_xlsx_spectrum_inputs_are_equivalent():
    source = pd.read_csv(EXAMPLE_SPECTRUM)
    target = Path("outputs/desktop/test_temp/中文任务谱.xlsx")
    target.parent.mkdir(parents=True, exist_ok=True)
    source.to_excel(target, index=False)
    csv_result = DesktopCalculationService().validate_spectrum(EXAMPLE_SPECTRUM)
    xlsx_result = DesktopCalculationService().validate_spectrum(target)
    assert xlsx_result["valid"]
    assert xlsx_result["segment_count"] == csv_result["segment_count"]
    assert xlsx_result["days"] == csv_result["days"]


def test_project_roundtrip_and_no_result_injection():
    path = Path("outputs/desktop/test_temp/工程.d4project.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    state = ProjectState(name="中文工程", spectrum_path=str(EXAMPLE_SPECTRUM),
                         page_inputs={"rul": {"maximum_cycles": 240}})
    state.save(path)
    loaded = ProjectState.load(path)
    assert loaded.name == "中文工程"
    assert loaded.result_paths == {}
    assert loaded.page_inputs["rul"]["maximum_cycles"] == 240


def test_saved_page_inputs_restore_without_old_results():
    qt = app()
    source = MainWindow()
    source.pages[0].speed.setValue(17.5)
    source.pages[3].source.setCurrentIndex(2)
    source.pages[4].max_cycles.setValue(321)
    source.pages[4].samples.setValue(64)
    source.project.page_inputs["_project_file"] = "工程.d4project.json"
    source._sync_project()
    payload = dict(source.project.page_inputs)
    assert payload["_project_file"] == "工程.d4project.json"
    source.close()

    restored = MainWindow()
    restored._apply_page_inputs(payload)
    assert restored.pages[0].speed.value() == 17.5
    assert restored.pages[3].source.currentData() == "specified_medium"
    assert restored.pages[4].max_cycles.value() == 321
    assert restored.pages[4].samples.value() == 64
    assert restored.results == {}
    restored.close()


def test_report_only_contains_executed_modules():
    report = build_report({"name": "验收", "spectrum_path": "x.csv"},
                          {"simulation": {"calculation_success": True,
                                           "tracking_pass": True,
                                           "trajectory_feasible": True,
                                           "runtime_s": 1.0}},
                          {"model": "ENGINEERING_HYDRAULIC_V1"})
    assert "联合仿真" in report
    assert "以下模块本工程尚未执行" in report
    assert "剩余完整30天任务：130" not in report


def test_background_controller_keeps_event_loop_responsive():
    qt = app()
    controller = TaskController()
    result = []

    def task(progress, is_cancelled):
        for index in range(4):
            time.sleep(0.02)
            progress(index / 4, "后台")
        return {"ok": True}

    controller.finished.connect(lambda task_id, value: result.append(value))
    assert controller.start("test", task)
    ticks = 0
    deadline = time.time() + 2
    while not result and time.time() < deadline:
        qt.processEvents()
        ticks += 1
        time.sleep(0.002)
    assert ticks > 5
    assert result == [{"ok": True}]
    controller.shutdown()


def test_background_task_cancels_at_safe_checkpoint():
    qt = app()
    controller = TaskController()
    cancelled = []

    def task(progress, is_cancelled):
        for index in range(100):
            if is_cancelled():
                return {}
            time.sleep(0.005)
            progress(index / 100, "可取消任务")
        return {"unexpected": True}

    controller.cancelled.connect(lambda task_id, message: cancelled.append((task_id, message)))
    assert controller.start("cancel-test", task)
    deadline = time.time() + 2
    while not controller.busy and time.time() < deadline:
        qt.processEvents()
    controller.request_cancel()
    while not cancelled and time.time() < deadline:
        qt.processEvents()
        time.sleep(0.002)
    assert cancelled and cancelled[0][0] == "cancel-test"
    controller.shutdown()


def test_healthy_baseline_hash_not_changed_by_ui_startup():
    before = file_hash(HEALTHY)
    qt = app()
    window = MainWindow()
    window.close()
    assert file_hash(HEALTHY) == before
