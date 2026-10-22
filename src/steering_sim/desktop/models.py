"""Qt data models and traceable project persistence."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
import json
from pathlib import Path
from typing import Any

import pandas as pd
from .localization import cn
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QSortFilterProxyModel


class DataFrameModel(QAbstractTableModel):
    def __init__(self, frame: pd.DataFrame | None = None, parent=None) -> None:
        super().__init__(parent)
        self._frame = (frame.copy() if frame is not None else pd.DataFrame())

    @property
    def frame(self) -> pd.DataFrame:
        return self._frame.copy()

    def set_frame(self, frame: pd.DataFrame) -> None:
        self.beginResetModel()
        self._frame = frame.copy()
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._frame)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._frame.columns)

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        value = self._frame.iat[index.row(), index.column()]
        if role in (Qt.DisplayRole, Qt.EditRole):
            if pd.isna(value):
                return ""
            if isinstance(value, float):
                name=str(self._frame.columns[index.column()])
                if any(k in name for k in ('arrival_s','settled_time','convergence_s','delay_s','到位','稳态建立','额外收敛','指令完成')) and (value==0 or abs(value)>=1e-4):
                    return f'{value:.2f}'
                return f"{value:.6g}"
            return cn(value)
        if role == Qt.TextAlignmentRole:
            return int(Qt.AlignVCenter | (Qt.AlignRight if isinstance(value, (int, float))
                                          else Qt.AlignLeft))
        return None

    def headerData(self, section: int, orientation, role=Qt.DisplayRole):  # noqa: N802
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return cn(self._frame.columns[section])
        return str(section + 1)

    def sort(self, column: int, order=Qt.AscendingOrder) -> None:
        if self._frame.empty:
            return
        self.layoutAboutToBeChanged.emit()
        name = self._frame.columns[column]
        self._frame = self._frame.sort_values(
            name, ascending=order == Qt.AscendingOrder,
            kind="mergesort", na_position="last").reset_index(drop=True)
        self.layoutChanged.emit()


class DataFrameProxyModel(QSortFilterProxyModel):
    """Filter Qt display text, but sort the typed pandas source in one batch.

    Avoid Python cell callbacks O(n log n) through Qt when a new large result
    is assigned. Source sort uses actual numbers rather than display strings.
    """
    def sort(self, column: int, order=Qt.AscendingOrder) -> None:
        source=self.sourceModel()
        if column>=0 and source is not None:
            source.sort(column,order)
        super().sort(-1,order)


@dataclass
class ProjectState:
    schema_version: str = "D4.0"
    name: str = "未命名工程"
    spectrum_path: str = ""
    initial_state: str = "d1_day30"
    maximum_cycles: int = 240
    monte_carlo_enabled: bool = True
    monte_carlo_samples: int = 128
    random_seed: int = 20261013
    mode: str = "快速模式"
    page_inputs: dict[str, Any] = field(default_factory=dict)
    completed_modules: dict[str, bool] = field(default_factory=dict)
    result_paths: dict[str, str] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2),
                          encoding="utf-8")
        return target

    @staticmethod
    def load(path: str | Path) -> "ProjectState":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if raw.get("schema_version") != "D4.0":
            raise ValueError(f"不支持的工程文件版本：{raw.get('schema_version')}")
        inputs=raw.get('page_inputs',{})
        if 'forecast_mode' not in inputs.get('degradation',{}) and 'stochastic' not in inputs.get('degradation',{}):
            raw.setdefault('provenance',{})['compatibility_rules']={
                'degradation_forecast':'旧工程未设置随机预测，默认确定性、128条、种子20261013；选择随机后才计算路径',
                'spectrum_rate':'旧任务行缺少速率保持12°/s及最短0.4s，新行显式6秒/度',
                'ramp_reference':'斜坡输入按R2严格一桥外轮角定义；历史结果仅保留路径，不作为新结果'}
        known = ProjectState.__dataclass_fields__
        return ProjectState(**{key: value for key, value in raw.items() if key in known})
