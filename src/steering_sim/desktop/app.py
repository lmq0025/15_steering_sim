"""D4 Qt main window and offline desktop entry point."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import logging
import os
from pathlib import Path
import sys
import time

os.environ.setdefault("MPLBACKEND", "Agg")

import pandas as pd
import pyqtgraph as pg
import pyqtgraph.exporters
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction, QCloseEvent, QFont
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QProgressBar, QPushButton, QStackedWidget,
    QStatusBar, QToolBar, QVBoxLayout, QWidget)

from . import APP_NAME, APP_VERSION
from .models import ProjectState
from .pages import (DegradationPage, QualityPage, RULPage, SimulationPage,
                    SpectrumPage, WorkPage)
from .reporting import write_report
from .services import DesktopCalculationService, EXAMPLE_SPECTRUM, OUTPUT
from .widgets import DataTable, EngineeringPlot,ParameterWheelGuard
from .localization import cn
from .worker import TaskController

LOG = logging.getLogger("steering_sim.desktop")


STYLE = """
QWidget { font-family: "Microsoft YaHei UI", "Microsoft YaHei"; font-size: 12pt; color: #263746; }
QMainWindow, QWidget#central { background: #f3f5f7; }
QFrame#panel, QGroupBox { background: white; border: 1px solid #d8e0e7; border-radius: 6px; }
QGroupBox { margin-top: 12px; padding-top: 12px; font-weight: 600; }
QLabel#pageTitle { font-size: 22pt; font-weight: 650; color: #17324d; }
QLabel#pageSubtitle { color: #5d6b78; font-size: 11pt; }
QFrame#metricCard { background: white; border: 1px solid #d8e0e7; border-radius: 7px; }
QLabel#metricTitle { color: #5d6b78; font-size: 10pt; }
QLabel#metricValue { font-size: 19pt; font-weight: 700; color: #17324d; }
QLabel#metricNote { color: #687784; font-size: 9pt; }
QLabel#warningText { color: #925400; background: #fff6e5; padding: 8px; border-radius: 4px; }
QLabel#criticalNotice { color: #8a3b00; background: #fff2dc; border: 1px solid #db8b27; padding: 9px; border-radius: 5px; font-weight: 600; }
QPushButton { background: #eef3f7; border: 1px solid #bdcad5; border-radius: 4px; padding: 7px 12px; }
QPushButton:hover { background: #e0eaf2; }
QPushButton:disabled { color: #9ca7b0; background: #edf0f2; }
QPushButton#primaryButton { background: #245f91; color: white; border: 1px solid #1d4f79; font-weight: 600; }
QPushButton#primaryButton:hover { background: #1d527f; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox { background: white; border: 1px solid #bfcbd6; border-radius: 4px; padding: 5px; min-height: 24px; }
QSpinBox, QDoubleSpinBox { padding-right: 32px; min-height: 30px; }
QSpinBox::up-button, QDoubleSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right; width: 30px; height: 19px; background: #e4eef6; border-left: 1px solid #bfcbd6; }
QSpinBox::down-button, QDoubleSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right; width: 30px; height: 19px; background: #e4eef6; border-left: 1px solid #bfcbd6; }
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover, QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover { background: #bdd6eb; }
QListWidget { background: #20384f; border: none; color: #e7eef5; padding-top: 12px; }
QListWidget::item { padding: 13px 16px; margin: 2px 7px; border-radius: 5px; }
QListWidget::item:selected { background: #2e6c9e; color: white; font-weight: 600; }
QListWidget::item:hover { background: #2a4b68; }
QTabWidget::pane { border: 1px solid #d4dde5; background: white; }
QTabBar::tab { background: #e8edf1; padding: 8px 14px; }
QTabBar::tab:selected { background: white; color: #1e5e91; font-weight: 600; }
QTableView, QTableWidget { background: white; alternate-background-color: #f6f8fa; gridline-color: #e1e7ec; }
QHeaderView::section { background: #e8eef3; color: #29445d; padding: 6px; border: 0; border-right: 1px solid #d5dde4; font-weight: 600; }
QToolBar { background: white; border-bottom: 1px solid #d2dbe3; spacing: 6px; padding: 5px; }
QStatusBar { background: #e8edf1; color: #405363; }
"""
_assets=Path(__file__).parent/'assets'
STYLE += f'''QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{image: url("{(_assets/'spin_up.svg').as_posix()}"); width: 16px; height: 12px;}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{image: url("{(_assets/'spin_down.svg').as_posix()}"); width: 16px; height: 12px;}}'''


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME}  {APP_VERSION}")
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setMinimumSize(1200, 760)
        self.resize(1560, 940)
        self.service = DesktopCalculationService()
        self.controller = TaskController(self)
        self.project = ProjectState(spectrum_path=str(EXAMPLE_SPECTRUM))
        self.results: dict[str, dict] = {}
        self.started_at = 0.0
        self._build_toolbar()
        self._build_content()
        self._build_status()
        self._connect()
        self.wheel_guard=ParameterWheelGuard(self)

    def _build_toolbar(self) -> None:
        bar = QToolBar("工程工具栏")
        bar.setMovable(False)
        self.addToolBar(bar)
        actions = (("新建工程", self.new_project), ("打开工程", self.open_project),
                   ("保存工程", self.save_project), ("另存为", self.save_project_as),
                   ("导出当前表格", self.export_current_table),
                   ("保存当前图表", self.export_current_plot),
                   ("导出中文综合报告", self.export_report),
                   ("保存验收截图", self.capture_current_page))
        for text, slot in actions:
            action = QAction(text, self)
            action.triggered.connect(slot)
            bar.addAction(action)
        raw_action=QAction('导出原始字段',self)
        raw_action.triggered.connect(lambda:self.export_current_table(raw=True))
        bar.addAction(raw_action)

    def _build_content(self) -> None:
        central = QWidget(objectName="central")
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        self.navigation = QListWidget()
        self.navigation.setFixedWidth(245)
        names = ["01  联合仿真", "02  任务载荷谱", "03  部件退化预测",
                 "04  当前质量评估", "05  剩余任务循环预测"]
        for name in names:
            self.navigation.addItem(QListWidgetItem(name))
        self.stack = QStackedWidget()
        self.pages: list[WorkPage] = [SimulationPage(), SpectrumPage(), DegradationPage(),
                                     QualityPage(), RULPage()]
        for page in self.pages:
            wrapper = QWidget()
            page_layout = QVBoxLayout(wrapper)
            page_layout.setContentsMargins(20, 16, 20, 16)
            page_layout.addWidget(page)
            self.stack.addWidget(wrapper)
        layout.addWidget(self.navigation)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self.navigation.setCurrentRow(0)
        self.navigation.currentRowChanged.connect(self.stack.setCurrentIndex)

    def _build_status(self) -> None:
        bar = QStatusBar()
        self.setStatusBar(bar)
        self.status_text = QLabel("就绪｜离线运行｜正式模型已锁定")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFixedWidth(260)
        self.cancel_button = QPushButton("取消任务")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.controller.request_cancel)
        self.elapsed = QLabel("耗时 0.0 s")
        bar.addWidget(self.status_text, 1)
        bar.addPermanentWidget(self.progress)
        bar.addPermanentWidget(self.elapsed)
        bar.addPermanentWidget(self.cancel_button)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_elapsed)

    def _connect(self) -> None:
        for page in self.pages:
            page.run_requested.connect(self.start_task)
            page.message.connect(self.show_message)
        spectrum: SpectrumPage = self.pages[1]  # type: ignore[assignment]
        spectrum.spectrum_changed.connect(self.pages[2].set_spectrum)  # type: ignore[attr-defined]
        spectrum.spectrum_changed.connect(self.pages[4].set_spectrum)  # type: ignore[attr-defined]
        self.controller.started.connect(self._task_started)
        self.controller.progress.connect(self._task_progress)
        self.controller.finished.connect(self._task_finished)
        self.controller.failed.connect(self._task_failed)
        self.controller.cancelled.connect(self._task_cancelled)
        self.controller.busy_changed.connect(self._busy_changed)

    def start_task(self, task_id: str, payload: dict) -> None:
        if self.controller.busy:
            self.show_message("已有计算正在运行，请等待或先申请取消。", "warning")
            return
        if task_id=='quality' and str(payload.get('state_source','')).startswith('checkpoint_'):
            if 'degradation' not in self.results:
                self.show_message('请先执行本工程的退化预测，再选择检查点。','warning'); return
            from steering_sim.degradation import MultiModeDegradationState
            from steering_sim.degradation.damage import ComponentDamageState
            result=self.results['degradation']; requested=float(payload['state_source'].split('_')[-1])
            curve=result['curve_frame'];available=curve.loc[curve.day>=requested-1e-12]
            if available.empty or any(key not in curve for key in result['mode_keys']):
                self.show_message('最近预测没有完整的所选检查点，请先重新运行03。','warning');return
            row=available.iloc[0]
            import math
            if any(not math.isfinite(float(row[key])) for key in result['mode_keys']):
                self.show_message('最近预测检查点存在无效状态，不能作为质量评价输入。','warning');return
            payload['multimode_state']=MultiModeDegradationState({key:ComponentDamageState(float(row[key])) for key in result['mode_keys']})
        if task_id in ('degradation','rul'):
            spectrum=self.pages[1]
            spectrum.path=str(OUTPUT/'working_task_spectrum.csv')
            payload['spectrum_path']=str(spectrum.save_working_copy())
            spectrum.spectrum_changed.emit(spectrum.path)
        methods = {"simulation": self.service.run_simulation,
                   "batch": self.service.run_batch_estimate,
                   "degradation": self.service.run_degradation,
                   "quality": self.service.run_quality,
                   "rul": self.service.run_rul,"export":self.service.export_table}
        methods['replay']=self.service.load_simulation_record
        if not self.controller.start(task_id, methods[task_id], **payload):
            self.show_message("已有计算正在运行，请等待或先申请取消。", "warning")

    def _task_started(self, task_id: str) -> None:
        if task_id!='export':
            page_id='simulation' if task_id in ('batch','replay') else task_id
            self.results.pop(page_id,None)
            page = next(page for page in self.pages if page.page_id==page_id)
            if hasattr(page, 'task_started'):
                page.task_started()
            else:
                page.invalidate_result('正在计算，尚未产生本次结果')
        self.started_at = time.perf_counter()
        self.progress.setValue(0)
        names={'simulation':'联合仿真','batch':'准稳态批量估计','degradation':'部件退化预测','quality':'当前质量评估','rul':'剩余任务循环预测','replay':'历史结果回放载入'}
        self.status_text.setText(f"正在运行：{names.get(task_id,task_id)}")
        self.timer.start(200)

    def _task_progress(self, value: int, message: str) -> None:
        self.progress.setValue(value)
        self.status_text.setText(message)

    def _task_finished(self, task_id: str, result: object) -> None:
        result = dict(result or {})
        if not result:
            self._task_cancelled(task_id, "任务在安全检查点取消")
            return
        if task_id=='export':
            self.status_text.setText(f"表格已导出：{result['path']}")
            self.progress.setValue(100);self.timer.stop();return
        page_id = "simulation" if task_id in ('batch','replay') else task_id
        page = next(item for item in self.pages if item.page_id == page_id)
        try:
            page.task_finished(result)
        except Exception as exc:
            import traceback
            self._task_failed(task_id, f"结果显示失败：{exc}", traceback.format_exc())
            return
        self.results[page_id] = result
        self.project.completed_modules[page_id] = task_id!='replay'
        task_names = {"simulation": "联合仿真", "batch": "批量估计",
                      "degradation": "退化预测", "quality": "质量评估",
                      "rul": "寿命预测"}
        task_names['replay']='历史结果载入（非本次新积分）'
        self.status_text.setText(f"{task_names.get(task_id, task_id)}完成")
        self.progress.setValue(100)
        self.timer.stop()

    def _task_failed(self, task_id: str, message: str, detail: str) -> None:
        if task_id=='export':
            self.status_text.setText(f'导出失败：{message}');self.timer.stop()
            QMessageBox.critical(self,'导出失败',str(message));return
        page_id = "simulation" if task_id in ('batch','replay') else task_id
        next(item for item in self.pages if item.page_id == page_id).task_failed(message)
        self.project.completed_modules[page_id] = False
        self.results.pop(page_id,None)
        self.status_text.setText(f"{cn(task_id)}失败：{cn(message)}")
        self.progress.setValue(0)
        self.timer.stop()
        log=OUTPUT/'logs'/f'calculation_error_{time.time_ns()}.log'
        log.parent.mkdir(parents=True,exist_ok=True)
        log.write_text(detail,encoding='utf-8')
        QMessageBox.critical(self, "计算失败", f"{cn(message)}\n\n详细技术诊断：{log}")

    def _task_cancelled(self, task_id: str, message: str) -> None:
        if task_id=='export':
            self.status_text.setText('表格导出已取消；若文件写入已开始，文件可能已完整生成。')
            self.progress.setValue(0);self.timer.stop();return
        page_id = "simulation" if task_id in ('batch','replay') else task_id
        self.results.pop(page_id, None)
        self.project.completed_modules[page_id] = False
        page=next(item for item in self.pages if item.page_id == page_id)
        if hasattr(page, 'task_cancelled'):
            page.task_cancelled(message)
        else:
            page.invalidate_result('本次任务已在安全检查点取消，未产生新结果')
        if hasattr(page,'banner'):
            page.banner.set_status('本次任务已取消；旧结果已清除，未生成新结果。','warning')
        self.status_text.setText(message)
        self.progress.setValue(0)
        self.timer.stop()

    def _busy_changed(self, busy: bool) -> None:
        self.cancel_button.setEnabled(busy)

    def _update_elapsed(self) -> None:
        self.elapsed.setText(f"耗时 {time.perf_counter() - self.started_at:.1f} s")

    def show_message(self, text: str, level: str = "info") -> None:
        self.status_text.setText(text)

    def _sync_project(self) -> None:
        spectrum: SpectrumPage = self.pages[1]  # type: ignore[assignment]
        self.project.spectrum_path = spectrum.path
        project_file = self.project.page_inputs.get("_project_file", "")
        self.project.page_inputs = {page.page_id: page.project_payload() for page in self.pages}
        if project_file:
            self.project.page_inputs["_project_file"] = project_file
        rul_inputs = self.project.page_inputs["rul"]
        self.project.initial_state = (rul_inputs.get("custom_initial_path")
                                      if rul_inputs.get("initial_state") == "custom"
                                      else rul_inputs.get("initial_state", "d1_day30"))
        self.project.maximum_cycles = int(rul_inputs.get("maximum_cycles", 240))
        self.project.monte_carlo_enabled = bool(rul_inputs.get("stochastic", True))
        self.project.monte_carlo_samples = int(rul_inputs.get("samples", 128))
        self.project.random_seed = int(rul_inputs.get("seed", 20261013))
        self.project.mode = str(rul_inputs.get("mode", "快速模式"))
        compatibility=self.project.provenance.get('compatibility_rules')
        self.project.provenance = self.service.provenance(spectrum.path)
        if compatibility: self.project.provenance['compatibility_rules']=compatibility
        self.project.result_paths = {
            key: str(value.get("output_dir", value.get("report_path", "")))
            for key, value in self.results.items()}

    def new_project(self) -> None:
        if self.controller.busy:
            self.show_message("计算运行中，不能新建工程", "warning")
            return
        self.project = ProjectState(spectrum_path=str(EXAMPLE_SPECTRUM))
        self.results.clear()
        for page in self.pages:
            if page.page_id!='spectrum': page.invalidate_result('新工程尚未执行计算')
        self.pages[1].load_example()  # type: ignore[attr-defined]
        self._apply_page_inputs({})
        self.show_message("已新建空工程；历史结果未带入")

    def _apply_page_inputs(self, inputs: dict) -> None:
        """Restore persisted inputs without treating persisted outputs as current."""
        simulation: SimulationPage = self.pages[0]  # type: ignore[assignment]
        sim = inputs.get("simulation", {})
        simulation.speed.setValue(float(sim.get("speed_kmh", 5.0)))
        index = simulation.command_type.findData(sim.get("command_type", "step"))
        simulation.command_type.setCurrentIndex(max(0, index))
        simulation.initial_angle.setValue(float(sim.get("initial_outer_angle_deg", 0.0)))
        simulation.from_straight.setChecked(bool(sim.get(
            "from_straight", float(sim.get("initial_outer_angle_deg", 0.0)) == 0.0)))
        simulation.seconds_per_degree.setValue(float(sim.get("seconds_per_degree", 6.0)))
        simulation.hold_observation.setValue(float(sim.get("hold_observation_s", 10.0)))
        simulation.angle.setValue(float(sim.get("target_outer_angle_deg", 10.0)))
        simulation.mu.setValue(float(sim.get("friction_coefficient", 0.8)))
        simulation.duration.setValue(float(sim.get("duration_s", 1.25)))
        simulation._saved_replay_time=float(sim.get('replay_time_s',0))
        simulation._record_reference=sim.get('record_reference')
        simulation.replay.speed.setCurrentIndex(max(0,simulation.replay.speed.findData(sim.get('replay_speed',1))))
        simulation.wheel_selector.setCurrentIndex(int(sim.get('wheel_index',1)))
        simulation.cylinder_selector.setCurrentIndex(int(sim.get('channel_index',0)))
        simulation.channel_overview.link.setChecked(bool(sim.get('linked_channel_axes',True)))
        simulation.detail_markers.setChecked(bool(sim.get('detail_markers',False)))
        simulation.channel_markers.setChecked(bool(sim.get('channel_markers',False)))
        simulation.tabs.setCurrentIndex(max(0,min(simulation.tabs.count()-1,int(sim.get('result_tab',0)))))
        for widget, value in zip(simulation.axles, sim.get("axle_mass_t", [11.5] * 6)):
            widget.setValue(float(value))

        degradation: DegradationPage = self.pages[2]  # type: ignore[assignment]
        degradation_data = inputs.get("degradation", {})
        index = degradation.initial.findData(degradation_data.get("initial_state", "healthy"))
        degradation.initial.setCurrentIndex(max(0, index))
        degradation.forecast_mode.setCurrentIndex(int(bool(degradation_data.get('stochastic',False))))
        degradation.sample_count.setValue(int(degradation_data.get('samples',128)))
        degradation.seed.setValue(int(degradation_data.get('random_seed',20261013)))
        index=degradation.component.findData(degradation_data.get('component','pump:front'))
        degradation.component.setCurrentIndex(max(0,index))
        degradation.view_mode.setCurrentIndex(int(degradation_data.get('view_mode',0)))
        degradation.interval.setCurrentIndex(1 if degradation_data.get('interval',90)==95 else 0)
        degradation.center.setCurrentIndex(1 if degradation_data.get('center')=='p50' else 0)
        degradation.show_band.setChecked(bool(degradation_data.get('show_band',True)))
        degradation.show_paths.setChecked(bool(degradation_data.get('show_paths',False)))
        degradation.compare.setChecked(bool(degradation_data.get('compare',False)))
        degradation.show_threshold.setChecked(bool(degradation_data.get('show_threshold',False)))
        degradation._saved_metric=degradation_data.get('metric')
        degradation.path_count.setCurrentIndex(1 if degradation_data.get('path_count')==10 else 0)

        quality: QualityPage = self.pages[3]  # type: ignore[assignment]
        quality_data = inputs.get("quality", {})
        index = quality.source.findData(quality_data.get("state_source", "healthy"))
        quality.source.setCurrentIndex(max(0, index))
        quality.severity.setValue(float(quality_data.get("severity", quality.severity.value())))
        quality._saved_case=quality_data.get('case_id')
        quality._saved_quality_wheel=quality_data.get('wheel')
        quality.quality_wheel.setCurrentIndex(max(0,quality.quality_wheel.findData(quality_data.get('wheel','axle1_right'))))
        quality.supply_rail.setCurrentIndex(max(0,quality.supply_rail.findData(quality_data.get('supply_rail','front'))))

        rul: RULPage = self.pages[4]  # type: ignore[assignment]
        rul_data = inputs.get("rul", {})
        index = rul.initial.findData(rul_data.get("initial_state", "d1_day30"))
        rul.initial.setCurrentIndex(max(0, index))
        rul.custom_initial_path = str(rul_data.get("custom_initial_path", ""))
        rul.max_cycles.setValue(int(rul_data.get("maximum_cycles", 240)))
        rul.stochastic.setChecked(bool(rul_data.get("stochastic", True)))
        rul.samples.setValue(int(rul_data.get("samples", 128)))
        rul.seed.setValue(int(rul_data.get("seed", 20261013)))
        rul.mode.setCurrentText(str(rul_data.get("mode", "快速模式")))
        rul.random_view.restore(rul_data.get('random_view',{}))
        rul.restore_quality_settings(rul_data)

    def save_project(self) -> None:
        path = self.project.page_inputs.get("_project_file", "")
        if not path:
            self.save_project_as()
            return
        self._sync_project()
        self.project.save(path)
        self.show_message(f"工程已保存：{path}", "success")

    def save_project_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "保存工程", "转向质量预测工程.d4project.json",
                                              "D4工程 (*.d4project.json *.json)")
        if not path:
            return
        self._sync_project()
        self.project.page_inputs["_project_file"] = path
        self.project.save(path)
        self.show_message(f"工程已保存：{path}", "success")

    def open_project(self) -> None:
        if self.controller.busy:
            return
        path, _ = QFileDialog.getOpenFileName(self, "打开工程", "", "D4工程 (*.json)")
        if not path:
            return
        project = ProjectState.load(path)
        project.page_inputs["_project_file"] = path
        self.project = project
        spectrum_data = project.page_inputs.get("spectrum", {})
        rows = spectrum_data.get("rows")
        spectrum_warning=''
        if rows is not None:
            self.pages[1].load_frame(pd.DataFrame(rows), spectrum_data.get("path", ""))  # type: ignore[attr-defined]
        else:
            # Older project formats store a file reference only. Never retain
            # a different project's already displayed mission in this case.
            source=Path(project.spectrum_path) if project.spectrum_path else None
            if source is not None and not source.is_absolute():source=Path(path).parent/source
            try:
                if source is None or not source.is_file():raise FileNotFoundError('工程引用的任务谱不存在')
                frame=pd.read_csv(source) if source.suffix.lower()=='.csv' else pd.read_excel(source)
                self.pages[1].load_frame(frame,str(source))
            except Exception as exc:
                self.pages[1].load_frame(pd.DataFrame(),'')
                spectrum_warning=f'任务谱未恢复，已清空原表；请重新导入。{cn(exc)}'
        self._apply_page_inputs(project.page_inputs)
        self.results.clear()
        self.project.completed_modules={}
        for page in self.pages:
            if page.page_id!='spectrum': page.invalidate_result('工程输入已恢复，历史结果不作为本次计算')
        self.show_message(spectrum_warning or "工程输入已恢复；历史结果路径保留，但不会冒充本次计算结果。", "warning" if spectrum_warning else "success")

    def _current_page(self) -> WorkPage:
        return self.pages[self.navigation.currentRow()]

    def export_current_table(self, *, raw: bool = False) -> None:
        if self._current_page().page_id=='spectrum':
            self.pages[1].export_file(raw=raw)
            return
        tables = [item for item in self._current_page().findChildren(DataTable) if item.isVisible()]
        if not tables:
            self.show_message("当前页没有可导出的结果表格", "warning")
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出当前表格", "结果.xlsx",
                                              "Excel (*.xlsx);;CSV (*.csv)")
        if path:
            self.start_task('export',{'frame':tables[0].frame,'path':path,'raw':raw})

    def export_current_plot(self) -> None:
        page=self._current_page()
        snapshot=page.snapshot_widget() if hasattr(page,'snapshot_widget') else None
        if snapshot is not None:
            path,_=QFileDialog.getSaveFileName(self,'保存当前总览','转向总览.png','PNG (*.png)')
            if path:snapshot.grab().save(path,'PNG');self.show_message(f'总览已保存：{path}','success')
            return
        plots = [item for item in self._current_page().findChildren(EngineeringPlot) if item.isVisible()]
        if not plots:
            self.show_message("当前页没有可保存的图表", "warning")
            return
        path, _ = QFileDialog.getSaveFileName(self, "保存当前图表", "工程曲线.png", "PNG (*.png)")
        if path:
            exporter = pg.exporters.ImageExporter(plots[0].plotItem)
            exporter.parameters()["width"] = 1600
            exporter.export(path)
            self.show_message(f"图表已保存：{path}", "success")

    def export_report(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "导出中文综合报告", "电液转向综合报告.md",
                                              "Markdown (*.md)")
        if not path:
            return
        self.pages[0].replay.pause()
        self._sync_project()
        figures=self.export_report_figures(Path(path))
        report = write_report(path, asdict(self.project), self.results,
                              self.project.provenance,figures=figures)
        self.show_message(f"综合报告已导出：{report}", "success")

    def export_report_figures(self,path):
        folder=path.parent/(path.stem+'_images');figures=[]
        def save(widget,title,name,plot=False):
            folder.mkdir(parents=True,exist_ok=True);target=folder/name
            if plot:
                exporter=pg.exporters.ImageExporter(widget.plotItem);exporter.parameters()['width']=1400;exporter.export(str(target))
            elif not widget.grab().save(str(target),'PNG'):raise RuntimeError('总览图导出失败')
            figures.append((title,target.relative_to(path.parent).as_posix()))
        for index,key in ((0,'simulation'),(2,'degradation'),(3,'quality'),(4,'rul')):
            page=self.pages[index]
            if key not in self.results or page.last_result is not self.results[key]:continue
            if key=='simulation' and page.last_result.get('kind')=='simulation':
                save(page.vehicle,f'车辆实际姿态，模拟时间{page.replay.current_time:.2f} s','vehicle.png')
                save(page.channel_overview.content,f'四通道实际响应，模拟时间{page.replay.current_time:.2f} s','channels.png')
            elif key=='degradation':save(page.damage_plot,page.damage_plot.plotItem.titleLabel.text,'degradation.png',True)
            elif key=='quality':
                save(page.angle_plot,page.angle_plot.plotItem.titleLabel.text,'quality_wheels.png',True)
                save(page.pressure_plot,page.pressure_plot.plotItem.titleLabel.text,'quality_pressure.png',True)
            elif key=='rul':
                if (page.last_result.get('mc_checkpoints') is not None or
                        page.last_result.get('deterministic_modes') is not None):
                    save(page.random_view.plot,page.random_view.plot.plotItem.titleLabel.text,'rul_crossings.png',True)
                save(page.quality_plot,'实际质量检查点（未在检查点之间插值）','quality_checkpoints.png',True)
        return figures

    def capture_current_page(self) -> Path:
        directory = OUTPUT / "screenshots"
        directory.mkdir(parents=True, exist_ok=True)
        page = self._current_page().page_id
        path = directory / f"D4_{self.navigation.currentRow() + 1}_{page}_{time.strftime('%Y%m%d_%H%M%S')}.png"
        screen = QApplication.primaryScreen()
        screen.grabWindow(int(self.winId())).save(str(path), "PNG")
        self.show_message(f"真实GUI窗口截图已保存：{path}", "success")
        return path

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self.controller.busy:
            answer = QMessageBox.question(
                self, "后台任务仍在运行",
                "取消请求将在下一安全检查点生效。确认关闭软件吗？")
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            self.controller.request_cancel()
            event.ignore()
            self.status_text.setText("正在等待后台任务到达安全检查点，结束后自动关闭。")
            self._close_when_idle()
            return
        self.controller.shutdown()
        event.accept()

    def _close_when_idle(self) -> None:
        if self.controller.busy:
            QTimer.singleShot(200, self._close_when_idle)
        else:
            self.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--maximized", action="store_true")
    parser.add_argument("--page", type=int, default=0)
    parser.add_argument("--startup-probe-seconds", type=float, default=0.0)
    parser.add_argument("--startup-probe-pages", action="store_true")
    parser.add_argument("--startup-probe-health", action="store_true")
    parser.add_argument("--startup-screenshot", default="")
    args, qt_args = parser.parse_known_args(argv)
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
    LOG.info("creating QApplication")
    app = QApplication([sys.argv[0], *qt_args])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setFont(QFont("Microsoft YaHei UI", 11))
    app.setStyleSheet(STYLE)
    pg.setConfigOptions(antialias=True, foreground="#30475d")
    LOG.info("creating main window")
    window = MainWindow()
    window.navigation.setCurrentRow(max(0, min(4, args.page)))
    if args.maximized:
        window.showMaximized()
    else:
        window.show()
    LOG.info("main window shown; pages=%d", window.stack.count())
    if args.startup_probe_pages:
        probe_timer = QTimer(window)
        probe_state = {"page": 0}
        def cycle_page() -> None:
            probe_state["page"] = (probe_state["page"] + 1) % window.stack.count()
            window.navigation.setCurrentRow(probe_state["page"])
            LOG.info("startup probe page=%d", probe_state["page"] + 1)
        probe_timer.timeout.connect(cycle_page)
        probe_timer.start(1200)
    if args.startup_probe_health:
        window.controller.finished.connect(
            lambda task_id, _result: LOG.info("startup probe task finished=%s", task_id))
        QTimer.singleShot(2500, window.pages[0]._run)
    if args.startup_screenshot:
        def save_probe_screenshot() -> None:
            target = Path(args.startup_screenshot).resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            saved = QApplication.primaryScreen().grabWindow(int(window.winId())).save(
                str(target), "PNG")
            LOG.info("startup screenshot saved=%s path=%s", saved, target)
        QTimer.singleShot(8000 if args.startup_probe_health else 1800,
                          save_probe_screenshot)
    if args.startup_probe_seconds > 0:
        QTimer.singleShot(int(args.startup_probe_seconds * 1000), window.close)
    exit_code = app.exec()
    LOG.info("Qt event loop exited code=%d", exit_code)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
