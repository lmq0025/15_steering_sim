"""Run a real 6 s/deg Qt workflow and capture D4-R1 window evidence."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
import time

os.environ.setdefault("MPLBACKEND", "Agg")
ROOT = Path(__file__).resolve().parents[2]
for value in (ROOT, ROOT / "src"):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from steering_sim.desktop.app import MainWindow, STYLE


class Driver:
    def __init__(self, app: QApplication, window: MainWindow) -> None:
        self.app, self.window = app, window
        self.output = ROOT / "outputs" / "desktop" / "r1"
        self.output.mkdir(parents=True, exist_ok=True)
        self.started = time.perf_counter()
        self.records = []
        window.controller.finished.connect(self.finished)
        window.controller.failed.connect(self.failed)

    def start(self) -> None:
        page = self.window.pages[0]
        self.window.navigation.setCurrentRow(0)
        page.command_type.setCurrentIndex(1)
        page.initial_angle.setValue(0.0)
        page.angle.setValue(2.0)
        page.seconds_per_degree.setValue(6.0)
        page.hold_observation.setValue(5.0)
        QTimer.singleShot(1200, page._run)

    def capture(self, name: str) -> None:
        QApplication.processEvents()
        path = self.output / name
        pixmap = QApplication.primaryScreen().grabWindow(int(self.window.winId()))
        saved = pixmap.save(str(path), "PNG")
        self.records.append({"path": str(path), "saved": bool(saved),
                             "width": pixmap.width(), "height": pixmap.height()})

    def finished(self, task_id: str, result: object) -> None:
        if task_id != "simulation":
            return
        page = self.window.pages[0]
        for index, name in ((0, "ramp_wheel_dynamics.png"),
                            (1, "ramp_cylinder_dynamics.png"),
                            (2, "ramp_wheel_response_table.png"),
                            (3, "ramp_cylinder_response_table.png")):
            page.tabs.setCurrentIndex(index)
            self.capture(name)
        result = dict(result)
        response = result["response"]
        result["wheel_response_table"].to_csv(
            self.output / "wheel_response_times_0_to_2.csv", index=False,
            encoding="utf-8-sig")
        result["cylinder_response_table"].to_csv(
            self.output / "cylinder_response_times_0_to_2.csv", index=False,
            encoding="utf-8-sig")
        shutil.copy2(result["csv_path"], self.output / "ramp_timeseries_0_to_2.csv")
        payload = {
            "status": "PASS", "real_qt_window_capture": True,
            "case": "0deg_to_+2deg", "seconds_per_degree": 6.0,
            "command_completion_s": response["command_completion_s"],
            "all_wheels_settled_s": response["all_wheels_settled_s"],
            "all_cylinders_settled_s": response["all_cylinders_settled_s"],
            "system_settled_s": response["system_settled_s"],
            "simulation_wall_s": result["runtime_s"],
            "workflow_wall_s": time.perf_counter() - self.started,
            "screenshots": self.records,
        }
        (self.output / "ramp_gui_acceptance.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        QTimer.singleShot(300, self.app.quit)

    def failed(self, task_id: str, message: str, detail: str) -> None:
        (self.output / "ramp_gui_FAILED.txt").write_text(
            f"{task_id}: {message}\n{detail}", encoding="utf-8")
        self.app.exit(2)


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    window = MainWindow()
    window.showMaximized()
    driver = Driver(app, window)
    driver.start()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
