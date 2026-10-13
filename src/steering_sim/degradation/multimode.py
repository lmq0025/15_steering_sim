"""D3 component-instance multi-mode degradation state and physical mapping."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Mapping

from steering_sim.hydraulics_engineering import (
    CylinderDegradationParameters, EngineeringHydraulicParameters,
    PumpDegradationParameters, ValveDegradationParameters,
    with_component_degradation)
from steering_sim.j0_coupling.config import CHANNEL_ORDER

from .damage import ComponentDamageState, DegradationState

PUMP_IDS = ("front", "rear")
MODE_NAMES = {
    "pump": ("leakage_wear", "mechanical_loss"),
    "valve": ("leakage_wear", "response_lag"),
    "cylinder": ("leakage_wear", "friction_growth"),
}


def mode_key(kind: str, component_id: str, mode: str) -> str:
    return f"{kind}:{component_id}:{mode}"


@dataclass(frozen=True, slots=True)
class D3Config:
    raw: Mapping[str, Any]
    model_version: str
    assumption_tag: str

    def mode(self, kind: str, mode: str) -> Mapping[str, Any]:
        return self.raw["modes"][kind][mode]


def load_d3_config(path: str | Path) -> D3Config:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if raw.get("schema_version") != "D3.0":
        raise ValueError(f"unsupported D3 config: {raw.get('schema_version')!r}")
    if raw.get("assumption_tag") != "ENGINEERING_DESIGN_ASSUMPTION":
        raise ValueError("unvalidated D3 values must carry ENGINEERING_DESIGN_ASSUMPTION")
    if raw.get("calibration_status") != "PENDING_CLIENT_CALIBRATION":
        raise ValueError("D3 values must be marked PENDING_CLIENT_CALIBRATION")
    for kind, names in MODE_NAMES.items():
        for name in names:
            if name not in raw.get("modes", {}).get(kind, {}):
                raise ValueError(f"missing D3 mode {kind}.{name}")
    return D3Config(raw=raw, model_version=str(raw["model_version"]),
                    assumption_tag=str(raw["assumption_tag"]))


@dataclass(frozen=True, slots=True)
class MultiModeDegradationState:
    """Flat immutable state: every component instance owns two independent modes."""

    modes: Mapping[str, ComponentDamageState] = field(default_factory=dict)

    @staticmethod
    def healthy(channels: tuple[str, ...] = CHANNEL_ORDER
                ) -> "MultiModeDegradationState":
        values: dict[str, ComponentDamageState] = {}
        for component_id in PUMP_IDS:
            for mode in MODE_NAMES["pump"]:
                values[mode_key("pump", component_id, mode)] = ComponentDamageState()
        for kind in ("valve", "cylinder"):
            for component_id in channels:
                for mode in MODE_NAMES[kind]:
                    values[mode_key(kind, component_id, mode)] = ComponentDamageState()
        return MultiModeDegradationState(values)

    @staticmethod
    def from_d1(state: DegradationState) -> "MultiModeDegradationState":
        result = dict(MultiModeDegradationState.healthy(tuple(state.valves)).modes)
        for kind, values in (("pump", state.pumps), ("valve", state.valves),
                             ("cylinder", state.cylinders)):
            for component_id, value in values.items():
                result[mode_key(kind, component_id, "leakage_wear")] = value
        return MultiModeDegradationState(result)

    def to_d1(self) -> DegradationState:
        return DegradationState(
            pumps={name: self.modes[mode_key("pump", name, "leakage_wear")]
                   for name in PUMP_IDS},
            valves={name: self.modes[mode_key("valve", name, "leakage_wear")]
                    for name in CHANNEL_ORDER},
            cylinders={name: self.modes[mode_key("cylinder", name, "leakage_wear")]
                       for name in CHANNEL_ORDER})

    @property
    def max_damage(self) -> float:
        return max((value.damage for value in self.modes.values()), default=0.0)

    def with_mode(self, key: str, value: ComponentDamageState
                  ) -> "MultiModeDegradationState":
        if key not in self.modes:
            raise KeyError(key)
        updated = dict(self.modes)
        updated[key] = value
        return MultiModeDegradationState(updated)

    def flat_damage(self) -> dict[str, float]:
        return {key.replace(":", "_"): value.damage
                for key, value in self.modes.items()}


def parameters_from_multimode(
        healthy: EngineeringHydraulicParameters,
        state: MultiModeDegradationState, config: D3Config,
        ) -> EngineeringHydraulicParameters:
    """Map six modes into the existing engineering model without mutating healthy."""
    pump_leak = config.mode("pump", "leakage_wear")
    pump_mech = config.mode("pump", "mechanical_loss")
    valve_leak = config.mode("valve", "leakage_wear")
    valve_lag = config.mode("valve", "response_lag")
    cylinder_leak = config.mode("cylinder", "leakage_wear")
    cylinder_friction = config.mode("cylinder", "friction_growth")

    pumps: dict[str, PumpDegradationParameters] = {}
    for name in PUMP_IDS:
        d_leak = state.modes[mode_key("pump", name, "leakage_wear")].damage
        d_mech = state.modes[mode_key("pump", name, "mechanical_loss")].damage
        rated_power = ((healthy.supplies[name].ideal_flow_m3_s
                        * healthy.supplies[name].relief_pressure_pa
                        * float(pump_mech["healthy_power_margin_ratio"]))
                       if d_mech > 0.0 else 0.0)
        pumps[name] = PumpDegradationParameters(
            volumetric_efficiency=1.0,
            internal_leakage_m3_s_per_pa=(
                float(pump_leak["maximum_internal_leakage_m3_s_per_pa"]) * d_leak),
            mechanical_efficiency=max(
                float(pump_mech["minimum_mechanical_efficiency"]),
                1.0 - float(pump_mech["efficiency_loss_at_maximum_damage"]) * d_mech),
            rated_drive_power_w=rated_power)

    valves = {name: ValveDegradationParameters(
        internal_leakage_m3_s_per_pa=(
            float(valve_leak["maximum_internal_leakage_m3_s_per_pa"])
            * state.modes[mode_key("valve", name, "leakage_wear")].damage),
        flow_coefficient_scale=1.0,
        lag_scale=(1.0 + (float(valve_lag["maximum_lag_scale"]) - 1.0)
                   * state.modes[mode_key("valve", name, "response_lag")].damage))
        for name in CHANNEL_ORDER}
    cylinders = {name: CylinderDegradationParameters(
        internal_leakage_m3_s_per_pa=(
            float(cylinder_leak["maximum_internal_leakage_m3_s_per_pa"])
            * state.modes[mode_key("cylinder", name, "leakage_wear")].damage),
        friction_scale=(1.0 + (float(cylinder_friction["maximum_friction_scale"]) - 1.0)
                        * state.modes[mode_key("cylinder", name, "friction_growth")].damage))
        for name in CHANNEL_ORDER}
    return with_component_degradation(healthy, pumps=pumps, valves=valves,
                                      cylinders=cylinders)


def component_mode_rows(state: MultiModeDegradationState, config: D3Config,
                        parameters: EngineeringHydraulicParameters
                        ) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, value in state.modes.items():
        kind, component_id, mode = key.split(":")
        mode_config = config.mode(kind, mode)
        row = {
            "component_type": kind, "component_id": component_id,
            "degradation_mode": mode, "damage": value.damage,
            "equivalent_exposure": value.exposure,
            "damage_unit": "-", "exposure_unit": mode_config["exposure_unit"],
            "rate": mode_config["rate"],
            "failure_damage": mode_config["failure_damage"],
            "mechanism": mode_config["mechanism"],
            "source": config.assumption_tag,
            "calibration_status": "PENDING_CLIENT_CALIBRATION",
            "model_version": config.model_version,
        }
        wear = (parameters.degradation.pump(component_id) if kind == "pump" else
                parameters.degradation.valve(component_id) if kind == "valve" else
                parameters.degradation.cylinder(component_id))
        if kind == "pump" and mode == "leakage_wear":
            row.update(parameter="internal_leakage_m3_s_per_pa",
                       parameter_value=wear.internal_leakage_m3_s_per_pa,
                       parameter_unit="m3/s/Pa")
        elif kind == "pump":
            row.update(parameter="mechanical_efficiency",
                       parameter_value=wear.mechanical_efficiency,
                       parameter_unit="-")
        elif kind == "valve" and mode == "leakage_wear":
            row.update(parameter="internal_leakage_m3_s_per_pa",
                       parameter_value=wear.internal_leakage_m3_s_per_pa,
                       parameter_unit="m3/s/Pa")
        elif kind == "valve":
            row.update(parameter="lag_scale", parameter_value=wear.lag_scale,
                       parameter_unit="-")
        elif mode == "leakage_wear":
            row.update(parameter="internal_leakage_m3_s_per_pa",
                       parameter_value=wear.internal_leakage_m3_s_per_pa,
                       parameter_unit="m3/s/Pa")
        else:
            row.update(parameter="friction_scale",
                       parameter_value=wear.friction_scale, parameter_unit="-")
        rows.append(row)
    return rows
