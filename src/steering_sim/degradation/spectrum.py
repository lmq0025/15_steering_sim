"""30 天分段任务谱数据模型与 CSV/XLSX 输入。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import warnings

import pandas as pd


REQUIRED_COLUMNS = (
    "segment_id", "speed_kmh", "target_outer_angle_deg", "segment_duration_s",
    "friction_coefficient", "axle_mass_1_t", "axle_mass_2_t",
    "axle_mass_3_t", "axle_mass_4_t", "axle_mass_5_t", "axle_mass_6_t",
    "pump_running",
)
OPTIONAL_COLUMNS = ("repeats", "contamination_severity", "oil_temperature_c", "seconds_per_degree")
SECONDS_PER_DAY = 86400.0
COLUMN_LABELS = dict(zip(REQUIRED_COLUMNS, (
    '工况段编号','车速（km/h）','一桥外轮最终转角（°）','整段时间（s）','附着系数',
    *[f'第{i}桥轴荷（t）' for i in range(1,7)],'泵运行')))
COLUMN_LABELS.update(repeats='重复次数', contamination_severity='污染严重度',
                     oil_temperature_c='油温（℃）', seconds_per_degree='每度转向时间（秒/度）')


def normalize_columns(frame):
    return frame.rename(columns={value:key for key,value in COLUMN_LABELS.items()})


class SpectrumError(ValueError):
    """任务谱缺列、单位/范围错误或总时长不符。"""


def _boolean(value: object, row: int) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and float(value) in (0.0, 1.0):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "yes", "y", "1", "运行", "开", "是"}:
        return True
    if text in {"false", "no", "n", "0", "停机", "关", "否"}:
        return False
    raise SpectrumError(f"第 {row} 行 pump_running={value!r} 不是布尔值")


@dataclass(frozen=True, slots=True)
class TaskSegment:
    segment_id: str
    speed_kmh: float
    target_outer_angle_deg: float
    segment_duration_s: float
    friction_coefficient: float
    axle_mass_t: tuple[float, float, float, float, float, float]
    pump_running: bool
    repeats: int = 1
    contamination_severity: float = 1.0
    oil_temperature_c: float = 40.0
    seconds_per_degree: float | None = None  # None is the documented D1/D3 legacy API.

    def __post_init__(self) -> None:
        values = (self.speed_kmh, self.target_outer_angle_deg,
                  self.segment_duration_s, self.friction_coefficient,
                  *self.axle_mass_t, self.contamination_severity,
                  self.oil_temperature_c)
        if not all(math.isfinite(value) for value in values):
            raise SpectrumError(f"{self.segment_id}: 存在 NaN/Inf")
        if self.segment_duration_s <= 0.0:
            raise SpectrumError(f"{self.segment_id}: segment_duration_s 必须为正")
        if self.speed_kmh < 0.0 or self.friction_coefficient < 0.0:
            raise SpectrumError(f"{self.segment_id}: 车速和附着系数不得为负")
        if any(value <= 0.0 for value in self.axle_mass_t):
            raise SpectrumError(f"{self.segment_id}: 六桥轴荷必须为正")
        if self.repeats < 1:
            raise SpectrumError(f"{self.segment_id}: repeats 必须为正整数")
        if self.contamination_severity < 0.0:
            raise SpectrumError(f"{self.segment_id}: 污染严重度不得为负")
        if self.seconds_per_degree is not None and (
                not math.isfinite(self.seconds_per_degree) or self.seconds_per_degree <= 0):
            raise SpectrumError(f"{self.segment_id}: 每度转向时间须为有限正数")


@dataclass(frozen=True, slots=True)
class TaskSpectrum:
    segments: tuple[TaskSegment, ...]
    source: Path

    @property
    def total_duration_s(self) -> float:
        return sum(item.segment_duration_s * item.repeats for item in self.segments)

    @property
    def total_days(self) -> float:
        return self.total_duration_s / SECONDS_PER_DAY

    def expanded(self):
        for segment in self.segments:
            for repeat_index in range(segment.repeats):
                yield segment, repeat_index + 1

    def validate_transitions(self, initial_angle: float = 0.0) -> None:
        previous = initial_angle
        for segment, _ in self.expanded():
            change = abs(segment.target_outer_angle_deg-previous)
            if change > 1e-12 and not segment.pump_running:
                raise SpectrumError(f"{segment.segment_id}: 泵停机时不能完成新的转向动作")
            if segment.seconds_per_degree is not None:
                required = change*segment.seconds_per_degree
                if required > segment.segment_duration_s+1e-9:
                    raise SpectrumError(f"{segment.segment_id}: 转向需 {required:g} 秒，任务段仅 {segment.segment_duration_s:g} 秒（严格模式）")
            if segment.pump_running:
                previous = segment.target_outer_angle_deg


def load_task_spectrum(path: str | Path, *, expected_days: float | None = 30.0,
                       duration_tolerance_s: float = 1.0) -> TaskSpectrum:
    source = Path(path)
    if not source.exists():
        raise SpectrumError(f"任务谱不存在：{source}")
    suffix = source.suffix.lower()
    if suffix == ".csv":
        frame = pd.read_csv(source)
    elif suffix in {".xlsx", ".xls"}:
        frame = pd.read_excel(source)
    else:
        raise SpectrumError(f"仅支持 CSV/XLSX，收到 {suffix or '无扩展名'}")
    frame = normalize_columns(frame)
    missing = [name for name in REQUIRED_COLUMNS if name not in frame.columns]
    if missing:
        raise SpectrumError("任务谱缺少必需列：" + ", ".join(missing))
    if frame.empty:
        raise SpectrumError("任务谱没有工况行")
    if "seconds_per_degree" not in frame or frame['seconds_per_degree'].isna().any():
        warnings.warn("旧任务谱缺少每度转向时间：沿用历史12°/s及最短0.4s兼容口径；新任务应显式填写6秒/度。", UserWarning)

    segments: list[TaskSegment] = []
    for position, row in frame.iterrows():
        excel_row = int(position) + 2
        try:
            repeats_value = row.get("repeats", 1)
            repeats = 1 if pd.isna(repeats_value) else int(repeats_value)
            if not pd.isna(repeats_value) and float(repeats_value) != repeats:
                raise SpectrumError(f"第 {excel_row} 行 repeats 必须为整数")
            contamination = row.get("contamination_severity", 1.0)
            temperature = row.get("oil_temperature_c", 40.0)
            segments.append(TaskSegment(
                segment_id=str(row["segment_id"]),
                speed_kmh=float(row["speed_kmh"]),
                target_outer_angle_deg=float(row["target_outer_angle_deg"]),
                segment_duration_s=float(row["segment_duration_s"]),
                friction_coefficient=float(row["friction_coefficient"]),
                axle_mass_t=tuple(float(row[f"axle_mass_{i}_t"])
                                  for i in range(1, 7)),  # type: ignore[arg-type]
                pump_running=_boolean(row["pump_running"], excel_row),
                repeats=repeats,
                contamination_severity=(1.0 if pd.isna(contamination)
                                        else float(contamination)),
                oil_temperature_c=(40.0 if pd.isna(temperature)
                                   else float(temperature)),
                seconds_per_degree=(None if pd.isna(row.get("seconds_per_degree"))
                                    else float(row["seconds_per_degree"]))))
        except SpectrumError:
            raise
        except Exception as exc:
            raise SpectrumError(f"第 {excel_row} 行解析失败：{exc}") from exc

    spectrum = TaskSpectrum(tuple(segments), source.resolve())
    # Legacy spectra retain their original pump-off handling; explicit-rate
    # inputs opt into strict transition validation.
    if any(s.seconds_per_degree is not None for s in spectrum.segments):
        spectrum.validate_transitions()
    if expected_days is not None:
        expected_s = float(expected_days) * SECONDS_PER_DAY
        delta = spectrum.total_duration_s - expected_s
        if abs(delta) > duration_tolerance_s:
            relation = "不足" if delta < 0.0 else "超过"
            raise SpectrumError(
                f"任务谱总时长 {spectrum.total_days:.6f} 天，{relation}用户指定的 "
                f"{expected_days:.6f} 天 {abs(delta):.1f} s；程序不会自动补足或截断。")
    return spectrum
