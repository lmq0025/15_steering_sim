from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np

from .model import LumpedHydraulicSystem, SystemInputs


@dataclass(frozen=True)
class HydraulicInput:
    """SI input contract for the future steering-mechanics adapter."""

    valve_commands: tuple[float, float, float, float]
    pump_speeds_rad_s: tuple[float, float, float, float]
    external_load_forces_n: tuple[float, float, float, float]
    redundant_valve_commands: Mapping[str, float] | None = None
    prescribed_motion_by_alias: Mapping[str, tuple[float, float, float]] | None = None

    def to_system_inputs(self) -> SystemInputs:
        pump_aliases = ("pump01", "pump01_1", "pump01_2", "pump01_3")
        primary_aliases = ("dirvalve_6", "dirvalve_1", "dirvalve_8", "dirvalve_11")
        valve_map = dict(self.redundant_valve_commands or {})
        valve_map.update(zip(primary_aliases, self.valve_commands))
        return SystemInputs(
            valve_commands=self.valve_commands,
            pump_speeds=(self.pump_speeds_rad_s[0], self.pump_speeds_rad_s[2],
                         self.pump_speeds_rad_s[2], self.pump_speeds_rad_s[2]),
            load_forces=self.external_load_forces_n,
            pump_speeds_by_alias=dict(zip(pump_aliases, self.pump_speeds_rad_s)),
            valve_commands_by_alias=valve_map,
            prescribed_motion_by_alias=self.prescribed_motion_by_alias,
        )


@dataclass(frozen=True)
class HydraulicChannelOutput:
    position_m: float
    velocity_m_s: float
    hydraulic_force_n: float
    pressure_a_pa_g: float
    pressure_b_pa_g: float
    flow_a_m3_s: float
    flow_b_m3_s: float


@dataclass(frozen=True)
class HydraulicOutput:
    channels: tuple[HydraulicChannelOutput, ...]
    supply_pressures_pa_g: tuple[float, float]
    pump_capacity_insufficient: tuple[bool, bool]
    pump_capacity_margin_m3_s: tuple[float, float]


def evaluate_hydraulic(model: LumpedHydraulicSystem, t: float, state: np.ndarray,
                       inputs: HydraulicInput) -> tuple[np.ndarray, HydraulicOutput]:
    """Evaluate the hydraulic subsystem without touching a mechanical model."""
    dx, raw = model.evaluate(t, state, inputs.to_system_inputs())
    channels = tuple(HydraulicChannelOutput(
        position_m=float(item["position"]), velocity_m_s=float(item["velocity"]),
        hydraulic_force_n=float(item["hydraulic_force"]),
        pressure_a_pa_g=float(item["pA"]), pressure_b_pa_g=float(item["pB"]),
        flow_a_m3_s=float(item["QA"]), flow_b_m3_s=float(item["QB"]),
    ) for item in raw)
    return dx, HydraulicOutput(
        channels=channels,
        supply_pressures_pa_g=(float(raw[0]["pump_outlet_pressure"]),
                               float(raw[1]["pump_outlet_pressure"])),
        pump_capacity_insufficient=(bool(raw[0]["pump_capacity_insufficient"]),
                                    bool(raw[1]["pump_capacity_insufficient"])),
        pump_capacity_margin_m3_s=(float(raw[0]["pump_capacity_margin"]),
                                   float(raw[1]["pump_capacity_margin"])),
    )
