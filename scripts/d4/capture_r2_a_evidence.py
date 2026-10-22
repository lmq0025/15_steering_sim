"""Capture the current R2-A Qt window, retaining R1 evidence unchanged."""
import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
from capture_d4_r1_evidence import Driver, MainWindow, STYLE

app = QApplication(sys.argv)
app.setStyleSheet(STYLE)
window = MainWindow()
window.showMaximized()
driver = Driver(app, window)
driver.output = Path(__file__).resolve().parents[2] / 'outputs/desktop/r2/a/gui_reference_step'
driver.output.mkdir(parents=True, exist_ok=True)
driver.start()
raise SystemExit(app.exec())
