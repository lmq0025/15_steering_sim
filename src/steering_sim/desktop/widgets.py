"""Reusable professional Qt widgets."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal, QSortFilterProxyModel
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableView, QVBoxLayout, QWidget)

from .models import DataFrameModel


class MetricCard(QFrame):
    def __init__(self, title: str, value: str = "—", note: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("metricCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("metricTitle")
        self.value_label = QLabel(value)
        self.value_label.setObjectName("metricValue")
        self.value_label.setWordWrap(True)
        self.note_label = QLabel(note)
        self.note_label.setObjectName("metricNote")
        self.note_label.setWordWrap(True)
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.note_label)

    def set_value(self, value: str, note: str | None = None,
                  level: str = "normal") -> None:
        self.value_label.setText(value)
        if note is not None:
            self.note_label.setText(note)
        colors = {"normal": "#17324d", "success": "#16794b",
                  "warning": "#a65f00", "danger": "#b42318"}
        self.value_label.setStyleSheet(f"color:{colors.get(level, colors['normal'])};")


class StatusBanner(QFrame):
    def __init__(self, text: str = "等待操作", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("statusBanner")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        self.label = QLabel(text)
        self.label.setWordWrap(True)
        layout.addWidget(self.label, 1)

    def set_status(self, text: str, level: str = "info") -> None:
        colors = {"info": ("#eaf2fb", "#24527a"),
                  "success": ("#e9f7ef", "#176b45"),
                  "warning": ("#fff6e5", "#925400"),
                  "error": ("#fdecec", "#a32121")}
        background, foreground = colors.get(level, colors["info"])
        self.setStyleSheet(
            f"QFrame#statusBanner{{background:{background};border:1px solid {foreground};"
            "border-radius:5px;}}")
        self.label.setStyleSheet(f"color:{foreground};")
        self.label.setText(text)


class DataTable(QWidget):
    export_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.model = DataFrameModel()
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        toolbar = QHBoxLayout()
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("筛选表格…")
        self.filter_edit.textChanged.connect(self.proxy.setFilterFixedString)
        export = QPushButton("导出表格")
        export.clicked.connect(self.export_requested)
        toolbar.addWidget(QLabel("快速筛选"))
        toolbar.addWidget(self.filter_edit, 1)
        toolbar.addWidget(export)
        layout.addLayout(toolbar)
        self.view = QTableView()
        self.view.setModel(self.proxy)
        self.view.setSortingEnabled(True)
        self.view.setAlternatingRowColors(True)
        self.view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.SingleSelection)
        self.view.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.view.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.view.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.view, 1)

    def set_frame(self, frame: pd.DataFrame) -> None:
        self.model.set_frame(frame)
        self.view.resizeColumnsToContents()

    @property
    def frame(self) -> pd.DataFrame:
        return self.model.frame

    def export(self, path: str | Path) -> Path:
        target = Path(path)
        if target.suffix.lower() == ".xlsx":
            self.frame.to_excel(target, index=False)
        else:
            self.frame.to_csv(target, index=False, encoding="utf-8-sig")
        return target


class EngineeringPlot(pg.PlotWidget):
    def __init__(self, title: str = "", left_label: str = "", bottom_label: str = "",
                 parent=None) -> None:
        super().__init__(parent=parent, background="w")
        self.setTitle(title, color="#17324d", size="12pt")
        self.setLabel("left", left_label)
        self.setLabel("bottom", bottom_label)
        self.showGrid(x=True, y=True, alpha=0.22)
        self.addLegend(offset=(10, 10))
        self.getPlotItem().setMenuEnabled(True)
        self.setMouseEnabled(x=True, y=True)
        self._install_cursor()
        self._mouse_proxy = pg.SignalProxy(
            self.scene().sigMouseMoved, rateLimit=30, slot=self._mouse_moved)

    def _install_cursor(self) -> None:
        """Install a lightweight coordinate readout without changing data."""
        self._cursor_x = pg.InfiniteLine(angle=90, movable=False,
                                         pen=pg.mkPen("#78909c", width=1))
        self._cursor_y = pg.InfiniteLine(angle=0, movable=False,
                                         pen=pg.mkPen("#78909c", width=1))
        self._cursor_label = pg.TextItem(color="#17324d", fill="#ffffffdd",
                                         anchor=(0, 1))
        for item in (self._cursor_x, self._cursor_y, self._cursor_label):
            self.addItem(item, ignoreBounds=True)
            item.hide()

    def _mouse_moved(self, event) -> None:
        position = event[0]
        if not self.sceneBoundingRect().contains(position):
            self._cursor_x.hide()
            self._cursor_y.hide()
            self._cursor_label.hide()
            return
        point = self.getPlotItem().vb.mapSceneToView(position)
        self._cursor_x.setPos(point.x())
        self._cursor_y.setPos(point.y())
        self._cursor_label.setPos(point.x(), point.y())
        self._cursor_label.setText(f"x={point.x():.4g}\ny={point.y():.4g}")
        self._cursor_x.show()
        self._cursor_y.show()
        self._cursor_label.show()

    def replace_curves(self, curves: list[tuple[str, object, object, str]]) -> None:
        self.clear()
        self.addLegend(offset=(10, 10))
        for name, x, y, color in curves:
            self.plot(x, y, name=name, pen=pg.mkPen(QColor(color), width=2))
        self._install_cursor()

    def add_time_markers(self, markers: list[tuple[str, float | None, str]]) -> None:
        for label, value, color in markers:
            if value is None:
                continue
            line = pg.InfiniteLine(
                pos=float(value), angle=90, movable=False,
                pen=pg.mkPen(color, width=1.5, style=Qt.DashLine),
                label=f"{label}：{float(value):.2f} s",
                labelOpts={"position": 0.92, "color": color, "fill": "#ffffffdd"})
            self.addItem(line)
