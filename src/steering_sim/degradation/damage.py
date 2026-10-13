"""泵、阀、缸共用的确定性非负累积框架。"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
import math
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class ComponentDamageState:
    damage: float = 0.0
    exposure: float = 0.0

    def advanced(self, *, rate: float, equivalent_exposure: float,
                 state_factor_alpha: float, maximum_damage: float) -> tuple["ComponentDamageState", float]:
        """解析积分 ``dD/dE=rate*(1+alpha*D)``，保证等价切分不改变结果。"""
        if rate < 0.0 or equivalent_exposure < 0.0:
            raise ValueError("rate 和 equivalent_exposure 不得为负")
        if state_factor_alpha < 0.0 or maximum_damage <= 0.0:
            raise ValueError("state_factor_alpha/maximum_damage 非物理")
        old = min(max(0.0, self.damage), maximum_damage)
        dose = rate * equivalent_exposure
        if state_factor_alpha == 0.0:
            new = old + dose
        else:
            new = ((old + 1.0 / state_factor_alpha)
                   * math.exp(state_factor_alpha * dose)
                   - 1.0 / state_factor_alpha)
        new = min(maximum_damage, max(old, new))
        return replace(self, damage=new,
                       exposure=self.exposure + equivalent_exposure), new - old


@dataclass(frozen=True, slots=True)
class DegradationState:
    pumps: Mapping[str, ComponentDamageState] = field(default_factory=lambda: {
        "front": ComponentDamageState(), "rear": ComponentDamageState()})
    valves: Mapping[str, ComponentDamageState] = field(default_factory=dict)
    cylinders: Mapping[str, ComponentDamageState] = field(default_factory=dict)

    @staticmethod
    def healthy(channels: tuple[str, ...]) -> "DegradationState":
        return DegradationState(
            pumps={"front": ComponentDamageState(), "rear": ComponentDamageState()},
            valves={name: ComponentDamageState() for name in channels},
            cylinders={name: ComponentDamageState() for name in channels})

    @property
    def max_damage(self) -> float:
        items = (*self.pumps.values(), *self.valves.values(), *self.cylinders.values())
        return max((item.damage for item in items), default=0.0)


@dataclass(frozen=True, slots=True)
class DegradationModelConfig:
    raw: Mapping[str, Any]
    model_version: str
    assumption_tag: str

    def component(self, name: str) -> Mapping[str, float]:
        return self.raw[name]


def load_degradation_config(path: str | Path) -> DegradationModelConfig:
    source = Path(path)
    raw = json.loads(source.read_text(encoding="utf-8"))
    if raw.get("schema_version") != "D1.0":
        raise ValueError(f"不支持的退化配置版本：{raw.get('schema_version')!r}")
    if raw.get("assumption_tag") != "ENGINEERING_DESIGN_ASSUMPTION":
        raise ValueError("D1 未标定参数必须标记 ENGINEERING_DESIGN_ASSUMPTION")
    for name in ("pump", "valve", "cylinder"):
        if name not in raw:
            raise ValueError(f"退化配置缺少 {name}")
    return DegradationModelConfig(raw=raw,
                                  model_version=str(raw["model_version"]),
                                  assumption_tag=str(raw["assumption_tag"]))
