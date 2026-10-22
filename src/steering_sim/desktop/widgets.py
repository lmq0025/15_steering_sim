"""Reusable professional Qt widgets."""
from __future__ import annotations

from pathlib import Path
import math

import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal, QSortFilterProxyModel,QObject,QEvent,QPointF
from PySide6.QtGui import QColor,QWheelEvent
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableView, QVBoxLayout, QWidget, QMenu, QFileDialog,QApplication,QAbstractSpinBox,QComboBox,QScrollArea)

from .models import DataFrameModel, DataFrameProxyModel
from .localization import chinese_frame,cn

class ParameterWheelGuard(QObject):
    """Protect both focused/unfocused editors and forward to parameter scroll."""
    def __init__(self,window):
        super().__init__(window);self.window=window
        QApplication.instance().installEventFilter(self)
    def eventFilter(self,watched,event):
        if event.type()!=QEvent.Wheel or not isinstance(watched,QWidget):return False
        if not self.window.isAncestorOf(watched):return False
        editor=watched
        while editor is not None and not isinstance(editor,(QAbstractSpinBox,QComboBox)):
            editor=editor.parentWidget()
        if editor is None:return False
        if isinstance(editor,QComboBox) and editor.view().isVisible():return False
        parent=editor.parentWidget()
        while parent is not None and not isinstance(parent,QScrollArea):parent=parent.parentWidget()
        if parent is not None:
            viewport=parent.viewport();local=viewport.mapFromGlobal(event.globalPosition().toPoint())
            forwarded=QWheelEvent(QPointF(local),event.globalPosition(),event.pixelDelta(),event.angleDelta(),event.buttons(),event.modifiers(),event.phase(),event.inverted())
            QApplication.sendEvent(viewport,forwarded)
        event.accept();return True


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
        self.proxy = DataFrameProxyModel(self)
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
        self.view.horizontalHeader().setResizeContentsPrecision(100)
        layout.addWidget(self.view, 1)

    def set_frame(self, frame: pd.DataFrame) -> None:
        self.model.set_frame(frame)
        self.view.resizeColumnsToContents()

    @property
    def frame(self) -> pd.DataFrame:
        return self.model.frame

    def export(self, path: str | Path, *, raw: bool = False) -> Path:
        target = Path(path)
        frame=self.frame if raw else chinese_frame(self.frame)
        if target.suffix.lower() == ".xlsx":
            frame.to_excel(target, index=False)
        else:
            frame.to_csv(target, index=False, encoding="utf-8-sig")
        return target


class EngineeringPlot(pg.PlotWidget):
    def __init__(self, title: str = "", left_label: str = "", bottom_label: str = "",
                 parent=None) -> None:
        super().__init__(parent=parent, background="w")
        self.setTitle(cn(title), color="#17324d", size="12pt")
        self.setLabel("left", left_label)
        self.setLabel("bottom", bottom_label.replace('day','天'))
        self.showGrid(x=True, y=True, alpha=0.22)
        self.addLegend(offset=(10, 10))
        self.getPlotItem().setMenuEnabled(False)
        self.getPlotItem().vb.setMenuEnabled(False)
        self.setMouseEnabled(x=True, y=True)
        self._install_cursor()
        self._mouse_proxy = pg.SignalProxy(
            self.scene().sigMouseMoved, rateLimit=30, slot=self._mouse_moved)

    def chinese_context_menu(self):
        menu=QMenu(self)
        reset=menu.addAction('复位并显示全部数据')
        reset.triggered.connect(lambda _checked=False:self.getPlotItem().autoRange())
        grid=menu.addAction('显示／隐藏网格')
        grid.setCheckable(True);grid.setChecked(bool(self.plotItem.ctrl.xGridCheck.isChecked()))
        grid.toggled.connect(lambda checked:self.showGrid(x=checked,y=checked,alpha=.22))
        legend=menu.addAction('显示／隐藏图例')
        legend.triggered.connect(lambda _checked=False:self.plotItem.legend.setVisible(not self.plotItem.legend.isVisible()))
        menu.addSeparator()
        save=menu.addAction('保存当前图表为PNG')
        save.triggered.connect(self._save_png)
        return menu

    def contextMenuEvent(self,event):  # noqa: N802
        menu=self.chinese_context_menu()
        menu.exec(event.globalPos());event.accept()
        menu.deleteLater()

    def _save_png(self):
        path,_=QFileDialog.getSaveFileName(self,'保存当前图表','工程曲线.png','PNG图像 (*.png)')
        if path:
            import pyqtgraph.exporters
            exporter=pg.exporters.ImageExporter(self.plotItem)
            exporter.parameters()['width']=1600;exporter.export(path)

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
        formatter=getattr(self,'hover_formatter',None)
        self._cursor_label.setText(formatter(point.x(),point.y()) if formatter else f"x={point.x():.4g}\ny={point.y():.4g}")
        self._cursor_x.show()
        self._cursor_y.show()
        self._cursor_label.show()

    def replace_curves(self, curves: list[tuple[str, object, object, str]]) -> None:
        self.clear()
        self.addLegend(offset=(10, 10))
        for name, x, y, color in curves:
            import numpy as np
            self.plot(np.asarray(x), np.asarray(y), name=cn(name), pen=pg.mkPen(QColor(color), width=2))
        self._install_cursor()

    def add_time_markers(self, markers: list[tuple[str, float | None, str]]) -> None:
        for index,(label, value, color) in enumerate(markers):
            if value is None or not math.isfinite(float(value)):
                continue
            line = pg.InfiniteLine(
                pos=float(value), angle=90, movable=False,
                pen=pg.mkPen(color, width=1.5, style=Qt.DashLine),
                label=f"{label}：{float(value):.2f} s",
                labelOpts={"position": max(.2,.92-.17*index), "color": color, "fill": "#ffffffdd"})
            self.addItem(line)

    def add_prediction_band(self,x,lower,upper,color='#1976d2'):
        import numpy as np
        x,lower,upper=map(np.asarray,(x,lower,upper))
        # PlotDataItem(pen=None) can hide its internal curve entirely;
        # FillBetweenItem then receives an empty path in pyqtgraph 0.13.
        c=QColor(color);r,g,b=c.red(),c.green(),c.blue()
        low=pg.PlotCurveItem(x,lower,pen=pg.mkPen(r,g,b,70))
        high=pg.PlotCurveItem(x,upper,pen=pg.mkPen(r,g,b,70))
        self.addItem(low); self.addItem(high)
        band=pg.FillBetweenItem(low,high,brush=pg.mkBrush(r,g,b,45))
        self.addItem(band)
        return band
