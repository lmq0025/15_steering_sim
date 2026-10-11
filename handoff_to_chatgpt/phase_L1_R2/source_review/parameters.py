from __future__ import annotations

from dataclasses import dataclass, field
import math


@dataclass(frozen=True)
class FluidParameters:
    density: float = 883.0
    bulk_modulus: float = 1.70e9
    kinematic_viscosity: float = 56.47e-6


@dataclass(frozen=True)
class PumpParameters:
    displacement: float = 10.0e-6 / (2.0 * math.pi)
    nominal_speed: float = 1350.0 * 2.0 * math.pi / 60.0
    volumetric_efficiency: float = 1.0
    leakage: float = 0.0


@dataclass(frozen=True)
class ValveParameters:
    discharge_coefficient: float = 0.7
    maximum_area: float = 20.0e-6
    area_gradient: float = 20.0e-6
    command_gain: float = 1.0
    deadzone: float = 0.0
    tau: float | None = None


@dataclass(frozen=True)
class ActuatorParameters:
    area_a: float
    area_b: float
    dead_volume_a: float
    dead_volume_b: float
    stroke: float
    initial_position: float = 0.0
    leakage: float = 0.0
    moving_mass: float = 1000.0
    viscous_damping: float = 0.0
    friction_force: float = 0.0
    endstop_stiffness: float = 1.0e8
    endstop_damping: float = 1.0e5

    @property
    def volume_a0(self) -> float:
        return self.dead_volume_a + self.area_a * self.stroke / 2.0

    @property
    def volume_b0(self) -> float:
        return self.dead_volume_b + self.area_b * self.stroke / 2.0


@dataclass(frozen=True)
class SupplyParameters:
    tank_pressure: float = 0.0
    relief_cracking_pressure: float = 16.0e6
    relief_conductance: float = 500.0 / 60_000.0 / 100_000.0
    path_resistance: float = 1.18e10


@dataclass(frozen=True)
class ChannelParameters:
    name: str
    pump_aliases: tuple[str, ...]
    valve_aliases: tuple[str, ...]
    # True when the SC_1 local work ports 3/4 are connected to the channel's
    # physical B/A chambers respectively.  This is topology, not calibration.
    valve_work_port_swaps: tuple[bool, ...]
    actuator_alias: str
    supply_group: str
    fluid: FluidParameters = field(default_factory=FluidParameters)
    pump: PumpParameters = field(default_factory=PumpParameters)
    valve: ValveParameters = field(default_factory=ValveParameters)
    actuator: ActuatorParameters = field(default=None)  # type: ignore[assignment]
    supply: SupplyParameters = field(default_factory=SupplyParameters)

    @property
    def pump_alias(self) -> str:
        return "+".join(self.pump_aliases)

    @property
    def valve_alias(self) -> str:
        return "+".join(self.valve_aliases)


def _areas(diamp_mm: float, rod_mm: float) -> tuple[float, float]:
    piston = math.pi * (diamp_mm * 1e-3) ** 2 / 4.0
    rod = math.pi * (rod_mm * 1e-3) ** 2 / 4.0
    return piston, piston - rod


def default_channels() -> list[ChannelParameters]:
    a1, b1 = 5000.0e-6, 3700.0e-6
    piston2, annulus2 = _areas(25.0, 12.0)
    # HJ021 has a rod at both ends (diamr1 and diamr2), hence equal annular areas.
    a2, b2 = annulus2, annulus2
    specs = [
        ("channel_front", ("pump01", "pump01_1"), ("dirvalve_6",), (True,), "actuator002", "supply_front", 0.30, a2, b2),
        ("channel_rear_1", ("pump01_2", "pump01_3"), ("dirvalve_1", "dirvalve_2"), (False, True), "actuator001", "supply_rear", 0.13, a1, b1),
        ("channel_rear_2", ("pump01_2", "pump01_3"), ("dirvalve_8", "dirvalve_9"), (False, True), "actuator001_1", "supply_rear", 0.195, a1, b1),
        ("channel_rear_3", ("pump01_2", "pump01_3"), ("dirvalve_11", "dirvalve_12"), (False, True), "actuator001_2", "supply_rear", 0.265, a1, b1),
    ]
    result: list[ChannelParameters] = []
    for name, pumps, valves, swaps, actuator, supply_group, stroke, aa, ab in specs:
        leak = 0.5 / 60_000.0 / 100_000.0 if actuator == "actuator002" else 0.0
        result.append(ChannelParameters(
            name=name,
            pump_aliases=pumps,
            valve_aliases=valves,
            valve_work_port_swaps=swaps,
            actuator_alias=actuator,
            supply_group=supply_group,
            actuator=ActuatorParameters(
                area_a=aa, area_b=ab, dead_volume_a=50e-6,
                dead_volume_b=50e-6, stroke=stroke, leakage=leak,
            ),
        ))
    return result
