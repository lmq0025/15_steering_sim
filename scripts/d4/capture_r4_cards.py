"""Actual Qt/QThread acceptance of R4 page-03 cards, fresh official forecasts.

Runs deterministic, Gamma-128, Gamma-1000, then a repeated Gamma-128 forecast.
The final stages exercise project restore, cooperative cancellation and an
invalid mission through the same production controller.  No old result CSV is
used as a substitute for a new forecast.  Screenshots are actual QScreen pixels.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
EXPECTED_PYTHON = Path(r"E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe")
assert Path(sys.executable) == EXPECTED_PYTHON, sys.executable

import numpy as np
import pandas as pd
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QTextBrowser

from steering_sim.desktop.app import MainWindow, STYLE
from steering_sim.desktop.services import DesktopCalculationService, EXAMPLE_SPECTRUM, OUTPUT


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/desktop/r4/cards_gui")
    args = parser.parse_args()
    out = args.output.resolve()
    if (out / "acceptance.json").exists():
        raise FileExistsError(f"Refuse overwriting existing acceptance evidence: {out}. Choose a new --output directory.")
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setFont(QFont("Microsoft YaHei UI", 11))
    app.setStyleSheet(STYLE)
    window = MainWindow()
    window.service = DesktopCalculationService(out / "calculations")
    window.showMaximized()
    window.navigation.setCurrentRow(2)
    page = window.pages[2]
    records, tasks, lifecycle, errors, heartbeat = [], [], [], [], []
    state = {"phase": "initial", "task_started": 0.0, "finished": False,
             "expected_error_dialog_seen": False}
    started = time.perf_counter()
    original_spectrum = pd.read_csv(EXAMPLE_SPECTRUM)
    working_file = OUTPUT / "working_task_spectrum.csv"
    previous_working_bytes = working_file.read_bytes() if working_file.exists() else None
    if previous_working_bytes is not None:
        (out / "preexisting_working_spectrum.csv").write_bytes(previous_working_bytes)
    protected_paths = (ROOT / "configs/degradation/d1_degradation_models.json",
                       ROOT / "configs/degradation/d3_rul_models.json",
                       ROOT / "configs/j1r2/engineering_hydraulics.json")
    protected = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                 for path in protected_paths}

    def write_json(name, value):
        (out / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

    def shot(name, widget=None):
        app.processEvents()
        widget = window if widget is None else widget
        path = out / f"{name}.png"
        assert app.primaryScreen().grabWindow(int(widget.winId())).save(str(path)), str(path)
        records.append(path.name)

    def safe_exit(code):
        if window.controller.busy:
            window.controller.request_cancel()
            QTimer.singleShot(100, lambda: safe_exit(code))
        else:
            if previous_working_bytes is not None:
                working_file.write_bytes(previous_working_bytes)
            else:
                original_spectrum.to_csv(working_file, index=False, encoding="utf-8-sig")
            window.close()
            app.exit(code)

    def fail(message, detail=""):
        if state["finished"]:
            return
        state["finished"] = True
        errors.append(str(message))
        (out / "failure.txt").write_text(str(detail or message), encoding="utf-8")
        write_json("acceptance.json", dict(status="FAIL", phase=state["phase"],
                   message=str(message), tasks=tasks, screenshots=records, errors=errors))
        print(f"FAIL {message}\n{detail}", flush=True)
        safe_exit(2)

    def guard(callback):
        def wrapped(*values):
            if state["finished"]:
                return
            try:
                callback(*values)
            except Exception as exc:
                fail(str(exc), traceback.format_exc())
        return wrapped

    def later(callback, delay=350):
        QTimer.singleShot(delay, guard(callback))

    def card_texts():
        return [card.value_label.text() for card in (page.pump_card, page.valve_card, page.cylinder_card)]

    def assert_empty(label):
        assert card_texts() == [label] * 3, card_texts()
        assert page.last_result is None and "degradation" not in window.results
        assert page.final_parameter_table.frame.empty
        assert not any(button.isEnabled() for button in page.card_detail_buttons.values())

    def dialog_path(method, path, callback):
        old = getattr(QFileDialog, method)
        setattr(QFileDialog, method, lambda *a, **k: (str(path), ""))
        try:
            callback()
        finally:
            setattr(QFileDialog, method, old)

    def verify_summaries(result):
        # Compare UI values with the same service output AND its persisted raw
        # parameter statistics.  Neither card text nor rounding is the oracle.
        expected = pd.read_csv(Path(result["output_dir"]) / "raw/prediction_intervals.csv")
        final = expected.loc[expected.day == expected.day.max()].set_index("metric")
        column = page.center.currentData() if result["sample_count"] else "deterministic"
        assert result["curve_frame"].day.iloc[-1] == 30
        assert window.results["degradation"] is page.last_result
        for summary in page.component_summaries.values():
            assert np.isclose(summary.numeric_value, final.at[summary.metric, column], rtol=2e-14, atol=0)
        if result["sample_count"]:
            assert result["paths"].shape[1:] == (result["sample_count"], 20)
        return {kind: asdict(value) for kind, value in page.component_summaries.items()}

    def run_forecast(phase, count):
        state["phase"] = phase
        window.navigation.setCurrentRow(2)
        page.tabs.setCurrentIndex(0)
        page.forecast_mode.setCurrentIndex(int(count > 0))
        page.sample_count.setValue(count or 128)
        page.seed.setValue(20261013)
        page.initial.setCurrentIndex(page.initial.findData("healthy"))
        page._run()

    @guard
    def task_started(task):
        state["task_started"] = time.perf_counter()
        assert task == "degradation"
        assert_empty("正在预测")
        lifecycle.append(dict(phase=state["phase"], status="正在预测"))
        print(f"START {state['phase']}", flush=True)
        if state["phase"] == "cancel":
            # TaskController emits started before its QThread starts. The
            # production cancellation flag is applied immediately and handled
            # by the first safe checkpoint; no service is stubbed.
            window.controller.request_cancel()

    @guard
    def task_done(task, result):
        assert task == "degradation" and result
        assert state["phase"] not in ("cancel", "invalid_input")
        actual = verify_summaries(result)
        tasks.append(dict(phase=state["phase"], sample_count=result["sample_count"],
                          gui_task_wall_s=time.perf_counter() - state["task_started"],
                          service_runtime_s=result["runtime_s"], output_dir=result["output_dir"],
                          cards=actual, center=page.center.currentData(),
                          input_hash=result["provenance"].get("spectrum_sha256")))
        print(f"DONE {state['phase']} {tasks[-1]['gui_task_wall_s']:.3f}s", flush=True)
        later(lambda: after_forecast(result))

    def after_forecast(result):
        phase = state["phase"]
        page.component.setCurrentIndex(page.component.findData("pump:front"))
        page.view_mode.setCurrentIndex(1)
        page.metric.setCurrentIndex(page.metric.findData("volumetric_efficiency"))
        page.show_band.setChecked(True)
        page.show_paths.setChecked(bool(result["sample_count"]))
        if phase == "deterministic":
            shot("01_确定性预测_三类真实结果摘要")
            later(lambda: run_forecast("gamma_128", 128))
        elif phase == "gamma_128":
            shot("02_Gamma128_三类随机均值摘要")
            later(lambda: run_forecast("gamma_1000", 1000))
        elif phase == "gamma_1000":
            page.path_count.setCurrentIndex(page.path_count.findData(10))
            shot("03_Gamma1000_真实均值卡片与区间")
            before = hashlib.sha256(result["paths"].tobytes()).hexdigest()
            page.center.setCurrentIndex(page.center.findData("p50"))
            p50 = verify_summaries(result)
            page.component.setCurrentIndex(page.component.findData("valve:channel_front"))
            page.metric.setCurrentIndex(page.metric.findData("lag_scale"))
            assert hashlib.sha256(result["paths"].tobytes()).hexdigest() == before
            shot("04_Gamma1000_P50卡片与阀迟滞")
            QTest.mouseClick(page.card_detail_buttons["valve"], Qt.LeftButton)
            assert page.tabs.currentWidget() is page.final_parameter_table
            shot("05_卡片详细参数_同次第30天P50")
            for suffix in ("csv", "xlsx"):
                page.final_parameter_table.export(out / f"第30天物理参数_P50.{suffix}")
            page.final_parameter_table.export(out / "第30天物理参数_raw.csv", raw=True)
            write_json("card_values_1000.json", dict(mean=tasks[-1]["cards"], p50=p50,
                       sample_count=1000, random_seed=result["random_seed"],
                       reference_conditions=result["reference_conditions"],
                       unchanged_paths_sha256=before, source=result["output_dir"]))
            page.tabs.setCurrentIndex(0)
            dialog_path("getSaveFileName", out / "03本次计算中文报告.md", window.export_report)
            browser = QTextBrowser(window)
            browser.setWindowFlags(browser.windowFlags() | Qt.Window)
            browser.setWindowTitle("本次真实1000路径计算的中文报告")
            browser.resize(1200, 850)
            browser.setMarkdown((out / "03本次计算中文报告.md").read_text("utf-8"))
            browser.show()
            shot("06_本次计算中文报告", browser)
            browser.close()
            window._sync_project()
            project = out / "三类卡片验收工程.d4project.json"
            window.project.save(project)
            dialog_path("getOpenFileName", project, window.open_project)
            assert page.center.currentData() == "p50" and page.sample_count.value() == 1000
            assert_empty("待计算")
            shot("07_工程恢复_输入已保留历史结果不冒充新计算")
            lifecycle.append(dict(phase="project_restore", status="待计算", center="p50", samples=1000))
            later(lambda: run_forecast("repeat_128", 128))
        elif phase == "repeat_128":
            assert result["sample_count"] == 128
            assert "128条路径" in page.pump_card.note_label.text()
            assert "随机P50" in page.pump_card.note_label.text()
            shot("08_重复预测128_已替换上次1000结果")
            later(lambda: run_forecast("cancel", 1000))

    @guard
    def task_cancelled(task, message):
        assert task == "degradation" and state["phase"] == "cancel", (task, message)
        assert_empty("已取消")
        lifecycle.append(dict(phase="cancel", status="已取消", message=message,
                              wall_s=time.perf_counter() - state["task_started"]))
        shot("09_后台取消_三类卡片已取消且无旧数据")
        # Edit the in-memory mission table used by the real GUI. A non-positive
        # duration must be rejected by official mission validation in the worker.
        # The distributed example has Chinese headings. Normalize before
        # changing the machine field, otherwise this test itself creates two
        # aliases for the duration column instead of a zero-duration segment.
        from steering_sim.degradation.spectrum import normalize_columns
        invalid = normalize_columns(original_spectrum.copy())
        invalid.loc[0, "segment_duration_s"] = 0
        window.pages[1].load_frame(invalid)
        later(lambda: run_forecast("invalid_input", 128))

    @guard
    def task_failed(task, message, detail):
        if state["phase"] != "invalid_input":
            fail(message, detail)
            return
        assert task == "degradation"
        assert_empty("计算失败")
        assert "SpectrumError" in message or "持续时间" in message or "duration" in message
        lifecycle.append(dict(phase="invalid_input", status="计算失败", message=message,
                              wall_s=time.perf_counter() - state["task_started"]))
        (out / "expected_input_error.txt").write_text(detail, encoding="utf-8")
        later(finish)

    def finish():
        assert state["expected_error_dialog_seen"]
        shot("10_错误输入_三类卡片计算失败且无旧结果")
        assert [t["sample_count"] for t in tasks] == [0, 128, 1000, 128]
        assert all(hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest
                   for path, digest in protected.items())
        write_json("acceptance.json", dict(
            status="PASS", method="Actual Qt MainWindow + production QThread services + QScreen.grabWindow",
            python=sys.executable, screenshots=records, tasks=tasks, lifecycle=lifecycle,
            wall_s=time.perf_counter() - started, protected_hashes=protected,
            source_spectrum=str(EXAMPLE_SPECTRUM), fresh_forecasts=4,
            project_restore_preserves_inputs_not_stale_results=True,
            display_switch_reuses_same_paths=True,
            expected_validation_error=True, cooperative_cancellation=True,
            maximum_busy_heartbeat_gap_s=max(
                [b[1] - a[1] for a, b in zip(heartbeat, heartbeat[1:]) if a[0] and a[0] == b[0]] or [0.0]),
        ))
        state["finished"] = True
        print(f"PASS {out / 'acceptance.json'}", flush=True)
        safe_exit(0)

    def tick():
        heartbeat.append((state["phase"] if window.controller.busy else None, time.perf_counter()))
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, QMessageBox) and widget.isVisible() and widget.windowTitle() == "计算失败":
                if state["phase"] == "invalid_input":
                    state["expected_error_dialog_seen"] = True
                # Acknowledge only this script's application's calculation error
                # dialog; no system permission/authentication dialog is touched.
                widget.accept()

    pulse = QTimer(window)
    pulse.timeout.connect(tick)
    pulse.start(50)
    window.controller.started.connect(task_started)
    window.controller.finished.connect(task_done)
    window.controller.failed.connect(task_failed)
    window.controller.cancelled.connect(task_cancelled)
    sys.excepthook = lambda kind, value, tb: fail(str(value), "".join(traceback.format_exception(kind, value, tb)))
    QTimer.singleShot(600000, lambda: fail("Qt卡片验收超过10分钟，未宣称通过"))
    window.pages[1].load_frame(original_spectrum, str(EXAMPLE_SPECTRUM))
    later(lambda: run_forecast("deterministic", 0), 800)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
