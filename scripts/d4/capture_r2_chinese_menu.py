"""Capture an application-owned, exposed native Qt menu after repaint."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'src'))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer,QPoint
from steering_sim.desktop.app import MainWindow,STYLE
app=QApplication([]);app.setStyleSheet(STYLE);window=MainWindow();window.showMaximized()
window.navigation.setCurrentRow(2)
menu=window.pages[2].damage_plot.chinese_context_menu()
def capture():
    image=menu.grab()
    if image.isNull():raise RuntimeError('Native menu screenshot unavailable')
    image.save(str(ROOT/'outputs/desktop/r2/gui/19_真实中文图表菜单.png'))
    menu.close();window.close();app.quit()
def show():
    menu.popup(window.pages[2].damage_plot.mapToGlobal(QPoint(100,60)))
    QTimer.singleShot(700,capture)
QTimer.singleShot(500,show)
raise SystemExit(app.exec())
