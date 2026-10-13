"""Launch the real D4 window, execute the end-to-end flow and capture evidence."""
from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
import time

os.environ.setdefault("MPLBACKEND", "Agg")

ROOT = Path(__file__).resolve().parents[2]
for value in (ROOT, ROOT / "src"):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))

import pandas as pd
import pyqtgraph.exporters
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from steering_sim.desktop.app import MainWindow, STYLE
from steering_sim.desktop.reporting import write_report
from steering_sim.desktop.services import OUTPUT


class AcceptanceDriver:
    def __init__(self, app: QApplication, window: MainWindow) -> None:
        self.app = app
        self.window = window
        self.output = OUTPUT / "acceptance"
        self.screens = self.output / "screenshots"
        self.output.mkdir(parents=True, exist_ok=True)
        self.screens.mkdir(parents=True, exist_ok=True)
        self.records: list[dict] = []
        self.started = time.perf_counter()
        self.step = 0
        self.sequence = [
            (0, "01_joint_simulation", self.window.pages[0]._run),
            (1, "02_task_spectrum", None),
            (2, "03_degradation_prediction", self.window.pages[2]._run),
            (3, "04_quality_assessment", self.window.pages[3]._run),
            (4, "05_rul_prediction_result", self.window.pages[4]._run),
        ]
        self.window.controller.finished.connect(self.task_finished)
        self.window.controller.failed.connect(self.task_failed)

    def start(self) -> None:
        QTimer.singleShot(1200, self.run_step)

    def run_step(self) -> None:
        if self.step >= len(self.sequence):
            self.finish()
            return
        page_index, name, action = self.sequence[self.step]
        self.window.navigation.setCurrentRow(page_index)
        QApplication.processEvents()
        if action is None:
            QTimer.singleShot(500, lambda: self.capture_and_continue(name))
        else:
            action()

    def task_finished(self, task_id: str, result: object) -> None:
        expected = self.sequence[self.step][1]
        QTimer.singleShot(700, lambda: self.capture_and_continue(expected))

    def task_failed(self, task_id: str, message: str, detail: str) -> None:
        (self.output / "FAILED.txt").write_text(
            f"{task_id}: {message}\n{detail}", encoding="utf-8")
        self.app.exit(2)

    def capture_and_continue(self, name: str) -> None:
        QApplication.processEvents()
        target = self.screens / f"{name}.png"
        pixmap = QApplication.primaryScreen().grabWindow(int(self.window.winId()))
        saved = pixmap.save(str(target), "PNG")
        self.records.append({"page": name, "path": str(target),
                             "saved": bool(saved), "width": pixmap.width(),
                             "height": pixmap.height(),
                             "elapsed_s": time.perf_counter() - self.started})
        self.step += 1
        QTimer.singleShot(350, self.run_step)

    def finish(self) -> None:
        self.window._sync_project()
        project_path = self.output / "D4_acceptance_project.d4project.json"
        self.window.project.name = "D4完整流程验收工程"
        self.window.project.save(project_path)
        report_path = write_report(
            self.output / "D4_comprehensive_report_sample.md",
            asdict(self.window.project), self.window.results,
            self.window.project.provenance)
        # Export a real result table and interactive plot snapshot without dialogs.
        rul = self.window.results.get("rul", {})
        if isinstance(rul.get("history"), pd.DataFrame):
            rul["history"].to_excel(self.output / "mission_cycle_history_sample.xlsx",
                                    index=False)
        plot = self.window.pages[4].damage_plot
        exporter = pyqtgraph.exporters.ImageExporter(plot.plotItem)
        exporter.parameters()["width"] = 1600
        exporter.export(str(self.output / "rul_damage_chart_sample.png"))
        payload = {
            "status": "PASS", "screenshots": self.records,
            "completed_modules": dict(self.window.project.completed_modules),
            "project": str(project_path), "report": str(report_path),
            "runtime_s": time.perf_counter() - self.started,
            "real_qt_window_capture": True,
            "capture_method": "QScreen.grabWindow(MainWindow.winId)",
        }
        (self.output / "gui_acceptance.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        QTimer.singleShot(250, self.app.quit)


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    window = MainWindow()
    window.showMaximized()
    driver = AcceptanceDriver(app, window)
    driver.start()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
