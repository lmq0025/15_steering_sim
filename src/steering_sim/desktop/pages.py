"""Five Chinese engineering work pages for PHASE D4."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame,
    QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QSpinBox, QSplitter, QTabWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget)

from .services import EXAMPLE_SPECTRUM, TEMPLATE_SPECTRUM
from .widgets import DataTable, EngineeringPlot, MetricCard, StatusBanner


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
        if hasattr(self, "banner"):
            self.banner.set_status(f"计算失败：{message}。旧结果已标记为非当前结果。", "error")
        self.last_result = None

    def project_payload(self) -> dict[str, Any]:
        return {}


class SimulationPage(WorkPage):
    def __init__(self, parent=None) -> None:
        super().__init__("simulation", parent)
        root = QVBoxLayout(self)
        root.addWidget(title_block(
            "机械—液压—控制联合仿真",
            "正式模型：ENGINEERING_STEERING_MODEL + ENGINEERING_HYDRAULIC_V1；单工况运行完整22状态动力学。"))
        splitter = QSplitter()
        root.addWidget(splitter, 1)
        input_panel = QFrame()
        input_panel.setObjectName("panel")
        form_layout = QVBoxLayout(input_panel)
        group = QGroupBox("工况参数")
        form = QFormLayout(group)
        self.speed = spin(5.0, 0, 80, 1, " km/h")
        self.angle = spin(10.0, -35, 35, 1, " °")
        self.mu = spin(0.8, 0.05, 1.5, 2)
        self.duration = spin(1.25, 0.2, 20, 2, " s")
        self.command_type = QComboBox()
        self.command_type.addItem("阶跃输入（兼容模式）", "step")
        self.command_type.addItem("斜坡输入", "ramp")
        self.initial_angle = spin(0.0, -30, 30, 1, " °")
        self.seconds_per_degree = spin(6.0, 0.1, 60, 2, " s/°")
        self.hold_observation = spin(10.0, 2.0, 60, 1, " s")
        self.command_type.currentIndexChanged.connect(self._sync_command_controls)
        form.addRow("转向指令类型", self.command_type)
        form.addRow("初始目标转角", self.initial_angle)
        form.addRow("每度斜坡时间", self.seconds_per_degree)
        form.addRow("目标后观察时长", self.hold_observation)
        form.addRow("车速", self.speed)
        form.addRow("一桥外轮目标转角", self.angle)
        form.addRow("路面摩擦系数", self.mu)
        form.addRow("动态仿真时长", self.duration)
        self.axles = [spin(11.5, 1, 30, 2, " t") for _ in range(6)]
        for index, item in enumerate(self.axles, 1):
            form.addRow(f"第{index}桥轴荷", item)
        form_layout.addWidget(group)
        self.run_button = QPushButton("运行单工况完整动态仿真")
        self.run_button.setObjectName("primaryButton")
        self.run_button.clicked.connect(self._run)
        self.batch_button = QPushButton("运行3111准稳态批量估计")
        self.batch_button.clicked.connect(self._batch)
        form_layout.addWidget(self.run_button)
        form_layout.addWidget(self.batch_button)
        note = QLabel("说明：3111批量功能是准稳态能力估计，不是3111次完整动态积分。")
        note.setWordWrap(True)
        note.setObjectName("warningText")
        form_layout.addWidget(note)
        form_layout.addStretch()
        splitter.addWidget(input_panel)

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
        self.wheel_selector.currentIndexChanged.connect(self._refresh_response_plots)
        angle_page = QWidget(); angle_layout = QVBoxLayout(angle_page)
        angle_layout.setContentsMargins(0, 0, 0, 0)
        angle_layout.addWidget(self.wheel_selector); angle_layout.addWidget(self.angle_plot, 1)
        self.cylinder_selector = QComboBox()
        self.cylinder_selector.addItems(["前通道", "后通道1", "后通道2", "后通道3"])
        self.cylinder_selector.currentIndexChanged.connect(self._refresh_response_plots)
        cylinder_page = QWidget(); cylinder_layout = QVBoxLayout(cylinder_page)
        cylinder_layout.setContentsMargins(0, 0, 0, 0)
        cylinder_layout.addWidget(self.cylinder_selector); cylinder_layout.addWidget(self.cylinder_plot, 1)
        self.wheel_table = DataTable()
        self.wheel_response_table = DataTable()
        self.cylinder_response_table = DataTable()
        self.tabs.addTab(angle_page, "十二轮转向动态")
        self.tabs.addTab(cylinder_page, "四组等效作动通道")
        self.tabs.addTab(self.wheel_response_table, "十二轮到位/稳态时间")
        self.tabs.addTab(self.cylinder_response_table, "四通道到位/稳态时间")
        self.tabs.addTab(self.pressure_plot, "供油压力")
        self.tabs.addTab(self.wheel_table, "十二轮结果")
        result_layout.addWidget(self.tabs, 1)
        splitter.addWidget(result)
        splitter.setSizes([330, 900])
        self._sync_command_controls()

    def _sync_command_controls(self) -> None:
        ramp = self.command_type.currentData() == "ramp"
        for item in (self.initial_angle, self.seconds_per_degree, self.hold_observation):
            item.setEnabled(ramp)
        self.duration.setEnabled(not ramp)

    def _scenario(self) -> dict[str, Any]:
        return {"speed_kmh": self.speed.value(),
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
        speeds = np.linspace(0, 50, 51)
        scenarios = [{"target_outer_angle_deg": float(angle),
                      "speed_kmh": float(speed),
                      "friction_coefficient": self.mu.value(),
                      "axle_mass_t": [item.value() for item in self.axles]}
                     for speed in speeds for angle in angles]
        self.run_requested.emit("batch", {"scenarios": scenarios})

    def task_finished(self, result: dict[str, Any]) -> None:
        super().task_finished(result)
        if result.get("kind") == "batch":
            self.wheel_table.set_frame(result["rows"])
            self.tabs.setCurrentWidget(self.wheel_table)
            self.banner.set_status(f"已完成 {len(result['rows'])} 个工况的准稳态能力估计。{result['note']}",
                                   "success")
            return
        samples = result["samples"]
        time = samples["time_s"]
        self._refresh_response_plots()
        self.pressure_plot.replace_curves([
            ("前供油轨", time, samples["supply_pressure_front_mpa_g"], "#1976d2"),
            ("后供油轨", time, samples["supply_pressure_rear_mpa_g"], "#d97706")])
        self.wheel_table.set_frame(result["wheel_table"])
        self.wheel_response_table.set_frame(result["wheel_response_table"].rename(columns={
            "wheel": "车轮", "final_target_deg": "最终目标/°",
            "final_actual_deg": "最终实际/°", "maximum_tracking_error_deg": "最大误差/°",
            "first_arrival_s": "首次到位/s", "settled_time_s": "稳态建立/s",
            "final_speed_deg_s": "最终角速度/(°/s)", "settled_status": "状态",
        }))
        self.cylinder_response_table.set_frame(result["cylinder_response_table"].rename(columns={
            "channel": "等效作动通道", "final_target_m": "最终目标/m",
            "final_actual_m": "最终实际/m", "final_error_m": "最终偏差/m",
            "first_arrival_s": "首次到位/s", "settled_time_s": "稳态建立/s",
            "final_velocity_m_s": "最终活塞速度/(m/s)", "settled_status": "状态",
        }))
        self.card_success.set_value("成功" if result["calculation_success"] else "失败",
                                    f"墙钟时间 {result['runtime_s']:.2f} s",
                                    "success" if result["calculation_success"] else "danger")
        self.card_tracking.set_value("达标" if result["tracking_pass"] else "需复核",
                                     "来自液压实际角与目标角", "success" if result["tracking_pass"] else "warning")
        self.card_feasible.set_value("可行" if result["trajectory_feasible"] else "超附着风险",
                                     "该判定独立于液压跟踪状态",
                                     "success" if result["trajectory_feasible"] else "warning")
        response = result["response"]
        settled = response["system_settled_s"]
        settled_text = ("未在仿真范围内稳定" if settled is None
                        else f"整机共同稳态 {settled:.2f} s")
        self.banner.set_status(
            f"本次结果来自实时22状态动态仿真；指令完成 {response['command_completion_s']:.2f} s；{settled_text}",
            "success" if settled is not None else "warning")

    def _refresh_response_plots(self) -> None:
        if not self.last_result or self.last_result.get("kind") != "simulation":
            return
        samples = self.last_result["samples"]
        response = self.last_result["response"]
        time = samples["time_s"]
        wheel_index = self.wheel_selector.currentIndex()
        axle, side_index = divmod(wheel_index, 2)
        wheel = f"axle{axle + 1}_{'left' if side_index == 0 else 'right'}"
        row = response["wheel_table"].iloc[wheel_index]
        self.angle_plot.replace_curves([
            ("目标", time, samples[f"wheel_{wheel}_command_deg"], "#708090"),
            ("液压实际", time, samples[f"wheel_{wheel}_actual_deg"], "#1976d2")])
        self.angle_plot.add_time_markers([
            ("指令完成", response["command_completion_s"], "#5d6b78"),
            ("首次到位", row["first_arrival_s"], "#d97706"),
            ("稳态建立", row["settled_time_s"], "#2e7d32"),
            ("整车共同稳态", response["system_settled_s"], "#7b1fa2")])
        channel = ("channel_front", "channel_rear_1", "channel_rear_2",
                   "channel_rear_3")[self.cylinder_selector.currentIndex()]
        cylinder_row = response["cylinder_table"].iloc[self.cylinder_selector.currentIndex()]
        self.cylinder_plot.replace_curves([
            ("目标行程", time, 1000 * samples[f"{channel}_x_ref_eff_m"], "#708090"),
            ("实际行程", time, 1000 * samples[f"{channel}_x_m"], "#1976d2")])
        self.cylinder_plot.add_time_markers([
            ("指令完成", response["command_completion_s"], "#5d6b78"),
            ("首次到位", cylinder_row["first_arrival_s"], "#d97706"),
            ("稳态建立", cylinder_row["settled_time_s"], "#2e7d32"),
            ("四通道共同稳态", response["all_cylinders_settled_s"], "#7b1fa2")])

    def project_payload(self) -> dict[str, Any]:
        return self._scenario()


SPECTRUM_COLUMNS = [
    "segment_id", "speed_kmh", "target_outer_angle_deg", "segment_duration_s",
    "friction_coefficient", *[f"axle_mass_{i}_t" for i in range(1, 7)],
    "pump_running", "repeats", "contamination_severity", "oil_temperature_c"]


class SpectrumPage(WorkPage):
    spectrum_changed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__("spectrum", parent)
        self.path = str(EXAMPLE_SPECTRUM)
        root = QVBoxLayout(self)
        root.addWidget(title_block("任务载荷谱",
            "每行是一个连续工况段；保持任务顺序、段间转向动作和独立持续时间语义。"))
        toolbar = QHBoxLayout()
        for text, slot in (("导入CSV/XLSX", self.import_file), ("打开30天示例", self.load_example),
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
        self.table.setHorizontalHeaderLabels(SPECTRUM_COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
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
        self.table.blockSignals(True)
        self.table.setRowCount(len(frame))
        for row in range(len(frame)):
            for column, name in enumerate(SPECTRUM_COLUMNS):
                value = frame.iloc[row].get(name, "")
                self.table.setItem(row, column, QTableWidgetItem("" if pd.isna(value) else str(value)))
        self.table.blockSignals(False)
        if path:
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
        frame = pd.read_csv(path) if Path(path).suffix.lower() == ".csv" else pd.read_excel(path)
        self.load_frame(frame, path)

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
                    *(["11.5"] * 6), "True", "1", "1.0", "40"]
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
            self.banner.set_status("任务谱为空，请添加或导入工况段", "warning")
            return
        durations = pd.to_numeric(frame["segment_duration_s"], errors="coerce")
        repeats = pd.to_numeric(frame["repeats"], errors="coerce").fillna(1)
        if durations.isna().any() or (durations <= 0).any():
            self.banner.set_status("存在非数值或非正的持续时间", "error")
            return
        elapsed = (durations * repeats).cumsum() / 86400.0
        days = float(elapsed.iloc[-1])
        level = "success" if abs(days - 30) <= 1 / 86400 else "warning"
        relation = "等于30天" if level == "success" else ("不足30天" if days < 30 else "超过30天")
        self.banner.set_status(
            f"共 {len(frame)} 行，展开后约 {int(repeats.sum())} 段，总时长 {days:.6f} 天：{relation}。",
            level)
        speed = pd.to_numeric(frame["speed_kmh"], errors="coerce").fillna(0)
        angle = pd.to_numeric(frame["target_outer_angle_deg"], errors="coerce").fillna(0)
        x = np.r_[0.0, elapsed.to_numpy()]
        self.speed_plot.replace_curves([("车速", x, np.r_[speed.iloc[0], speed], "#1976d2")])
        self.angle_plot.replace_curves([("目标转角", x, np.r_[angle.iloc[0], angle], "#d97706")])

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
        self.banner = StatusBanner("工程假设预测，待甲方试验标定")
        root.addWidget(self.banner)
        cards = QHBoxLayout()
        self.pump_card = MetricCard("齿轮泵", "2台 × 2模式", "不是柱塞泵")
        self.valve_card = MetricCard("转向阀", "4组 × 2模式", "内泄漏 / 响应迟滞")
        self.cylinder_card = MetricCard("等效液压缸", "4组 × 2模式", "不是7个独立物理缸")
        self.time_card = MetricCard("计算耗时")
        for card in (self.pump_card, self.valve_card, self.cylinder_card, self.time_card):
            cards.addWidget(card)
        root.addLayout(cards)
        self.tabs = QTabWidget()
        self.damage_plot = EngineeringPlot("第0～30天损伤曲线", "累计损伤 (-)", "任务时间 (day)")
        self.component_table = DataTable()
        self.segment_table = DataTable()
        self.rainflow_table = DataTable()
        self.tabs.addTab(self.damage_plot, "退化曲线")
        self.tabs.addTab(self.component_table, "部件与模式")
        self.tabs.addTab(self.segment_table, "逐段损伤贡献")
        self.tabs.addTab(self.rainflow_table, "雨流与等效载荷")
        root.addWidget(self.tabs, 1)

    def set_spectrum(self, path: str) -> None:
        if path:
            self.spectrum_path = path
            self.path_edit.setText(path)

    def _run(self) -> None:
        self.run_requested.emit("degradation", {
            "spectrum_path": self.spectrum_path,
            "initial_state": self.initial.currentData()})

    def task_finished(self, result: dict[str, Any]) -> None:
        super().task_finished(result)
        curve = result["curve_frame"]
        colors = ["#1976d2", "#2e7d32", "#d97706", "#7b1fa2", "#607d8b"]
        columns = [column for column in curve.columns if column.startswith("cumulative_damage")]
        self.damage_plot.replace_curves([
            (column.replace("cumulative_damage_", ""), curve["day"], curve[column],
             colors[index % len(colors)]) for index, column in enumerate(columns[:10])])
        self.component_table.set_frame(result["component_frame"])
        self.segment_table.set_frame(result["segment_frame"])
        self.rainflow_table.set_frame(result["rainflow_frame"])
        self.time_card.set_value(f"{result['runtime_s']:.2f} s", "30天快速解析预测", "success")
        self.banner.set_status(
            f"30天退化预测完成；风险提示 {len(result['risks'])} 条。"
            "所有退化系数均为工程假设，待甲方标定。", "success")

    def project_payload(self) -> dict[str, Any]:
        return {"spectrum_path": self.spectrum_path,
                "initial_state": self.initial.currentData()}


class QualityPage(WorkPage):
    def __init__(self, parent=None) -> None:
        super().__init__("quality", parent)
        root = QVBoxLayout(self)
        root.addWidget(title_block("当前质量性能评估",
            "使用D2 QualityAssessor执行真实22状态标准转向测试；机械阿克曼固有偏差与液压跟踪误差分别报告。"))
        controls = QHBoxLayout()
        self.source = QComboBox()
        self.source.addItem("全新健康状态", "healthy")
        self.source.addItem("轻度指定退化（敏感性）", "specified_light")
        self.source.addItem("中度指定退化（敏感性）", "specified_medium")
        self.source.addItem("重度指定退化（敏感性）", "specified_heavy")
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
        self.tabs = QTabWidget()
        self.result_table = DataTable()
        self.angle_plot = EngineeringPlot("健康/退化动态响应", "一桥右轮转角 (°)", "时间 (s)")
        self.pressure_plot = EngineeringPlot("供油压力动态", "压力 (MPa)", "时间 (s)")
        self.tabs.addTab(self.result_table, "质量指标与下降原因")
        self.tabs.addTab(self.angle_plot, "轮角对比")
        self.tabs.addTab(self.pressure_plot, "供压对比")
        root.addWidget(self.tabs, 1)
        self._sync_severity()

    def _sync_severity(self) -> None:
        values = [0.0, 0.25, 0.55, 0.85]
        self.severity.setValue(values[self.source.currentIndex()])
        self.severity.setEnabled(self.source.currentIndex() != 0)

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
        self.grade_card.set_value(GRADE_CN[grade], grade, level)
        self.error_card.set_value(f"{rows['max_tracking_error_deg'].max():.4f} °",
                                  "液压实际轮角相对命令")
        self.margin_card.set_value(f"{rows['minimum_pump_flow_margin_lpm'].min():.3f} L/min",
                                   "负值表示瞬态需求超过泵能力",
                                   "warning" if rows['minimum_pump_flow_margin_lpm'].min() < 0 else "success")
        self.source_card.set_value(result["natural_or_sensitivity"],
                                   "不会与自然30天退化混淆")
        colors = ["#1976d2", "#d97706", "#7b1fa2"]
        angle_curves, pressure_curves = [], []
        for index, dynamic in enumerate(result["dynamics"]):
            samples = dynamic.samples
            angle_curves.append((dynamic.case.id, samples["time_s"],
                                 samples["wheel_axle1_right_actual_deg"], colors[index]))
            pressure_curves.append((dynamic.case.id, samples["time_s"],
                                    samples["supply_pressure_front_mpa_g"], colors[index]))
        self.angle_plot.replace_curves(angle_curves)
        self.pressure_plot.replace_curves(pressure_curves)
        causes = "；".join(str(value) for value in rows["grade_causes"] if str(value))
        self.banner.set_status(f"评估完成：{GRADE_CN[grade]}。下降原因：{causes or '无'}", level)

    def project_payload(self) -> dict[str, Any]:
        return {"state_source": self.source.currentData(),
                "severity": self.severity.value()}


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
        root.addLayout(controls)
        self.banner = StatusBanner("工程假设预测，待甲方试验标定")
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
        self.quality_plot = EngineeringPlot("系统质量等级演化", "等级序号", "30天任务循环")
        self.distribution_plot = EngineeringPlot("随机寿命分布", "累计概率", "首次失效任务循环")
        self.mode_table = DataTable()
        self.tabs.addTab(self.damage_plot, "部件退化")
        self.tabs.addTab(self.quality_plot, "系统质量")
        self.tabs.addTab(self.distribution_plot, "随机寿命")
        self.tabs.addTab(self.mode_table, "临界部件参数")
        root.addWidget(self.tabs, 1)
        assumption = QLabel("醒目提示：寿命与随机区间均为工程假设下的预测结果，待甲方耐久试验标定。"
                            "Monte Carlo采用快速近似载荷推进，并非每条路径均执行完整22状态验证。")
        assumption.setObjectName("criticalNotice")
        assumption.setWordWrap(True)
        root.addWidget(assumption)

    def set_spectrum(self, path: str) -> None:
        if path:
            self.spectrum_path = path
            self.path_edit.setText(path)

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
            "detailed": self.mode.currentText() == "详细模式"})

    def task_finished(self, result: dict[str, Any]) -> None:
        super().task_finished(result)
        summary = result["summary"]
        status = summary["prediction_status"]
        level = "danger" if status == "FAILURE_REACHED" else "warning"
        remaining = summary.get("remaining_complete_30day_cycles")
        self.cycles_card.set_value("未在范围内达到" if remaining is None else f"{remaining} 次",
                                   "从当前状态起可完整执行的任务数", level)
        cycle = summary.get("first_failure_cycle")
        segment = summary.get("first_failure_segment_id") or "—"
        day = summary.get("first_failure_day_in_cycle")
        self.failure_card.set_value("—" if cycle is None else f"第{cycle}次任务",
                                    "无越限" if cycle is None else
                                    f"{str(segment).split('-')[0]}-{str(segment).split('-')[1]}段末检测；第{day:.6f}天",
                                    level)
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
        mode_names = {"response_lag": "响应迟滞", "internal_leakage": "内泄漏",
                      "mechanical_loss": "机械损失", "friction": "摩擦增大"}
        display_factors = [factor_names.get(item, item) for item in factors]
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
            display_reasons.append(translated)
        self.limiter_card.set_value(" / ".join(display_factors) or "—",
                                    "；".join(display_reasons), level)
        metrics = result["mc_summary"]
        quantiles = {row["metric"]: row["value"] for _, row in metrics.iterrows()
                     if row["metric"] in {"p05", "p50", "p95"}}
        self.quantile_card.set_value(
            f"{quantiles.get('p05', '—')} / {quantiles.get('p50', '—')} / {quantiles.get('p95', '—')}",
            "随机路径寿命分位区间，不是均值置信区间")
        history = result["history"]
        damage_columns = [column for column in history if column not in
                          {"mission_cycle", "mission_days_elapsed", "cycle_completed"}
                          and not column.startswith("increment_")]
        if damage_columns:
            maximum = history[damage_columns].apply(pd.to_numeric, errors="coerce").max(axis=1)
            self.damage_plot.replace_curves([("最大模式损伤", history["mission_cycle"], maximum, "#1976d2")])
        quality = result["quality"]
        if not quality.empty:
            grade = quality["rated_quality_grade"].map(
                {"HEALTHY": 0, "SUBHEALTHY": 1, "DEGRADED": 2, "DANGEROUS": 3})
            self.quality_plot.replace_curves([("额定质量等级", quality["mission_cycle"], grade, "#d97706")])
        samples = pd.to_numeric(result["mc_samples"].get("failure_cycle"), errors="coerce").dropna().sort_values()
        if len(samples):
            probability = np.arange(1, len(samples) + 1) / len(samples)
            self.distribution_plot.replace_curves([("经验CDF", samples, probability, "#7b1fa2")])
        self.mode_table.set_frame(result["modes"])
        explanation = STATUS_CN.get(status, status)
        self.banner.set_status(
            f"{explanation}。第{cycle}次任务的{str(segment).split('-')[0]}-{str(segment).split('-')[1]}段检测到首次越限；"
            "记录时刻是段末检测时刻，不是段内精确失效瞬间。" if cycle else explanation,
            "error" if status == "INDETERMINATE" else "warning")

    def project_payload(self) -> dict[str, Any]:
        return {"spectrum_path": self.spectrum_path,
                "initial_state": self.initial.currentData(),
                "custom_initial_path": self.custom_initial_path,
                "maximum_cycles": self.max_cycles.value(),
                "stochastic": self.stochastic.isChecked(),
                "samples": self.samples.value(), "seed": self.seed.value(),
                "mode": self.mode.currentText()}
