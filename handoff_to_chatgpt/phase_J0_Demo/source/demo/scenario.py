"""PHASE J0-DEMO 工况输入、范围校验与适用性边界。

本模块只描述"用户想算什么"，不做任何仿真。它把三类范围严格区分开：

``CUSTOMER_LIMITS``
    甲方任务书给出的完整输入范围。界面允许录入，但录入不代表模型可用。
``VERIFIED_LIMITS``
    已经完成控制—液压—机械动态联调、有 J0-R1 证据的工作范围。超出即
    ``EXTRAPOLATION``，必须显式提示，不得静默外推。
``ENGINEERING_DEFAULTS``
    摩擦系数 0.75、每桥轴荷 11.5 t，均来自 M1 默认扫描值，是**工程假设**，
    不是实车测量值。

所有默认值都带 ``ASSUMED`` 标记，界面与报告必须原样转述，不能升级成已确认事实。
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import math
from typing import Mapping

AXLE_COUNT = 6

# 甲方任务书给出的完整输入范围（允许录入，不代表模型已验证）。
CUSTOMER_LIMITS: Mapping[str, tuple[float, float]] = {
    "target_outer_angle_deg": (-30.0, 30.0),
    "speed_kmh": (0.0, 80.0),
    "friction_coefficient": (0.7, 0.8),
    "axle_mass_t": (10.0, 13.0),
    "duration_s": (0.5, 60.0),
}

# 已完成动态联调并有 J0-R1 证据的范围。超出即外推。
VERIFIED_LIMITS: Mapping[str, tuple[float, float]] = {
    "target_outer_angle_deg": (-5.0, 5.0),
    "speed_kmh": (0.0, 10.0),
    "friction_coefficient": (0.75, 0.75),
    "axle_mass_t": (11.5, 11.5),
    "duration_s": (0.5, 60.0),
}

VERIFIED_RANGE_SOURCE = (
    "PHASE_J0_R1 四工况（0°/0 km/h、±2°/5 km/h、+5°/10 km/h），摩擦系数 0.75、"
    "每桥轴荷 11.5 t。这是当前唯一有控制—液压—机械闭环证据的范围。"
)

ENGINEERING_DEFAULTS = {
    "friction_coefficient": 0.75,
    "axle_mass_t": 11.5,
    "duration_s": 5.0,
    "source": "ASSUMED_ENGINEERING_PARAMETER（M1 默认扫描值），不是实车测量值",
}


@dataclass(frozen=True, slots=True)
class DemoScenario:
    """一次演示仿真的完整输入。"""

    target_outer_angle_deg: float
    speed_kmh: float
    friction_coefficient: float = ENGINEERING_DEFAULTS["friction_coefficient"]
    axle_mass_t: tuple[float, ...] = (ENGINEERING_DEFAULTS["axle_mass_t"],) * AXLE_COUNT
    duration_s: float = ENGINEERING_DEFAULTS["duration_s"]
    case_id: str = "DEMO"

    def __post_init__(self) -> None:
        if len(self.axle_mass_t) != AXLE_COUNT:
            raise ValueError(f"axle_mass_t 必须是 {AXLE_COUNT} 个值")
        values = (self.target_outer_angle_deg, self.speed_kmh,
                  self.friction_coefficient, self.duration_s, *self.axle_mass_t)
        if not all(math.isfinite(float(value)) for value in values):
            raise ValueError("工况输入必须是有限数值")
        if self.duration_s <= 0.0:
            raise ValueError("仿真时长必须为正")

    @property
    def total_mass_t(self) -> float:
        return float(sum(self.axle_mass_t))

    def signature(self) -> str:
        """用于缓存键与"预设回放/重新运行"判定的稳定标识。"""
        loads = "-".join(f"{value:.4f}" for value in self.axle_mass_t)
        return (f"a{self.target_outer_angle_deg:+.4f}_v{self.speed_kmh:.4f}"
                f"_mu{self.friction_coefficient:.4f}_m{loads}_t{self.duration_s:.3f}")

    def describe(self) -> str:
        loads = {f"{value:.2f}" for value in self.axle_mass_t}
        mass = "/".join(sorted(loads))
        return (f"一桥外侧目标转角 {self.target_outer_angle_deg:+.2f}°，"
                f"车速 {self.speed_kmh:.1f} km/h，摩擦系数 "
                f"{self.friction_coefficient:.2f}，每桥轴荷 {mass} t，"
                f"时长 {self.duration_s:.1f} s")

    def with_angle(self, angle_deg: float) -> "DemoScenario":
        return replace(self, target_outer_angle_deg=float(angle_deg))


@dataclass(frozen=True, slots=True)
class RangeCheck:
    """单个输入量的范围判定结果。"""

    field: str
    label: str
    value: float
    unit: str
    customer_range: tuple[float, float]
    verified_range: tuple[float, float]

    @property
    def outside_customer(self) -> bool:
        low, high = self.customer_range
        return self.value < low - 1.0e-9 or self.value > high + 1.0e-9

    @property
    def outside_verified(self) -> bool:
        low, high = self.verified_range
        return self.value < low - 1.0e-9 or self.value > high + 1.0e-9

    def message(self) -> str:
        if self.outside_customer:
            low, high = self.customer_range
            return (f"{self.label} {self.value:g} {self.unit} 超出甲方任务书范围 "
                    f"[{low:g}, {high:g}] {self.unit}")
        if self.outside_verified:
            low, high = self.verified_range
            return (f"{self.label} {self.value:g} {self.unit} 超出已验证动态联调范围 "
                    f"[{low:g}, {high:g}] {self.unit}，结果属于外推")
        return ""


LABELS = {
    "target_outer_angle_deg": ("一桥外侧目标转角", "°"),
    "speed_kmh": ("车速", "km/h"),
    "friction_coefficient": ("地面摩擦系数", "—"),
    "axle_mass_t": ("每桥轴荷", "t"),
    "duration_s": ("仿真时长", "s"),
}


def check_ranges(scenario: DemoScenario) -> tuple[RangeCheck, ...]:
    """逐项返回范围判定；轴荷取六桥中的最不利值。"""
    loads_low = min(scenario.axle_mass_t)
    loads_high = max(scenario.axle_mass_t)
    load_value = loads_low if abs(loads_low - 11.5) >= abs(loads_high - 11.5) else loads_high
    items = (
        ("target_outer_angle_deg", scenario.target_outer_angle_deg),
        ("speed_kmh", scenario.speed_kmh),
        ("friction_coefficient", scenario.friction_coefficient),
        ("axle_mass_t", load_value),
        ("duration_s", scenario.duration_s),
    )
    checks: list[RangeCheck] = []
    for name, value in items:
        label, unit = LABELS[name]
        checks.append(RangeCheck(
            field=name, label=label, value=float(value), unit=unit,
            customer_range=CUSTOMER_LIMITS[name],
            verified_range=VERIFIED_LIMITS[name],
        ))
    return tuple(checks)


# --------------------------------------------------------------- 预设工况
@dataclass(frozen=True, slots=True)
class Preset:
    key: str
    name: str
    scenario: DemoScenario
    expected_status: str
    note: str = ""


def preset_scenarios() -> tuple[Preset, ...]:
    """四个默认预设，与 PHASE J0-R1 已交付的四工况完全一致。"""
    defaults = dict(friction_coefficient=ENGINEERING_DEFAULTS["friction_coefficient"],
                    axle_mass_t=(ENGINEERING_DEFAULTS["axle_mass_t"],) * AXLE_COUNT,
                    duration_s=5.0)
    return (
        Preset("J0-01", "直行 0° / 0 km/h",
               DemoScenario(0.0, 0.0, case_id="J0-01", **defaults),
               "PASS", "全零工况，检验静平衡与三桥锁止"),
        Preset("J0-02", "左转 +2° / 5 km/h",
               DemoScenario(2.0, 5.0, case_id="J0-02", **defaults),
               "CONDITIONAL", "前通道残差 0.311°，为当前已知跟踪极限"),
        Preset("J0-03", "右转 −2° / 5 km/h",
               DemoScenario(-2.0, 5.0, case_id="J0-03", **defaults),
               "CONDITIONAL", "与 J0-02 左右镜像"),
        Preset("J0-04", "左转 +5° / 10 km/h",
               DemoScenario(5.0, 10.0, case_id="J0-04", **defaults),
               "PASS", "最大已验证转角与车速"),
    )


DEFAULT_PRESET_KEY = "J0-01"
