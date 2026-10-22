"""Five Chinese engineering work pages for PHASE D4."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame,
    QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QSpinBox, QSplitter, QTabWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget, QTextBrowser, QAbstractSpinBox, QScrollArea)

from .services import EXAMPLE_SPECTRUM, TEMPLATE_SPECTRUM
from .widgets import DataTable, EngineeringPlot, MetricCard, StatusBanner
from .localization import cn
from .replay import ReplayControl,VehicleView,ChannelOverview,display_number
from .rul_view import RULRandomView
from .rul_presentation import rul_outcome_text
from steering_sim.degradation.spectrum import normalize_columns


GRADE_CN = {"HEALTHY": "健康", "SUBHEALTHY": "亚健康",
            "DEGRADED": "退化", "DANGEROUS": "危险"}
STATUS_CN = {
    "FAILURE_REACHED": "已检测到失效阈值越限",
    "FAILURE_BRACKETED": "失效位于已验证检查区间",
    "NOT_REACHED_WITHIN_HORIZON": "预测范围内未达到失效阈值",
    "INDETERMINATE": "数值或模型能力不足，无法判断",
}


def title_block(title: str, subtitle: str) -> QWidget:
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 8)
    label = QLabel(title)
    label.setObjectName("pageTitle")
    sub = QLabel(subtitle)
    sub.setObjectName("pageSubtitle")
    sub.setWordWrap(True)
    layout.addWidget(label)
    layout.addWidget(sub)
    return box


def spin(value: float, minimum: float, maximum: float, decimals: int = 2,
         suffix: str = "") -> QDoubleSpinBox:
    item = QDoubleSpinBox()
    item.setRange(minimum, maximum)
    item.setDecimals(decimals)
    item.setValue(value)
    item.setSuffix(suffix)
    item.setKeyboardTracking(False)
    item.setButtonSymbols(QAbstractSpinBox.PlusMinus)
    return item


class WorkPage(QWidget):
    run_requested = Signal(str, dict)
    message = Signal(str, str)

    def __init__(self, page_id: str, parent=None) -> None:
        super().__init__(parent)
        self.page_id = page_id
        self.last_result: dict[str, Any] | None = None

    def task_finished(self, result: dict[str, Any]) -> None:
        self.last_result = result

    def task_failed(self, message: str) -> None:
        self.invalidate_result()
        if hasattr(self, "banner"):
            self.banner.set_status(f"计算失败：{message}。旧结果已清除。", "error")

    def invalidate_result(self, message='本工程尚未执行计算') -> None:
        self.last_result = None
        if hasattr(self,'replay'):self.replay.pause();self.replay_cursors=[]
        if hasattr(self,'random_view'):self.random_view.clear()
        for table in self.findChildren(DataTable): table.set_frame(pd.DataFrame())
        for plot in self.findChildren(EngineeringPlot): plot.replace_curves([])
        for card in self.findChildren(MetricCard): card.set_value('未计算',message)
        if hasattr(self,'replay'):
            self.replay.set_samples({});self.vehicle.set_sample({});self.channel_overview.clear()
        if hasattr(self,'banner'): self.banner.set_status(message,'info')

    def project_payload(self) -> dict[str, Any]:
        return {}


class SimulationPage(WorkPage):
    def __init__(self, parent=None) -> None:
        super().__init__("simulation", parent)
        root = QVBoxLayout(self)
        root.addWidget(title_block(
            "机械—液压—控制联合仿真",
            "正式工程机械—液压—控制模型；四组等效作动通道，单工况运行完整22状态动力学。"))
        splitter = QSplitter()
        root.addWidget(splitter, 1)
        input_panel = QFrame()
        input_panel.setObjectName("panel")
        form_layout = QVBoxLayout(input_panel)
        group = QGroupBox("工况参数")
        form = QFormLayout(group)
        self.speed = spin(5.0, 0, 80, 1, " km/h")
        self.angle = spin(10.0, -30, 30, 1, " °")
        self.mu = spin(0.8, 0.05, 1.5, 2)
        self.duration = spin(1.25, 0.2, 20, 2, " s")
        self.command_type = QComboBox()
        self.command_type.addItem("阶跃输入（兼容模式）", "step")
        self.command_type.addItem("斜坡输入", "ramp")
        self.from_straight = QCheckBox("从直行开始转向")
        self.from_straight.setChecked(True)
        self.from_straight.toggled.connect(self._sync_command_controls)
        self.initial_angle = spin(0.0, -30, 30, 1, " °")
        self.seconds_per_degree = spin(6.0, 0.1, 60, 2, " s/°")
        self.hold_observation = spin(10.0, 2.0, 60, 1, " s")
        self.command_type.currentIndexChanged.connect(self._sync_command_controls)
        form.addRow("转向指令类型", self.command_type)
        form.addRow(self.from_straight)
        form.addRow("起始转角", self.initial_angle)
        form.addRow("每度斜坡时间", self.seconds_per_degree)
        form.addRow("目标后观察时长", self.hold_observation)
        form.addRow("车速", self.speed)
        form.addRow("一桥外轮最终目标转角", self.angle)
        form.addRow("路面摩擦系数", self.mu)
        form.addRow("动态仿真时长", self.duration)
        self.duration_label=form.labelForField(self.duration)
        self.total_duration=QLabel()
        form.addRow('预计模拟总时长',self.total_duration)
        self.total_duration_label=form.labelForField(self.total_duration)
        self.axles = [spin(11.5, 1, 30, 2, " t") for _ in range(6)]
        for index, item in enumerate(self.axles, 1):
            form.addRow(f"第{index}桥轴荷", item)
        form_layout.addWidget(group)
        self.action_preview = QLabel()
        self.action_preview.setWordWrap(True)
        form_layout.addWidget(self.action_preview)
        for widget in (self.initial_angle, self.angle, self.seconds_per_degree,
                       self.hold_observation):
            widget.valueChanged.connect(self._update_action_preview)
        for widget, increment in ((self.angle, 0.5), (self.initial_angle, 0.5),
                                  (self.speed, 1.0), (self.mu, 0.05),
                                  (self.seconds_per_degree, 0.5)):
            widget.setSingleStep(increment)
        for widget in self.axles:
            widget.setSingleStep(0.5)
        self.run_button = QPushButton("运行单工况完整动态仿真")
        self.run_button.setObjectName("primaryButton")
        self.run_button.clicked.connect(self._run)
        self.batch_button = QPushButton("运行3111准稳态批量估计")
        self.batch_button.clicked.connect(self._batch)
        self.load_record_button=QPushButton('载入上次工程结果回放（历史）')
        self.load_record_button.clicked.connect(self._load_record)
        form_layout.addWidget(self.run_button)
        form_layout.addWidget(self.batch_button)
        form_layout.addWidget(self.load_record_button)
        note = QLabel("说明：3111批量功能是准稳态能力估计，不是3111次完整动态积分。")
        note.setWordWrap(True)
        note.setObjectName("warningText")
        form_layout.addWidget(note)
        form_layout.addStretch()
        input_scroll=QScrollArea(); input_scroll.setWidgetResizable(True)
        input_scroll.setWidget(input_panel)
        splitter.addWidget(input_scroll)

        result = QWidget()
        result_layout = QVBoxLayout(result)
        self.banner = StatusBanner("请输入工况并运行")
        result_layout.addWidget(self.banner)
        cards = QHBoxLayout()
        self.card_success = MetricCard("计算状态")
        self.card_tracking = MetricCard("液压跟踪")
        self.card_feasible = MetricCard("目标轨迹可行性")
        for card in (self.card_success, self.card_tracking, self.card_feasible):
            cards.addWidget(card)
        result_layout.addLayout(cards)
        self.tabs = QTabWidget()
        self.angle_plot = EngineeringPlot("一桥右轮目标/实际转角", "转角 (°)", "时间 (s)")
        self.pressure_plot = EngineeringPlot("两条供油轨压力", "压力 (MPa)", "时间 (s)")
        self.cylinder_plot = EngineeringPlot("等效作动通道目标/实际行程", "行程 (mm)", "时间 (s)")
        self.wheel_selector = QComboBox()
        self.wheel_selector.addItems([f"{axle}桥{side}轮" for axle in range(1, 7)
                                      for side in ("左", "右")])
        self.wheel_selector.setCurrentIndex(1)
        self.wheel_selector.currentIndexChanged.connect(self._refresh_response_plots)
        angle_page = QWidget(); angle_layout = QVBoxLayout(angle_page)
        angle_layout.setContentsMargins(0, 0, 0, 0)
        angle_layout.addWidget(self.wheel_selector); angle_layout.addWidget(self.angle_plot, 1)
        self.detail_markers=QCheckBox('显示到位/稳态时间标线');angle_layout.insertWidget(1,self.detail_markers)
        self.detail_markers.toggled.connect(self._refresh_response_plots)
        self.cylinder_selector = QComboBox()
        self.cylinder_selector.addItems(["一二桥等效作动通道", "四桥等效作动通道", "五桥等效作动通道", "六桥等效作动通道"])
        self.cylinder_selector.currentIndexChanged.connect(self._refresh_response_plots)
        cylinder_page = QWidget(); cylinder_layout = QVBoxLayout(cylinder_page)
        cylinder_layout.setContentsMargins(0, 0, 0, 0)
        cylinder_layout.addWidget(self.cylinder_selector); cylinder_layout.addWidget(self.cylinder_plot, 1)
        self.channel_markers=QCheckBox('显示到位/稳态时间标线');cylinder_layout.insertWidget(1,self.channel_markers)
        self.channel_markers.toggled.connect(self._refresh_response_plots)
        self.wheel_table = DataTable()
        self.wheel_response_table = DataTable()
        self.cylinder_response_table = DataTable()
        self.vehicle=VehicleView();self.vehicle.wheel_selected.connect(self._select_wheel)
        self.channel_overview=ChannelOverview()
        self.replay=ReplayControl();self.replay.time_changed.connect(self._replay_at)
        self.replay_cursors=[]
        self.wheel_time_summary=QLabel();self.wheel_time_summary.setWordWrap(True)
        self.cylinder_time_summary=QLabel();self.cylinder_time_summary.setWordWrap(True)
        self.wheel_response_table.layout().insertWidget(0,self.wheel_time_summary)
        self.cylinder_response_table.layout().insertWidget(0,self.cylinder_time_summary)
        self.tabs.addTab(self.vehicle, "十二轮转向动态")
        self.tabs.addTab(self.channel_overview, "四组等效作动通道")
        self.tabs.addTab(self.wheel_response_table, "十二轮到位/稳态时间")
        self.tabs.addTab(self.cylinder_response_table, "四通道到位/稳态时间")
        self.tabs.addTab(self.pressure_plot, "供油压力")
        self.tabs.addTab(self.wheel_table, "十二轮结果")
        self.tabs.addTab(angle_page,'轮角曲线详情')
        self.tabs.addTab(cylinder_page,'单通道曲线详情')
        self.angle_detail_page=angle_page
        result_layout.addWidget(self.replay)
        result_layout.addWidget(self.tabs, 1)
        splitter.addWidget(result)
        splitter.setSizes([330, 900])
        self._sync_command_controls()
        self._refresh_response_plots()

    def _sync_command_controls(self) -> None:
        ramp = self.command_type.currentData() == "ramp"
        for item in (self.initial_angle, self.seconds_per_degree, self.hold_observation):
            item.setEnabled(ramp)
        self.duration.setEnabled(not ramp)
        self.duration.setVisible(not ramp); self.duration_label.setVisible(not ramp)
        self.total_duration.setVisible(ramp); self.total_duration_label.setVisible(ramp)
        self.from_straight.setEnabled(ramp)
        self.initial_angle.setEnabled(ramp and not self.from_straight.isChecked())
        if self.from_straight.isChecked():
            self.initial_angle.setValue(0.0)
        if hasattr(self, "action_preview"):
            self._update_action_preview()

    def _update_action_preview(self) -> None:
        start, end = self.initial_angle.value(), self.angle.value()
        completion = abs(end - start) * self.seconds_per_degree.value()
        self.total_duration.setText(f'{completion+self.hold_observation.value():g} 秒')
        action = ("保持转向，不发生新的转向动作" if start == end
                  else f"本次动作：{start:+g}° → {end:+g}°")
        self.action_preview.setText(
            f"{action}；每度 {self.seconds_per_degree.value():g} 秒；"
            f"指令完成 {completion:g} 秒；仿真范围 "
            f"{completion + self.hold_observation.value():g} 秒。"
            if self.command_type.currentData() == "ramp" else "阶跃兼容模式，沿用原参考曲线。")

    def _scenario(self) -> dict[str, Any]:
        return {"speed_kmh": self.speed.value(),
                "from_straight": self.from_straight.isChecked(),
                "command_type": self.command_type.currentData(),
                "initial_outer_angle_deg": self.initial_angle.value(),
                "seconds_per_degree": self.seconds_per_degree.value(),
                "hold_observation_s": self.hold_observation.value(),
                "target_outer_angle_deg": self.angle.value(),
                "friction_coefficient": self.mu.value(),
                "duration_s": self.duration.value(),
                "axle_mass_t": [item.value() for item in self.axles]}

    def _run(self) -> None:
        self.banner.set_status("任务已提交，计算将在后台线程运行", "info")
        self.run_requested.emit("simulation", {"scenario": self._scenario()})

    def _batch(self) -> None:
        angles = np.linspace(-30, 30, 61)
        speeds = np.arange(0, 81, 5)
        scenarios = [{"target_outer_angle_deg": float(angle),
                      "speed_kmh": float(speed),
                      "friction_coefficient": float(mu),
                      "axle_mass_t": [item.value() for item in self.axles]}
                     for mu in (0.70, 0.75, 0.80) for speed in speeds for angle in angles]
        self.banner.set_status("准稳态作动能力估计：61档转角×17档车速(0～80 km/h)×3档附着系数(0.70/0.75/0.80)=3111组。", "info")
        self.run_requested.emit("batch", {"scenarios": scenarios})

    def task_finished(self, result: dict[str, Any]) -> None:
        super().task_finished(result)
        if result.get("kind") == "batch":
            self.replay.set_samples({});self.channel_overview.clear()
            for card in (self.card_success,self.card_tracking,self.card_feasible):card.set_value('不适用','本页显示准稳态批量估计，非单工况动态')
            self.wheel_table.set_frame(result["rows"])
            self.tabs.setCurrentWidget(self.wheel_table)
            self.banner.set_status(f"已完成 {len(result['rows'])} 个工况的准稳态能力估计。{cn(result['note'])}",
                                   "success")
            return
        samples = result["samples"]
        time = samples["time_s"]
        self._refresh_response_plots()
        self.pressure_plot.replace_curves([
            ("前供油轨", time, samples["supply_pressure_front_mpa_g"], "#1976d2"),
            ("后供油轨", time, samples["supply_pressure_rear_mpa_g"], "#d97706")])
        self.wheel_table.set_frame(result["wheel_table"])
        wheel_frame = result["wheel_response_table"].copy()
        wheel_frame["wheel"] = wheel_frame["wheel"].map({
            f"axle{a}_{s}": f"{a}桥{'左' if s == 'left' else '右'}轮"
            for a in range(1, 7) for s in ("left", "right")})
        response_status = {"SETTLED": "已满足稳定判据",
                           "NOT_SETTLED_WITHIN_HORIZON": "观察范围内未稳定",
                           "FIXED_ZERO_NO_STEERING_REQUIRED": "固定零位／无需转向到位"}
        wheel_frame["settled_status"] = wheel_frame["settled_status"].replace(response_status)
        self.wheel_response_table.set_frame(wheel_frame.rename(columns={
            "wheel": "车轮", "final_target_deg": "最终目标/°",
            "final_actual_deg": "最终实际/°", "maximum_tracking_error_deg": "最大误差/°",
            "first_arrival_s": "首次到位/s", "settled_time_s": "稳态建立/s",
            "final_speed_deg_s": "最终角速度/(°/s)", "settled_status": "状态",
            "whole_run_first_arrival_s": "全过程首次进入终值容差/s",
            "additional_convergence_s": "指令后额外收敛/s",
            "speed_at_settling_deg_s": "稳态建立时角速度/(°/s)",
        }))
        cylinder_frame = result["cylinder_response_table"].copy()
        cylinder_frame["channel"] = cylinder_frame["channel"].replace({
            "channel_front": "一二桥等效作动通道", "channel_rear_1": "四桥等效作动通道",
            "channel_rear_2": "五桥等效作动通道", "channel_rear_3": "六桥等效作动通道"})
        cylinder_frame["settled_status"] = cylinder_frame["settled_status"].replace(response_status)
        self.cylinder_response_table.set_frame(cylinder_frame.rename(columns={
            "channel": "等效作动通道", "final_target_m": "最终目标/m",
            "final_actual_m": "最终实际/m", "final_error_m": "最终偏差/m",
            "first_arrival_s": "首次到位/s", "settled_time_s": "稳态建立/s",
            "final_velocity_m_s": "最终活塞速度/(m/s)", "settled_status": "状态",
            "additional_convergence_s": "指令后额外收敛/s",
            "speed_at_settling_m_s": "稳态建立时活塞速度/(m/s)",
        }))
        self.card_success.set_value("成功" if result["calculation_success"] else "失败",
                                    f"电脑计算 {result.get('service_runtime_s',result['runtime_s']):.2f} s",
                                    "success" if result["calculation_success"] else "danger")
        self.card_tracking.set_value("达标" if result["tracking_pass"] else "需复核",
                                     "来自液压实际角与目标角", "success" if result["tracking_pass"] else "warning")
        self.card_feasible.set_value("可行" if result["trajectory_feasible"] else "超附着风险",
                                     "该判定独立于液压跟踪状态",
                                     "success" if result["trajectory_feasible"] else "warning")
        response = result["response"]
        criteria = response["criteria"]
        criteria_text = (
            f"稳态判据：轮角±{criteria.wheel_angle_tolerance_deg:g}°、"
            f"角速度≤{criteria.wheel_speed_threshold_deg_s:g}°/s；"
            f"行程±{criteria.cylinder_position_tolerance_m*1000:g} mm、"
            f"活塞速度≤{criteria.piston_speed_threshold_m_s*1000:g} mm/s；"
            f"连续观察{criteria.settled_observation_s:g} s。")
        self.wheel_response_table.setToolTip(criteria_text)
        self.cylinder_response_table.setToolTip(criteria_text)
        settled = response["system_settled_s"]
        settled_text = ("未在仿真范围内稳定" if settled is None
                        else f"整机共同稳态 {settled:.2f} s")
        time_text=f"指令完成 {response['command_completion_s']:.2f} s；{settled_text}；指令后额外收敛 {display_number(response.get('additional_convergence_s'))} s。"
        self.wheel_time_summary.setText(time_text+'\n'+criteria_text)
        self.cylinder_time_summary.setText(f"指令完成 {response['command_completion_s']:.2f} s；四通道共同稳态 {display_number(response.get('all_cylinders_settled_s'))} s。\n"+criteria_text)
        self.channel_overview.set_samples(samples)
        self.replay.set_samples(samples)
        self.banner.set_status(
            ('历史结果回放，非本次新积分。' if result.get('provenance_kind')=='HISTORICAL_REPLAY' else '')+time_text,
            "success" if settled is not None else "warning")
        if result.get('provenance_kind')=='HISTORICAL_REPLAY':self.replay.seek(getattr(self,'_saved_replay_time',self.replay.end))

    def _refresh_response_plots(self) -> None:
        self.angle_plot.setTitle(f"{self.wheel_selector.currentText()}目标/实际转角")
        self.cylinder_plot.setTitle(f"{self.cylinder_selector.currentText()}目标/实际行程")
        if not self.last_result or self.last_result.get("kind") != "simulation":
            return
        samples = self.last_result["samples"]
        response = self.last_result["response"]
        time = samples["time_s"]
        wheel_index = self.wheel_selector.currentIndex()
        axle, side_index = divmod(wheel_index, 2)
        wheel = f"axle{axle + 1}_{'left' if side_index == 0 else 'right'}"
        row = response["wheel_table"].iloc[wheel_index]
        self.angle_plot.setTitle(f"{self.wheel_selector.currentText()}目标/实际转角")
        curves=[
            ("目标", time, samples[f"wheel_{wheel}_command_deg"], "#708090"),
            ("液压实际", time, samples[f"wheel_{wheel}_actual_deg"], "#1976d2")]
        if axle==0 and 'outer_angle_reference_deg' in samples:
            curves.insert(0,('一桥外轮输入指令',time,samples['outer_angle_reference_deg'],'#d97706'))
        self.angle_plot.replace_curves(curves)
        self.angle_plot.add_time_markers([] if not self.detail_markers.isChecked() else [
            ("指令完成", response["command_completion_s"], "#5d6b78"),
            ("首次到位", row["first_arrival_s"], "#d97706"),
            ("稳态建立", row["settled_time_s"], "#2e7d32"),
            ("整车共同稳态", response["system_settled_s"], "#7b1fa2")])
        channel = ("channel_front", "channel_rear_1", "channel_rear_2",
                   "channel_rear_3")[self.cylinder_selector.currentIndex()]
        cylinder_row = response["cylinder_table"].iloc[self.cylinder_selector.currentIndex()]
        self.cylinder_plot.setTitle(f"{self.cylinder_selector.currentText()}目标/实际行程")
        self.cylinder_plot.replace_curves([
            ("目标行程", time, 1000 * samples[f"{channel}_x_ref_eff_m"], "#708090"),
            ("实际行程", time, 1000 * samples[f"{channel}_x_m"], "#1976d2")])
        self.cylinder_plot.add_time_markers([] if not self.channel_markers.isChecked() else [
            ("指令完成", response["command_completion_s"], "#5d6b78"),
            ("首次到位", cylinder_row["first_arrival_s"], "#d97706"),
            ("稳态建立", cylinder_row["settled_time_s"], "#2e7d32"),
            ("四通道共同稳态", response["all_cylinders_settled_s"], "#7b1fa2")])
        import pyqtgraph as pg
        self.replay_cursors=[]
        for plot in (self.angle_plot,self.cylinder_plot):
            cursor=pg.InfiniteLine(angle=90,pen='#d97706');plot.addItem(cursor,ignoreBounds=True);self.replay_cursors.append(cursor)
        self._replay_at(self.replay.current_time)

    def _select_wheel(self,index):
        self.wheel_selector.setCurrentIndex(index);self.tabs.setCurrentWidget(self.angle_detail_page)

    def _replay_at(self,t):
        if not hasattr(self,'replay'):return
        sample=self.replay.sample();self.vehicle.set_sample(sample);self.channel_overview.set_sample(sample)
        for cursor in self.replay_cursors:cursor.setPos(t)

    def snapshot_widget(self):
        current=self.tabs.currentWidget()
        if current is self.vehicle:return self.vehicle
        if current is self.channel_overview:return self.channel_overview.content
        return None

    def project_payload(self) -> dict[str, Any]:
        reference=getattr(self,'_record_reference',None)
        if self.last_result and self.last_result.get('kind')=='simulation' and Path(self.last_result.get('csv_path','')).is_file():
            from .services import file_hash
            r=self.last_result
            reference=dict(csv_path=r['csv_path'],csv_sha256=file_hash(Path(r['csv_path'])),
                criteria=asdict(r['response']['criteria']),command_completion_s=r['response']['command_completion_s'],
                result_metadata={k:r[k] for k in ('input_scenario','input_scenario_sha256','runtime_s','service_runtime_s',
                    'simulation_horizon_s','calculation_success','tracking_pass','trajectory_feasible','command_type',
                    'initial_outer_angle_deg','seconds_per_degree','summary') if k in r})
        return dict(self._scenario(),replay_time_s=self.replay.current_time if len(self.replay.frame) else getattr(self,'_saved_replay_time',0),
                    replay_speed=self.replay.speed.currentData(),wheel_index=self.wheel_selector.currentIndex(),
                    channel_index=self.cylinder_selector.currentIndex(),linked_channel_axes=self.channel_overview.link.isChecked(),record_reference=reference,
                    detail_markers=self.detail_markers.isChecked(),channel_markers=self.channel_markers.isChecked(),result_tab=self.tabs.currentIndex())

    def _load_record(self):
        reference=getattr(self,'_record_reference',None)
        if not reference:
            self.message.emit('请先打开含正式时序文件引用的工程；未自动读取历史示例。','warning');return
        self.run_requested.emit('replay',{'reference':reference})


SPECTRUM_COLUMNS = [
    "segment_id", "speed_kmh", "target_outer_angle_deg", "segment_duration_s",
    "friction_coefficient", *[f"axle_mass_{i}_t" for i in range(1, 7)],
    "pump_running", "repeats", "contamination_severity", "oil_temperature_c", "seconds_per_degree"]


class SpectrumPage(WorkPage):
    spectrum_changed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__("spectrum", parent)
        self.path = str(EXAMPLE_SPECTRUM)
        root = QVBoxLayout(self)
        root.addWidget(title_block("任务载荷谱",
            "每行是一个连续工况段；保持任务顺序、段间转向动作和独立持续时间语义。"))
        toolbar = QHBoxLayout()
        for text, slot in (("导入CSV/XLSX", self.import_file), ("导出任务谱", self.export_file), ("打开30天示例", self.load_example),
                           ("新建空表", self.new_table), ("下载空模板", self.copy_template),
                           ("添加", self.add_row), ("删除", self.delete_row),
                           ("复制", self.copy_row), ("上移", lambda: self.move_row(-1)),
                           ("下移", lambda: self.move_row(1))):
            button = QPushButton(text)
            button.clicked.connect(slot)
            toolbar.addWidget(button)
        toolbar.addStretch()
        root.addLayout(toolbar)
        self.banner = StatusBanner()
        root.addWidget(self.banner)
        splitter = QSplitter(Qt.Vertical)
        self.table = QTableWidget(0, len(SPECTRUM_COLUMNS))
        self.table.setHorizontalHeaderLabels([cn(key) for key in SPECTRUM_COLUMNS])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setResizeContentsPrecision(100)
        self.table.itemChanged.connect(self.refresh_summary)
        splitter.addWidget(self.table)
        charts = QWidget()
        charts_layout = QHBoxLayout(charts)
        self.speed_plot = EngineeringPlot("速度—时间", "速度 (km/h)", "任务时间 (day)")
        self.angle_plot = EngineeringPlot("目标转角—时间", "转角 (°)", "任务时间 (day)")
        charts_layout.addWidget(self.speed_plot)
        charts_layout.addWidget(self.angle_plot)
        splitter.addWidget(charts)
        splitter.setSizes([480, 280])
        root.addWidget(splitter, 1)
        self.load_example()

    def load_frame(self, frame: pd.DataFrame, path: str = "") -> None:
        frame=normalize_columns(frame)
        values=frame.reindex(columns=SPECTRUM_COLUMNS).itertuples(index=False,name=None)
        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        self.table.setRowCount(len(frame))
        for row,items in enumerate(values):
            for column, (name,value) in enumerate(zip(SPECTRUM_COLUMNS,items)):
                if name=='pump_running' and str(value).lower() in ('true','false','1','0'):
                    value='运行' if str(value).lower() in ('true','1') else '停机'
                self.table.setItem(row, column, QTableWidgetItem("" if pd.isna(value) else str(value)))
        self.table.blockSignals(False)
        self.table.resizeColumnsToContents()
        self.table.setUpdatesEnabled(True)
        self.path = path
        self.refresh_summary()
        self.spectrum_changed.emit(self.path)

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame([
            {name: (self.table.item(row, column).text()
                    if self.table.item(row, column) else "")
             for column, name in enumerate(SPECTRUM_COLUMNS)}
            for row in range(self.table.rowCount())])

    def save_working_copy(self) -> Path:
        target = Path(self.path) if self.path else Path.cwd() / "d4_task_spectrum.csv"
        if target.suffix.lower() not in (".csv", ".xlsx"):
            target = target.with_suffix(".csv")
        frame = self.frame()
        numeric = [name for name in SPECTRUM_COLUMNS if name not in ("segment_id", "pump_running")]
        for name in numeric:
            frame[name] = pd.to_numeric(frame[name], errors="coerce")
        if target.suffix.lower() == ".xlsx":
            frame.to_excel(target, index=False)
        else:
            frame.to_csv(target, index=False, encoding="utf-8-sig")
        self.path = str(target)
        return target

    def import_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "导入任务谱", self.path,
                                              "任务谱 (*.csv *.xlsx *.xls)")
        if not path:
            return
        try:
            frame = pd.read_csv(path) if Path(path).suffix.lower() == ".csv" else pd.read_excel(path)
            from steering_sim.degradation.spectrum import REQUIRED_COLUMNS
            normalized=normalize_columns(frame)
            missing=[cn(name) for name in REQUIRED_COLUMNS if name not in normalized]
            if missing:raise ValueError('缺少必需字段：'+'、'.join(missing))
            self.load_frame(normalized, path)
        except Exception as exc:
            self.banner.set_status(f'导入失败，保留原任务表：{cn(exc)}','error')
            self.message.emit(f'任务谱导入失败：{cn(exc)}','error')

    def export_file(self, *, raw: bool = False) -> None:
        path,_=QFileDialog.getSaveFileName(self,'导出当前任务谱','当前任务谱.xlsx','Excel (*.xlsx);;CSV (*.csv)')
        if not path:return
        frame=self.frame()
        try:
            for name in SPECTRUM_COLUMNS:
                if name not in ('segment_id','pump_running'):
                    frame[name]=pd.to_numeric(frame[name].replace('',np.nan),errors='raise')
        except (ValueError,TypeError) as exc:
            self.message.emit(f'存在无效数字，请先修正任务表：{exc}','warning');return
        self.run_requested.emit('export',{'frame':frame,'path':path,'raw':raw})

    def load_example(self) -> None:
        self.load_frame(pd.read_csv(EXAMPLE_SPECTRUM), str(EXAMPLE_SPECTRUM))

    def new_table(self) -> None:
        self.load_frame(pd.DataFrame(columns=SPECTRUM_COLUMNS), "")

    def copy_template(self) -> None:
        target, _ = QFileDialog.getSaveFileName(self, "保存空模板", "任务载荷谱空模板.xlsx",
                                                "Excel (*.xlsx)")
        if target:
            Path(target).write_bytes(Path(TEMPLATE_SPECTRUM).read_bytes())
            self.message.emit(f"空模板已保存：{target}", "success")

    def add_row(self) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        defaults = [f"SEG-{row + 1:03d}", "0", "0", "60", "0.8",
                    *(["11.5"] * 6), "True", "1", "1.0", "40", "6"]
        for column, value in enumerate(defaults):
            self.table.setItem(row, column, QTableWidgetItem(value))

    def delete_row(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)

    def copy_row(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        self.table.insertRow(row + 1)
        for column in range(self.table.columnCount()):
            item = self.table.item(row, column)
            self.table.setItem(row + 1, column, QTableWidgetItem(item.text() if item else ""))

    def move_row(self, offset: int) -> None:
        row = self.table.currentRow()
        target = row + offset
        if row < 0 or target < 0 or target >= self.table.rowCount():
            return
        values = [[self.table.item(r, c).text() if self.table.item(r, c) else ""
                   for c in range(self.table.columnCount())] for r in (row, target)]
        for c in range(self.table.columnCount()):
            self.table.item(row, c).setText(values[1][c])
            self.table.item(target, c).setText(values[0][c])
        self.table.selectRow(target)

    def refresh_summary(self) -> None:
        frame = self.frame()
        if frame.empty:
            self.speed_plot.replace_curves([]);self.angle_plot.replace_curves([])
            self.banner.set_status("任务谱为空，请添加或导入工况段", "warning")
            return
        durations = pd.to_numeric(frame["segment_duration_s"], errors="coerce")
        repeats = pd.to_numeric(frame["repeats"], errors="coerce").fillna(1)
        if durations.isna().any() or (durations <= 0).any():
            self.speed_plot.replace_curves([]);self.angle_plot.replace_curves([])
            self.banner.set_status("存在非数值或非正的持续时间", "error")
            return
        elapsed = (durations * repeats).cumsum() / 86400.0
        days = float(elapsed.iloc[-1])
        level = "success" if abs(days - 30) <= 1 / 86400 else "warning"
        relation = "等于30天" if level == "success" else ("不足30天" if days < 30 else "超过30天")
        legacy=('seconds_per_degree' not in frame or pd.to_numeric(frame['seconds_per_degree'],errors='coerce').isna().any())
        semantics=('含历史兼容行：12°/s、最短0.4秒；未静默改为6秒/度。' if legacy else
                   '转向动作与保持均包含在整段时间内；段长不足时严格拒绝。')
        self.banner.set_status(
            f"共 {len(frame)} 行，展开后约 {int(repeats.sum())} 段，总时长 {days:.6f} 天：{relation}。{semantics}",
            level)
        speed = pd.to_numeric(frame["speed_kmh"], errors="coerce").fillna(0)
        angle = pd.to_numeric(frame["target_outer_angle_deg"], errors="coerce").fillna(0)
        # A row holds its final command AFTER the prescribed angle ramp;
        # do not draw a fictitious slow ramp over the entire holding period.
        times=[]; angles=[]; speeds=[]; cursor=0.; previous=0.
        for i,row in frame.iterrows():
            for _ in range(max(1,int(repeats.iloc[i]))):
                duration=float(durations.iloc[i]); final=float(angle.iloc[i])
                pump=str(row['pump_running']).lower() in ('true','1','运行','开','yes')
                rate=pd.to_numeric(row.get('seconds_per_degree'),errors='coerce')
                change=abs(final-previous)
                transition=(change*float(rate) if pd.notna(rate) else min(duration,max(.4,change/12))) if change else 0.
                if pd.isna(rate) and not pump:
                    final=previous;change=0.;transition=0.
                if transition>duration+1e-9 or (change>1e-12 and not pump):
                    self.speed_plot.replace_curves([]);self.angle_plot.replace_curves([])
                    self.banner.set_status(f"{row['segment_id']}：段长不足以完成指令，或停泵时要求转向（严格校验）。",'warning')
                    return
                times.extend([cursor,cursor+transition,cursor+duration])
                angles.extend([previous,final,final]);speeds.extend([float(speed.iloc[i])]*3)
                previous=final;cursor+=duration
        self.speed_plot.replace_curves([('分段车速',np.array(times)/86400,speeds,'#1976d2')])
        self.angle_plot.replace_curves([('规定角度斜坡及保持',np.array(times)/86400,angles,'#d97706')])

    def project_payload(self) -> dict[str, Any]:
        return {"path": self.path, "rows": self.frame().to_dict("records")}


class DegradationPage(WorkPage):
    def __init__(self, parent=None) -> None:
        super().__init__("degradation", parent)
        self.spectrum_path = str(EXAMPLE_SPECTRUM)
        root = QVBoxLayout(self)
        root.addWidget(title_block("部件退化预测",
            "调用D1/D3正式模型：2台齿轮泵、4个转向阀、4组等效液压缸；每类部件两种退化模式。"))
        controls = QHBoxLayout()
        self.path_edit = QLineEdit(self.spectrum_path)
        self.path_edit.setReadOnly(True)
        self.initial = QComboBox()
        self.initial.addItem("全新健康状态", "healthy")
        self.initial.addItem("D1第30天状态", "d1_day30")
        run = QPushButton("运行30天退化预测")
        run.setObjectName("primaryButton")
        run.clicked.connect(self._run)
        controls.addWidget(QLabel("任务谱"))
        controls.addWidget(self.path_edit, 1)
        controls.addWidget(QLabel("初始状态"))
        controls.addWidget(self.initial)
        controls.addWidget(run)
        root.addLayout(controls)
        forecast_controls=QHBoxLayout()
        self.forecast_mode=QComboBox(); self.forecast_mode.addItem('确定性预测',False); self.forecast_mode.addItem('Gamma随机退化预测',True)
        self.sample_count=QSpinBox(); self.sample_count.setRange(2,10000); self.sample_count.setValue(128)
        self.seed=QSpinBox(); self.seed.setRange(0,2147483647); self.seed.setValue(20261013)
        for label,widget in [('退化预测方式',self.forecast_mode),('真实路径数（128或1000）',self.sample_count),('随机种子',self.seed)]:
            forecast_controls.addWidget(QLabel(label)); forecast_controls.addWidget(widget)
        root.addLayout(forecast_controls)
        self.banner = StatusBanner("请选择任务谱并运行预测")
        root.addWidget(self.banner)
        cards = QHBoxLayout()
        self.pump_card = MetricCard("齿轮泵", "待计算", "两台齿轮泵的第30天参考容积效率")
        self.valve_card = MetricCard("转向阀", "待计算", "四组转向阀的第30天最大响应迟滞倍率")
        self.cylinder_card = MetricCard("等效液压缸", "待计算", "四组等效缸的第30天摩擦与内泄漏")
        self.time_card = MetricCard("计算耗时")
        for card in (self.pump_card, self.valve_card, self.cylinder_card, self.time_card):
            cards.addWidget(card)
        root.addLayout(cards)
        self.card_detail_buttons = {}
        for kind, card in (("pump", self.pump_card), ("valve", self.valve_card),
                           ("cylinder", self.cylinder_card)):
            button = QPushButton("查看第30天详细参数")
            button.setEnabled(False)
            button.clicked.connect(lambda _checked=False, selected=kind: self._show_card_details(selected))
            card.layout().addWidget(button)
            self.card_detail_buttons[kind] = button
        self.component_summaries = {}
        selection=QGridLayout()
        self.component=QComboBox()
        for kind,ids in [('pump',('front','rear')),('valve',('channel_front','channel_rear_1','channel_rear_2','channel_rear_3')),('cylinder',('channel_front','channel_rear_1','channel_rear_2','channel_rear_3'))]:
            for name in ids: self.component.addItem(cn(f'{kind}:{name}:').rstrip('：'),f'{kind}:{name}')
        self.view_mode=QComboBox(); self.view_mode.addItems(['累计损伤','实际物理参数'])
        self.metric=QComboBox()
        self.center=QComboBox(); self.center.addItem('均值','mean'); self.center.addItem('中位数P50','p50')
        self.interval=QComboBox(); self.interval.addItem('中央90%逐时刻预测区间',90); self.interval.addItem('中央95%逐时刻预测区间',95)
        self.show_band=QCheckBox('显示预测区间'); self.show_band.setChecked(True)
        self.show_paths=QCheckBox('显示代表路径')
        self.path_count=QComboBox();self.path_count.addItem('5条代表路径',5);self.path_count.addItem('10条代表路径',10)
        self.compare=QCheckBox('同类部件比较')
        self.show_threshold=QCheckBox('显示部件损伤硬阈值')
        for index,widget in enumerate((self.component,self.view_mode,self.metric,self.center,self.interval,self.show_band,self.show_paths,self.path_count,self.compare,self.show_threshold)):
            selection.addWidget(widget,index//4,index%4)
        root.addLayout(selection)
        self.component.currentIndexChanged.connect(self._metrics)
        self.view_mode.currentIndexChanged.connect(self._metrics)
        for widget in (self.metric,self.center,self.interval,self.path_count): widget.currentIndexChanged.connect(self._plot)
        for widget in (self.show_band,self.show_paths,self.compare,self.show_threshold): widget.toggled.connect(self._plot)
        self.tabs = QTabWidget()
        self.damage_plot = EngineeringPlot("第0～30天损伤曲线", "累计损伤 (-)", "任务时间 (day)")
        self.component_table = DataTable()
        self.segment_table = DataTable()
        self.rainflow_table = DataTable()
        self.checkpoint_table=DataTable(); self.statistics_table=DataTable()
        self.final_parameter_table=DataTable()
        self.model_info=QTextBrowser()
        self.tabs.addTab(self.damage_plot, "退化曲线")
        self.tabs.addTab(self.component_table, "二十模式确定性参考末态")
        self.tabs.addTab(self.segment_table, "逐段损伤贡献")
        self.tabs.addTab(self.rainflow_table, "雨流与等效载荷")
        self.tabs.addTab(self.checkpoint_table,'第0、10、20、30天参数')
        self.tabs.addTab(self.statistics_table,'逐时刻预测分布')
        self.tabs.addTab(self.final_parameter_table,'第30天物理参数摘要')
        self.tabs.addTab(self.model_info,'模型与参考条件说明')
        self.path_table=DataTable();self.risk_table=DataTable()
        self.tabs.addTab(self.path_table,'代表路径数据');self.tabs.addTab(self.risk_table,'工况风险')
        root.addWidget(self.tabs, 1)
        self.center.currentIndexChanged.connect(self._update_summary_cards)

    def invalidate_result(self, message='本工程尚未执行计算') -> None:
        super().invalidate_result(message)
        self.component_summaries = {}
        self.model_info.clear()
        for card in (self.pump_card, self.valve_card, self.cylinder_card):
            card.set_value('待计算', message)
        for button in self.card_detail_buttons.values():
            button.setEnabled(False)

    def task_started(self) -> None:
        self.invalidate_result('正在预测，尚未产生本次结果')
        for card in (self.pump_card, self.valve_card, self.cylinder_card, self.time_card):
            card.set_value('正在预测', '完成后显示本次真实计算结果')

    def task_cancelled(self, message='本次任务已在安全检查点取消') -> None:
        self.invalidate_result(message)
        for card in (self.pump_card, self.valve_card, self.cylinder_card, self.time_card):
            card.set_value('已取消', '未产生本次结果')
        self.banner.set_status(message, 'warning')

    def task_failed(self, message: str) -> None:
        self.invalidate_result('计算失败，未产生本次结果')
        for card in (self.pump_card, self.valve_card, self.cylinder_card, self.time_card):
            card.set_value('计算失败', cn(message), 'danger')
        self.banner.set_status(f'计算失败：{cn(message)}。旧结果已清除。', 'error')

    def _update_summary_cards(self) -> None:
        if not self.last_result:
            return
        from .degradation_cards import final_component_summary
        summaries, frame = final_component_summary(self.last_result, self.center.currentData())
        self.component_summaries = summaries
        self.final_parameter_table.set_frame(frame)
        for kind, card in (("pump", self.pump_card), ("valve", self.valve_card),
                           ("cylinder", self.cylinder_card)):
            summary = summaries[kind]
            card.set_value(summary.value, summary.note, 'success')
            card.setToolTip('先读取各部件的确定性值或所选随机统计量，再在同类部件间比较。'
                            '两泵效率范围不是预测区间；最大倍率不是逐路径最大值的均值。'
                            '详细参数与同次第30天预测分布一致。')
            self.card_detail_buttons[kind].setEnabled(True)

    def _show_card_details(self, kind: str) -> None:
        if self.last_result:
            self.final_parameter_table.filter_edit.setText(cn(kind))
            self.tabs.setCurrentWidget(self.final_parameter_table)

    def set_spectrum(self, path: str) -> None:
        if path:
            self.spectrum_path = path
            self.path_edit.setText(path)

    def _run(self) -> None:
        self.run_requested.emit("degradation", {
            "spectrum_path": self.spectrum_path,
            "initial_state": self.initial.currentData(),
            "stochastic":self.forecast_mode.currentData(), 'samples':self.sample_count.value(),
            'random_seed':self.seed.value()})

    def task_finished(self, result: dict[str, Any]) -> None:
        super().task_finished(result)
        self._metrics()
        self._update_summary_cards()
        self.component_table.set_frame(result["component_frame"])
        self.component_table.setToolTip('此表为同次预测的确定性参考末态；随机均值、分位数和标准差见逐时刻预测分布，不强制等于确定性参考。')
        self.segment_table.set_frame(result["segment_frame"])
        self.rainflow_table.set_frame(result["rainflow_frame"])
        self.checkpoint_table.set_frame(result['checkpoint_frame'])
        self.statistics_table.set_frame(result['statistics'])
        info=['<h3>计算模型与参数来源</h3>',
              '<p>组件末态、逐段增量及导出的状态JSON属于确定性参考；随机曲线和预测分布表另给均值、分位数。两者来自同次推进，不要求总体随机均值逐点等于确定性参考。</p>',
              '<p>统一方程：dD/dE = rate × (1 + αD)，确定性采用解析推进；Gamma以当前状态下的确定性增量为条件期望，达到上限时截断。</p>',
              '<p>中央预测区间是每个时刻的分位区间，不是整条路径的覆盖保证，不是均值置信区间，也不代表已验证的月预测误差。</p>',
              '<p>载荷近似与剩余寿命共用D3初态修正任务谱；各路径共享条件载荷暴露，独立更新自己的二十状态。温度和污染为确定输入，未模拟随机环境。</p>',
              f"<p>参考压差 {result['reference_conditions']['pressure_pa']/1e6:g} MPa，油温40℃，泵额定转速，缸参考速度0.01 m/s。容积效率只扣内泄漏，机械效率单独表示轴功率损失。</p>"]
        for kind,modes in result['models'].items():
            for mode,config in modes.items():
                if mode=='leakage_wear': mapping=f"泄漏系数 = {config['maximum_internal_leakage_m3_s_per_pa']:g} × D，单位m³/(s·Pa)"
                elif mode=='mechanical_loss': mapping=f"机械效率 = max({config['minimum_mechanical_efficiency']}, 1 − {config['efficiency_loss_at_maximum_damage']}D)，有限额定轴功率约束独立作用"
                elif mode=='response_lag': mapping=f"响应时间常数 = 健康时间常数 × [1 + ({config['maximum_lag_scale']} − 1)D]"
                else: mapping=f"摩擦倍率 = 1 + ({config['maximum_friction_scale']} − 1)D，进入现有库仑和黏性摩擦方程"
                info.append(f"<h4>{cn(kind)}：{cn(mode)}</h4><p>{cn(config['mechanism'])}。速率 {config['rate']:g} / {cn(config['exposure_unit'])}；状态加速α={config['state_factor_alpha']}；硬失效损伤={config['failure_damage']}；上限={config['maximum_damage']}；Gamma尺度={config['gamma_scale_damage']}。驱动量：{', '.join(cn(d) for d in config['drivers'])}。参数映射：{mapping}。来源：工程设计假设，待甲方标定。</p>")
        self.model_info.setHtml(''.join(info))
        risks=pd.DataFrame(result['risks'])
        self.risk_table.set_frame(risks[[k for k in risks if k in ('segment_id','load_flags','target_outer_angle_deg','speed_kmh') or 'adhesion' in k]])
        self.time_card.set_value(f"{result['runtime_s']:.2f} s", "30天快速解析预测", "success")
        self.banner.set_status(
            (f"Gamma随机预测｜{result['sample_count']}条路径｜逐时刻预测区间。" if result['sample_count'] else '确定性二十状态预测完成。')+f"工况风险 {len(result['risks'])} 条，详见工况风险页。", "warning" if result['risks'] else "success")

    def project_payload(self) -> dict[str, Any]:
        return {"spectrum_path": self.spectrum_path,
                "initial_state": self.initial.currentData(), 'stochastic':self.forecast_mode.currentData(),
                'samples':self.sample_count.value(),'random_seed':self.seed.value(),
                'component':self.component.currentData(),'view_mode':self.view_mode.currentIndex(),
                'metric':self.metric.currentData() or getattr(self,'_saved_metric',None),'interval':self.interval.currentData(),
                'center':self.center.currentData(),'show_band':self.show_band.isChecked(),
                'show_paths':self.show_paths.isChecked(),'compare':self.compare.isChecked(),
                'show_threshold':self.show_threshold.isChecked(),'path_count':self.path_count.currentData(),
                'representative_ids':list(range(min(self.path_count.currentData(),self.last_result['sample_count']))) if self.last_result else []}

    def _metrics(self):
        previous=self.metric.currentData()
        self.metric.blockSignals(True); self.metric.clear()
        if self.last_result:
            prefix=self.component.currentData()+':'
            for key in self.last_result['curve_frame']:
                if key.startswith(prefix) and ((key in self.last_result['mode_keys']) == (self.view_mode.currentIndex()==0)):
                    self.metric.addItem(cn(key.split(':')[-1]),key.split(':')[-1])
        index=self.metric.findData(getattr(self,'_saved_metric',None) or previous)
        self._saved_metric=None
        if index>=0: self.metric.setCurrentIndex(index)
        self.metric.blockSignals(False); self._plot()

    def _plot(self):
        if not self.last_result or not self.metric.currentData(): return
        result=self.last_result; prefix=self.component.currentData(); metric=self.metric.currentData()
        kind=prefix.split(':')[0]
        keys=[f'{prefix}:{metric}']
        if self.compare.isChecked():
            keys=[k for k in result['curve_frame'] if k.startswith(kind+':') and k.endswith(':'+metric)]
        stats=result['statistics']; colors=['#1976d2','#d97706','#2e7d32','#7b1fa2']
        components=[self.component.itemData(i) for i in range(self.component.count()) if self.component.itemData(i).startswith(kind+':')]
        def color(key):return colors[components.index(':'.join(key.split(':')[:2]))%len(colors)]
        frames=[stats.loc[stats.metric==key] for key in keys]
        threshold=None
        title=cn(keys[0])+('（同类对比）' if self.compare.isChecked() else '')
        title+=(f"｜{self.center.currentText()}，{result['sample_count']}条路径" if result['sample_count'] else '｜确定性预测')
        if result['sample_count'] and self.show_band.isChecked():
            title+=f"，中央{self.interval.currentData()}%逐时刻预测区间"
        self.damage_plot.setTitle(title)
        self.damage_plot.setLabel('left',result['units'][keys[0]])
        self.damage_plot.replace_curves([(cn(key),f.day,f[self.center.currentData()],color(key)) for key,f in zip(keys,frames)])
        if self.show_threshold.isChecked() and metric in result['models'][kind]:
            import pyqtgraph as pg
            threshold=result['models'][kind][metric]['failure_damage']
            self.damage_plot.addItem(pg.InfiniteLine(pos=threshold,angle=0,
                pen=pg.mkPen('#b42318',style=Qt.DashLine),label=f'工程假设硬阈值：{threshold:g}'))
        path_rows=[]
        for key,frame in zip(keys,frames):
            if result['sample_count'] and self.show_band.isChecked():
                lo,hi=('p05','p95') if self.interval.currentData()==90 else ('p025','p975')
                self.damage_plot.add_prediction_band(frame.day,frame[lo],frame[hi],color(key))
            if result['sample_count'] and self.show_paths.isChecked():
                count=min(self.path_count.currentData(),result['representatives'][key].shape[1])
                for j in range(count):
                    self.damage_plot.plot(frame.day.to_numpy(),result['representatives'][key][:,j],pen='#9aadb9')
                    path_rows.extend(dict(day=d,sample_id=j,metric=key,value=v,unit=result['units'][key]) for d,v in zip(frame.day,result['representatives'][key][:,j]))
        self.path_table.set_frame(pd.DataFrame(path_rows))
        self.damage_plot.setToolTip(f"统计使用全部{result['sample_count']}条路径；代表路径为固定样本ID 0～{min(self.path_count.currentData(),result['sample_count'])-1}，不重新抽样。参考条件见模型说明。")
        lower=min(float(f.p025.min()) for f in frames)
        upper=max(float(f.p975.max()) for f in frames)
        # A real representative path can lie outside the pointwise band. Keep
        # that path visible instead of cropping it at the quantile bounds.
        if path_rows:
            lower=min(lower,min(float(row['value']) for row in path_rows))
            upper=max(upper,max(float(row['value']) for row in path_rows))
        if threshold is not None: upper=max(upper,float(threshold))
        if upper<=lower:
            padding=max(abs(lower)*1e-4,1e-12);lower-=padding;upper+=padding
        self.damage_plot.setYRange(lower,upper,padding=.08)
        self.damage_plot.setXRange(0,float(frames[0].day.max()),padding=.01)


class QualityPage(WorkPage):
    def __init__(self, parent=None) -> None:
        super().__init__("quality", parent)
        root = QVBoxLayout(self)
        root.addWidget(title_block("当前质量性能评估",
            "使用正式质量评估服务执行真实22状态标准转向测试；机构几何固有偏差与液压跟踪误差分别报告。"))
        controls = QHBoxLayout()
        self.source = QComboBox()
        self.source.addItem("全新健康状态", "healthy")
        self.source.addItem("轻度指定退化（敏感性）", "specified_light")
        self.source.addItem("中度指定退化（敏感性）", "specified_medium")
        self.source.addItem("重度指定退化（敏感性）", "specified_heavy")
        for day in (0,10,20,30): self.source.addItem(f'最近退化预测第{day}天检查点',f'checkpoint_{day}')
        self.source.currentIndexChanged.connect(self._sync_severity)
        self.severity = spin(0.0, 0, 0.95, 2)
        run = QPushButton("运行标准转向测试")
        run.setObjectName("primaryButton")
        run.clicked.connect(self._run)
        controls.addWidget(QLabel("评估状态"))
        controls.addWidget(self.source)
        controls.addWidget(QLabel("模式损伤"))
        controls.addWidget(self.severity)
        controls.addStretch()
        controls.addWidget(run)
        root.addLayout(controls)
        self.source_description=QLabel();root.addWidget(self.source_description)
        self.banner = StatusBanner("请选择自然状态或明确标记的指定退化敏感性情景")
        root.addWidget(self.banner)
        cards = QHBoxLayout()
        self.grade_card = MetricCard("整车质量等级")
        self.error_card = MetricCard("最大轮角跟踪误差")
        self.margin_card = MetricCard("最小泵流量余量")
        self.source_card = MetricCard("场景性质")
        for card in (self.grade_card, self.error_card, self.margin_card, self.source_card):
            cards.addWidget(card)
        root.addLayout(cards)
        choices=QHBoxLayout()
        self.test_case=QComboBox();self.quality_wheel=QComboBox();self.supply_rail=QComboBox()
        for a in range(1,7):
            for side,label in [('left','左'),('right','右')]:self.quality_wheel.addItem(f'{a}桥{label}轮',f'axle{a}_{side}')
        self.quality_wheel.setCurrentIndex(1)
        self.supply_rail.addItem('前供油轨','front');self.supply_rail.addItem('后供油轨','rear')
        for label,widget in [('同一测试工况',self.test_case),('车轮',self.quality_wheel),('供油轨',self.supply_rail)]:choices.addWidget(QLabel(label));choices.addWidget(widget)
        root.addLayout(choices)
        self.test_case.currentIndexChanged.connect(self._case_changed)
        self.quality_wheel.currentIndexChanged.connect(self._paired_plots)
        self.supply_rail.currentIndexChanged.connect(self._paired_plots)
        self.tabs = QTabWidget()
        self.result_table = DataTable()
        self.angle_plot = EngineeringPlot("健康/退化动态响应", "一桥右轮转角 (°)", "时间 (s)")
        self.pressure_plot = EngineeringPlot("供油压力动态", "压力 (MPa)", "时间 (s)")
        self.tabs.addTab(self.result_table, "质量指标与下降原因")
        self.tabs.addTab(self.angle_plot, "轮角对比")
        self.tabs.addTab(self.pressure_plot, "供压对比")
        self.comparison_table=DataTable();self.tabs.addTab(self.comparison_table,'健康/当前同工况指标')
        root.addWidget(self.tabs, 1)
        self._sync_severity()

    def _sync_severity(self) -> None:
        values = [0.0, 0.25, 0.55, 0.85]
        index=self.source.currentIndex()
        self.severity.setValue(values[index] if index<len(values) else 0.0)
        self.severity.setEnabled(0<index<4)
        if hasattr(self,'source_description'):
            self.source_description.setText('使用健康参数作为性能基准。' if index==0 else '人为设置损伤程度，测试性能敏感性。' if index<4 else '使用最近一次预测的确定性参考检查点，不是随机均值或实测状态。')

    def _run(self) -> None:
        self.run_requested.emit("quality", {
            "state_source": self.source.currentData(),
            "severity": self.severity.value()})

    def task_finished(self, result: dict[str, Any]) -> None:
        super().task_finished(result)
        rows = result["rows"]
        self.result_table.set_frame(rows)
        grade = result["grade"]
        level = {"HEALTHY": "success", "SUBHEALTHY": "warning",
                 "DEGRADED": "warning", "DANGEROUS": "danger"}[grade]
        self.grade_card.set_value(GRADE_CN[grade], '真实额定工况评价', level)
        self.error_card.set_value(f"{rows['max_tracking_error_deg'].max():.4f} °",
                                  "液压实际轮角相对命令")
        self.margin_card.set_value(f"{rows['minimum_pump_flow_margin_lpm'].min():.3f} L/min",
                                   "负值表示瞬态需求超过泵能力",
                                   "warning" if rows['minimum_pump_flow_margin_lpm'].min() < 0 else "success")
        self.source_card.set_value(result["natural_or_sensitivity"],
                                   "不会与自然30天退化混淆")
        self.comparison_table.set_frame(result.get('comparison_frame',pd.DataFrame()))
        previous=self.test_case.currentData() or getattr(self,'_saved_case',None)
        preferred_wheel=getattr(self,'_saved_quality_wheel',None) or (self.quality_wheel.currentData() if self.test_case.currentData() else None)
        self.test_case.blockSignals(True);self.test_case.clear()
        for pair in result.get('comparison_dynamics',[]):self.test_case.addItem(cn(pair['case_id']),pair['case_id'])
        index=self.test_case.findData(previous);self.test_case.setCurrentIndex(max(0,index));self.test_case.blockSignals(False)
        self._case_changed()
        if preferred_wheel:self.quality_wheel.setCurrentIndex(max(0,self.quality_wheel.findData(preferred_wheel)))
        self._saved_case=None;self._saved_quality_wheel=None
        import re
        causes=list(dict.fromkeys(cn(part) for value in rows['grade_causes'] if pd.notna(value)
            for part in str(value).split('|') if part.strip()))
        causes=sorted(causes,key=lambda text:0 if '危险' in text else 1 if '退化' in text else 2)[:3]
        causes=[re.sub(r'-?\d+\.\d{5,}',lambda m:f'{float(m[0]):.3f}',v) for v in causes]
        self.banner.set_status(f"评估完成：{GRADE_CN[grade]}。"+('主要原因：'+'；'.join(causes) if causes else '未触发降级阈值。'),level)

    def _case_changed(self):
        if self.last_result:
            pair=next((p for p in self.last_result.get('comparison_dynamics',[]) if p['case_id']==self.test_case.currentData()),None)
            if pair:
                self.quality_wheel.setCurrentIndex(0 if pair['case_config']['target_outer_angle_deg']<0 else 1)
        self._paired_plots()

    def _paired_plots(self):
        if not self.last_result:return
        pair=next((p for p in self.last_result.get('comparison_dynamics',[]) if p['case_id']==self.test_case.currentData()),None)
        if pair is None:
            self.angle_plot.replace_curves([]);self.pressure_plot.replace_curves([]);return
        a,b=pair['healthy'].samples,pair['current'].samples;wheel=self.quality_wheel.currentData();rail=self.supply_rail.currentData()
        self.angle_plot.setTitle(f'{self.test_case.currentText()}：{self.quality_wheel.currentText()}健康/当前对照')
        self.angle_plot.setLabel('left','转角 (°)')
        self.angle_plot.replace_curves([('目标',a['time_s'],a[f'wheel_{wheel}_command_deg'],'#78909c'),('健康实际',a['time_s'],a[f'wheel_{wheel}_actual_deg'],'#1976d2'),('当前实际',b['time_s'],b[f'wheel_{wheel}_actual_deg'],'#d97706')])
        self.pressure_plot.setTitle(f'{self.test_case.currentText()}：{self.supply_rail.currentText()}健康/当前对照')
        self.pressure_plot.replace_curves([('健康供压',a['time_s'],a[f'supply_pressure_{rail}_mpa_g'],'#1976d2'),('当前供压',b['time_s'],b[f'supply_pressure_{rail}_mpa_g'],'#d97706')])

    def project_payload(self) -> dict[str, Any]:
        return {"state_source": self.source.currentData(),
                "severity": self.severity.value(),'case_id':self.test_case.currentData() or getattr(self,'_saved_case',None),
                'wheel':self.quality_wheel.currentData(),'supply_rail':self.supply_rail.currentData()}


class RULPage(WorkPage):
    def __init__(self, parent=None) -> None:
        super().__init__("rul", parent)
        self.spectrum_path = str(EXAMPLE_SPECTRUM)
        self.custom_initial_path = ""
        root = QVBoxLayout(self)
        root.addWidget(title_block("剩余任务循环预测",
            "重复30天任务谱，逐段继承六模式状态；关键检查点使用D2真实22状态质量评价。"))
        controls = QGridLayout()
        self.path_edit = QLineEdit(self.spectrum_path)
        self.path_edit.setReadOnly(True)
        self.initial = QComboBox()
        self.initial.addItem("D1第30天状态", "d1_day30")
        self.initial.addItem("全新健康状态", "healthy")
        self.initial.addItem("自定义JSON…", "custom")
        self.max_cycles = QSpinBox(); self.max_cycles.setRange(1, 2000); self.max_cycles.setValue(240)
        self.stochastic = QCheckBox("启用Gamma随机分析"); self.stochastic.setChecked(True)
        self.samples = QSpinBox(); self.samples.setRange(1, 4096); self.samples.setValue(128)
        self.seed = QSpinBox(); self.seed.setRange(0, 2147483647); self.seed.setValue(20261013)
        self.mode = QComboBox(); self.mode.addItems(["快速模式", "详细模式"])
        self.mode.setToolTip('选择每个检查点的标准工况组：快速模式沿用2个工况，详细模式增加中速工况。检查点数量另行设置。')
        self.quality_density=QComboBox()
        self.quality_density.addItem('快速：5个检查点',5)
        self.quality_density.addItem('较详细：10个检查点',10)
        self.quality_density.addItem('自定义检查点',None)
        self.quality_checkpoints=QSpinBox();self.quality_checkpoints.setRange(2,100);self.quality_checkpoints.setValue(5)
        self.quality_checkpoints.setEnabled(False)
        self.quality_density.currentIndexChanged.connect(self._checkpoint_density_changed)
        self.run_button = QPushButton("开始剩余寿命预测")
        self.run_button.setObjectName("primaryButton")
        self.run_button.clicked.connect(self._run)
        controls.addWidget(QLabel("30天任务谱"), 0, 0); controls.addWidget(self.path_edit, 0, 1, 1, 3)
        controls.addWidget(QLabel("当前初始状态"), 1, 0); controls.addWidget(self.initial, 1, 1)
        controls.addWidget(QLabel("最大任务循环"), 1, 2); controls.addWidget(self.max_cycles, 1, 3)
        controls.addWidget(self.stochastic, 2, 0); controls.addWidget(QLabel("样本数"), 2, 1)
        controls.addWidget(self.samples, 2, 2); controls.addWidget(QLabel("随机种子"), 2, 3)
        controls.addWidget(self.seed, 2, 4); controls.addWidget(self.mode, 1, 4)
        controls.addWidget(self.run_button, 0, 4)
        controls.addWidget(QLabel('真实动态质量检查'),3,0)
        controls.addWidget(self.quality_density,3,1)
        controls.addWidget(self.quality_checkpoints,3,2)
        controls.addWidget(QLabel('增加检查点将增加正式动态计算耗时'),3,3,1,2)
        root.addLayout(controls)
        self.banner = StatusBanner("请选择任务谱及预测范围")
        root.addWidget(self.banner)
        cards = QHBoxLayout()
        self.cycles_card = MetricCard("剩余完整30天任务")
        self.failure_card = MetricCard("首次越限")
        self.limiter_card = MetricCard("首先受限部件/模式")
        self.quantile_card = MetricCard("随机寿命 P05 / P50 / P95")
        for card in (self.cycles_card, self.failure_card, self.limiter_card, self.quantile_card):
            cards.addWidget(card)
        root.addLayout(cards)
        self.tabs = QTabWidget()
        self.damage_plot = EngineeringPlot("部件退化随任务循环变化", "最大模式损伤 (-)", "30天任务循环")
        self.quality_plot = EngineeringPlot("系统质量抽样检查点（22状态动态评估）", "质量等级", "30天任务循环")
        self.quality_scope=QLabel('尚未执行动态质量检查');self.quality_scope.setWordWrap(True)
        quality_area=QWidget();quality_layout=QVBoxLayout(quality_area)
        quality_layout.addWidget(self.quality_scope)
        quality_details=QTabWidget();self.quality_table=DataTable()
        quality_details.addTab(self.quality_plot,'离散质量检查点');quality_details.addTab(self.quality_table,'指标、原因与对应退化状态')
        quality_layout.addWidget(quality_details,1)
        self.distribution_plot = EngineeringPlot("随机寿命分布", "累计概率", "首次失效任务循环")
        self.mode_table = DataTable()
        self.random_view=RULRandomView()
        self.tabs.addTab(self.random_view,'限制部件退化与首次越限')
        self.tabs.addTab(self.damage_plot, "辅助分析：最大模式损伤")
        self.tabs.addTab(quality_area, "系统质量抽样检查点")
        self.tabs.addTab(self.distribution_plot, "随机寿命")
        self.tabs.addTab(self.mode_table, "临界部件参数")
        root.addWidget(self.tabs, 1)

    def invalidate_result(self,message='本工程尚未执行计算') -> None:
        super().invalidate_result(message)
        self.quality_scope.setText(message+'；尚无本次动态质量检查结果。')
        self.quality_plot.hover_formatter=None

    def set_spectrum(self, path: str) -> None:
        if path:
            self.spectrum_path = path
            self.path_edit.setText(path)

    def _checkpoint_density_changed(self):
        value=self.quality_density.currentData()
        self.quality_checkpoints.setEnabled(value is None)
        if value is not None:self.quality_checkpoints.setValue(value)

    def restore_quality_settings(self,raw):
        count=int(raw.get('quality_checkpoints',5))
        index=self.quality_density.findData(raw.get('quality_density',count if count in (5,10) else None))
        self.quality_density.setCurrentIndex(max(0,index));self.quality_checkpoints.setValue(count)
        self.tabs.setCurrentIndex(int(raw.get('result_tab',0)))

    def _run(self) -> None:
        initial = self.initial.currentData()
        if initial == "custom":
            if not self.custom_initial_path or not Path(self.custom_initial_path).exists():
                path, _ = QFileDialog.getOpenFileName(self, "选择自定义退化状态", "", "JSON (*.json)")
                if not path:
                    return
                self.custom_initial_path = path
            initial = self.custom_initial_path
        self.run_requested.emit("rul", {
            "spectrum_path": self.spectrum_path, "initial_state": initial,
            "maximum_cycles": self.max_cycles.value(), "samples": self.samples.value(),
            "random_seed": self.seed.value(), "stochastic": self.stochastic.isChecked(),
            "detailed": self.mode.currentText() == "详细模式",
            "quality_checkpoints":self.quality_checkpoints.value()})

    def task_finished(self, result: dict[str, Any]) -> None:
        super().task_finished(result)
        self.random_view.set_result(result)
        for plot in (self.damage_plot,self.quality_plot,self.distribution_plot):
            plot.replace_curves([])
        self.distribution_plot.setTitle('随机寿命分布（已越限样本）')
        summary = result["summary"]
        status = summary["prediction_status"]
        outcome = rul_outcome_text(summary)
        level = outcome["level"]
        self.cycles_card.set_value(outcome["complete_value"], outcome["complete_note"], level)
        self.failure_card.set_value(outcome["failure_value"], outcome["failure_note"], level)
        factors = summary.get("limiting_factors") or []
        reasons = summary.get("failure_reasons") or []
        factor_names = {
            "pump:rail_front": "前供油轨齿轮泵", "pump:rail_rear": "后供油轨齿轮泵",
            "valve:channel_front": "前通道转向阀", "valve:channel_rear_1": "后通道1转向阀",
            "valve:channel_rear_2": "后通道2转向阀", "valve:channel_rear_3": "后通道3转向阀",
            "cylinder:channel_front": "前通道等效液压缸",
            "cylinder:channel_rear_1": "后通道1等效液压缸",
            "cylinder:channel_rear_2": "后通道2等效液压缸",
            "cylinder:channel_rear_3": "后通道3等效液压缸",
        }
        factor_names={key:cn(key) for key in factor_names}
        mode_names = {"response_lag": "响应迟滞", "internal_leakage": "内泄漏",
                      "mechanical_loss": "机械损失", "friction": "摩擦增大"}
        display_factors = [cn(item) for item in factors]
        display_reasons = []
        for reason in reasons:
            translated = str(reason)
            for key, value in factor_names.items():
                translated = translated.replace(key, value)
            for key, value in mode_names.items():
                translated = translated.replace(key, value)
            translated = translated.replace(" damage ", "：损伤 ")
            translated = translated.replace("hard limit", "硬限值")
            translated = translated.replace(">=", "≥")
            display_reasons.append(cn(translated))
        self.limiter_card.set_value(" / ".join(display_factors) or "—",
                                    "；".join(display_reasons), level)
        metrics = result["mc_summary"]
        quantiles = {row["metric"]: row["value"] for _, row in metrics.iterrows()
                     if row["metric"] in {"p05", "p50", "p95"} and pd.notna(row['value'])}
        from .replay import display_number
        quantile_text=' / '.join(display_number(quantiles.get(key)) for key in ('p05','p50','p95'))
        self.quantile_card.set_value(
            quantile_text,
            "随机路径寿命分位区间，不是均值置信区间")
        censor_rows=metrics.loc[metrics['metric']=='right_censored_count','value']
        censored=int(float(censor_rows.iloc[0])) if len(censor_rows) and pd.notna(censor_rows.iloc[0]) else 0
        if censored:
            self.quantile_card.set_value(
                quantile_text,
                f'仅已越限样本的条件分位；另有{censored}条右删失，整体上尾尚未确定')
        history = result["history"]
        damage_columns = [column for column in history if column not in
                          {"mission_cycle", "mission_days_elapsed", "cycle_completed"}
                          and not column.startswith("increment_")]
        if damage_columns:
            maximum = history[damage_columns].apply(pd.to_numeric, errors="coerce").max(axis=1)
            self.damage_plot.setTitle('确定性最大模式损伤（辅助视图）')
            self.damage_plot.replace_curves([("确定性最大模式损伤", history["mission_cycle"], maximum, "#1976d2")])
        quality = result["quality"]
        self.quality_table.set_frame(quality)
        self.quality_scope.setText('没有完成可用的22状态质量检查；不能补造质量等级。')
        if not quality.empty:
            grade = quality["rated_quality_grade"].map(
                {"HEALTHY": 0, "SUBHEALTHY": 1, "DEGRADED": 2, "DANGEROUS": 3})
            self.quality_plot.replace_curves([])
            self.quality_plot.plot(quality['mission_cycle'].to_numpy(),grade.to_numpy(),pen=None,symbol='o',symbolBrush='#d97706',name='实际22状态质量检查点')
            self.quality_plot.getAxis('left').setTicks([[(0,'健康'),(1,'亚健康'),(2,'退化'),(3,'危险')]])
            self.quality_plot.setLabel('left','质量等级');self.quality_plot.setYRange(-.25,3.25,padding=0)
            cycles=[int(value) for value in quality.mission_cycle]
            last_cycle=int(result['history'].mission_cycle.max()) if len(result['history']) else max(cycles)
            gaps=[];previous=-1
            for value in cycles+[last_cycle+1]:
                if value-previous>1:gaps.append(str(previous+1) if value-previous==2 else f'{previous+1}～{value-1}')
                previous=value
            case_count=int(summary.get('executed_quality_case_count',quality.get('case_count',pd.Series(dtype=int)).sum()))
            self.quality_scope.setText(
                f'已执行{len(cycles)}个检查点、{case_count}次标准工况动态评估；循环位置：'+ '、'.join(map(str,cycles))+'。\n'
                '未做动态质量检查的循环：'+('、'.join(gaps) if gaps else '无')+'。仅显示实际检查等级；中间质量未验证。\n'
                '部件硬阈值与系统质量终止分别判断；部件越限时系统可仍为退化等级。系统首次性能越限只支持已检安全点与越限点之间的区间。')
            def quality_hover(x,y):
                row=quality.iloc[int(np.argmin(np.abs(quality.mission_cycle.to_numpy()-x)))]
                cause=cn(str(row.get('grade_causes',''))) if pd.notna(row.get('grade_causes','')) else '无降级项'
                state=row.get('maximum_mode_damage')
                return (f'第{int(row.mission_cycle)}次30天任务：{GRADE_CN.get(row.rated_quality_grade,cn(row.rated_quality_grade))}\n'
                        '实际执行的标准工况22状态质量评估\n'+
                        (f'对应20模式最大损伤：{float(state):.6g}\n' if state is not None and pd.notna(state) else '')+
                        '主要指标：'+(cause[:240] or '无降级项'))
            self.quality_plot.hover_formatter=quality_hover
        samples = pd.to_numeric(result["mc_samples"].get("failure_cycle"), errors="coerce").dropna().sort_values()
        if len(samples):
            probability = np.arange(1, len(samples) + 1) / len(samples)
            self.distribution_plot.replace_curves([("经验累计分布", samples, probability, "#7b1fa2")])
        else:
            self.distribution_plot.setTitle('本次未获得已越限随机样本；不绘制旧结果')
        self.mode_table.set_frame(result["modes"])
        self.banner.set_status(outcome["explanation"], outcome["banner_level"])

    def project_payload(self) -> dict[str, Any]:
        return {"spectrum_path": self.spectrum_path,
                "initial_state": self.initial.currentData(),
                "custom_initial_path": self.custom_initial_path,
                "maximum_cycles": self.max_cycles.value(),
                "stochastic": self.stochastic.isChecked(),
                "samples": self.samples.value(), "seed": self.seed.value(),
                "mode": self.mode.currentText(),'random_view':self.random_view.payload(),
                'quality_density':self.quality_density.currentData(),'quality_checkpoints':self.quality_checkpoints.value(),
                'result_tab':self.tabs.currentIndex()}
