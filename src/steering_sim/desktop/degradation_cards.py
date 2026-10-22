"""Presentation summaries from the same forecast's final physical statistics.

No wear equations or sampling live here.  In a Gamma forecast the mean/P50 is
read *after* the official pathwise physical mapping, just like the plot/export.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
import pandas as pd

from .localization import cn


@dataclass(frozen=True)
class ComponentCardSummary:
    value: str
    note: str
    metric: str
    component_id: str
    numeric_value: float


def final_component_summary(result: Mapping[str, Any], center: str = "mean"
                            ) -> tuple[dict[str, ComponentCardSummary], pd.DataFrame]:
    """Return cards and an exportable final-day parameter table, without mutation.

    Missing or nonfinite final physical results are an explicit display failure;
    no healthy fallback or prior run is used.  Deterministic runs always read the
    deterministic column regardless of the last stochastic display selection.
    """
    if center not in ("mean", "p50"):
        raise ValueError("部件摘要只支持随机均值或P50")
    statistics = result["statistics"]
    if statistics.empty:
        raise ValueError("本次预测没有可用的部件参数统计")
    day = float(statistics["day"].max())
    if not np.isfinite(day) or not np.isclose(day, 30.0, rtol=0, atol=1e-8):
        raise ValueError("部件摘要缺少第30天真实预测末态")
    final = statistics.loc[statistics["day"] == day].copy()
    if final["metric"].duplicated().any():
        raise ValueError("第30天部件参数存在重复记录")
    stochastic = int(result["sample_count"]) > 0
    column = center if stochastic else "deterministic"
    label = ("随机均值" if center == "mean" else "随机P50") if stochastic else "确定性值"
    label += f"（{int(result['sample_count'])}条路径）" if stochastic else ""
    physical = final.loc[~final["metric"].isin(result["mode_keys"])].copy()
    indexed = physical.set_index("metric")
    channels = ("channel_front", "channel_rear_1", "channel_rear_2", "channel_rear_3")

    def values(kind: str, names: tuple[str, ...], metric: str) -> pd.Series:
        keys = [f"{kind}:{name}:{metric}" for name in names]
        missing = [key for key in keys if key not in indexed.index]
        if missing:
            raise ValueError("第30天部件参数缺失：" + "、".join(cn(k) for k in missing))
        series = indexed.loc[keys, column].astype(float)
        if not np.isfinite(series.to_numpy()).all():
            raise ValueError("第30天部件参数含非有限数值")
        return series

    pumps = values("pump", ("front", "rear"), "volumetric_efficiency")
    valves = values("valve", channels, "lag_scale")
    friction = values("cylinder", channels, "friction_scale")
    leakage = values("cylinder", channels, "reference_leakage_lpm")
    worst_pump, worst_valve, worst_cylinder = str(pumps.idxmin()), str(valves.idxmax()), str(friction.idxmax())
    ref = result["reference_conditions"]
    pressure = float(ref["pressure_pa"]) / 1e6
    temperature = float(ref["temperature_c"])

    def component(key: str) -> str:
        return ":".join(key.split(":")[:2])

    prefix = f"第{day:g}天｜{label}"
    cards = {
        "pump": ComponentCardSummary(
            f"两泵容积效率 {pumps.min()*100:.3f}～{pumps.max()*100:.3f}%",
            f"{prefix}\n最低：{cn(component(worst_pump))}\n参考压差{pressure:g} MPa、{temperature:g}℃、各泵额定转速",
            worst_pump, component(worst_pump), float(pumps.min())),
        "valve": ComponentCardSummary(
            f"最大迟滞 {valves.max():.4f} 倍",
            f"{prefix}\n{cn(component(worst_valve))}\n相对健康阀响应时间常数",
            worst_valve, component(worst_valve), float(valves.max())),
        "cylinder": ComponentCardSummary(
            f"最大摩擦 {friction.max():.4f} 倍",
            f"{prefix}\n{cn(component(worst_cylinder))}\n最大内泄漏 {leakage.max():.4g} L/min（参考压差{pressure:g} MPa）",
            worst_cylinder, component(worst_cylinder), float(friction.max())),
    }
    physical.insert(1, "component_type", physical["metric"].str.split(":").str[0])
    physical.insert(2, "component_id", physical["metric"].map(component))
    physical.insert(3, "统计口径", label)
    physical.insert(4, "value", physical[column])
    physical["参考压差（MPa）"] = pressure
    return cards, physical.reset_index(drop=True)
