"""Typed PHASE J0 configuration with strict validation.

Every quantity that is an engineering assumption rather than a measured value
is tagged in ``configs/j0/j0_config.json`` and carried through to the report so
that no ASSUMED value can silently become a confirmed fact.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

CHANNEL_ORDER = ("channel_front", "channel_rear_1", "channel_rear_2",
                 "channel_rear_3")
DOF_BY_CHANNEL = {"channel_front": "q_front", "channel_rear_1": "q4",
                  "channel_rear_2": "q5", "channel_rear_3": "q6"}


@dataclass(frozen=True, slots=True)
class ChannelControlConfig:
    index: int
    channel: str
    valve_alias: str
    actuator_alias: str
    dof: str
    cylinder_group: str
    kp: float
    ki: float
    kd: float
    command_limit: float
    command_min: float
    command_max: float
    neutral_command: float
    command_polarity: float
    mapping_status: str
    authority_status: str
    notes: str

    def __post_init__(self) -> None:
        if self.channel not in CHANNEL_ORDER:
            raise ValueError(f"unknown channel {self.channel!r}")
        if DOF_BY_CHANNEL[self.channel] != self.dof:
            raise ValueError(
                f"{self.channel}: J0 fixed mapping requires dof "
                f"{DOF_BY_CHANNEL[self.channel]!r}, got {self.dof!r}")
        if CHANNEL_ORDER.index(self.channel) != self.index:
            raise ValueError(f"{self.channel}: index must be {CHANNEL_ORDER.index(self.channel)}")
        if self.command_limit <= 0.0:
            raise ValueError(f"{self.channel}: command_limit must be positive")
        if not self.command_min <= self.neutral_command <= self.command_max:
            raise ValueError(f"{self.channel}: neutral_command outside command window")
        if self.command_min >= self.command_max:
            raise ValueError(f"{self.channel}: empty command window")
        # ``command_limit`` clamps the PID output; ``command_from_pid`` then maps
        # it through ``neutral_command`` and clamps to the hardware command
        # window, so the two limits are independent and both are enforced.
        if self.command_polarity not in (1.0, -1.0):
            raise ValueError(f"{self.channel}: command_polarity must be +1 or -1")

    def command_from_pid(self, pid_output: float) -> float:
        """Map a PID output (positive = drive x positive) onto the valve command."""
        return float(min(max(
            self.neutral_command + self.command_polarity * pid_output,
            self.command_min), self.command_max))


@dataclass(frozen=True, slots=True)
class J0CaseConfig:
    id: str
    target_outer_angle_deg: float
    speed_kmh: float
    duration_s: float

    @property
    def speed_m_s(self) -> float:
        return self.speed_kmh / 3.6


@dataclass(frozen=True, slots=True)
class J0Config:
    path: Path
    raw: dict[str, Any]
    dt_hydraulic_s: float
    dt_control_s: float
    channels: tuple[ChannelControlConfig, ...]
    cases: tuple[J0CaseConfig, ...]
    control: dict[str, Any]
    mapping: dict[str, Any]
    load: dict[str, Any]
    hydraulic: dict[str, Any]
    acceptance: dict[str, Any]
    output: dict[str, Any]

    @property
    def substeps_per_control(self) -> int:
        ratio = self.dt_control_s / self.dt_hydraulic_s
        rounded = round(ratio)
        if abs(ratio - rounded) > 1.0e-9 or rounded < 1:
            raise ValueError("dt_control_s must be an integer multiple of dt_hydraulic_s")
        return int(rounded)

    @property
    def sample_stride(self) -> int:
        return max(1, int(self.output["sample_stride_hydraulic_steps"]))

    def channel(self, name: str) -> ChannelControlConfig:
        for item in self.channels:
            if item.channel == name:
                return item
        raise KeyError(name)


def load_j0_config(path: str | Path) -> J0Config:
    source = Path(path)
    raw = json.loads(source.read_text(encoding="utf-8"))
    if raw.get("schema_version") != "J0.1":
        raise ValueError(f"unsupported J0 configuration schema in {source}")

    hydraulic = raw["hydraulic"]
    dt_h = float(hydraulic["dt_hydraulic_s"])
    dt_c = float(raw["control"]["dt_control_s"])
    if dt_h <= 0.0 or dt_c <= 0.0:
        raise ValueError("time steps must be positive")
    if dt_c < dt_h:
        raise ValueError("the control period cannot be shorter than the hydraulic step")

    channels = tuple(ChannelControlConfig(
        index=int(item["index"]),
        channel=str(item["channel"]),
        valve_alias=str(item["valve_alias"]),
        actuator_alias=str(item["actuator_alias"]),
        dof=str(item["dof"]),
        cylinder_group=str(item["cylinder_group"]),
        kp=float(item["kp"]),
        ki=float(item["ki"]),
        kd=float(item["kd"]),
        command_limit=float(item["command_limit"]),
        command_min=float(item["command_min"]),
        command_max=float(item["command_max"]),
        neutral_command=float(item["neutral_command"]),
        command_polarity=float(item["command_polarity"]),
        mapping_status=str(item["mapping_status"]),
        authority_status=str(item["authority_status"]),
        notes=str(item["notes"]),
    ) for item in raw["control"]["channels"])
    if tuple(item.channel for item in channels) != CHANNEL_ORDER:
        raise ValueError("control channels must be listed in the fixed J0 order")

    cases = tuple(J0CaseConfig(
        id=str(item["id"]),
        target_outer_angle_deg=float(item["target_outer_angle_deg"]),
        speed_kmh=float(item["speed_kmh"]),
        duration_s=float(item["duration_s"]),
    ) for item in raw["cases"])
    if not cases:
        raise ValueError("at least one J0 case is required")

    return J0Config(
        path=source, raw=raw, dt_hydraulic_s=dt_h, dt_control_s=dt_c,
        channels=channels, cases=cases, control=raw["control"],
        mapping=raw["mapping"], load=raw["load"], hydraulic=hydraulic,
        acceptance=raw["acceptance"], output=raw["output"],
    )
