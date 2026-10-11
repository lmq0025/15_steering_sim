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
class SC1OrificeParameters:
    """One source-verified HYDVORF0 branch inside an SC_1 wrapper.

    ``curve`` names the transferred FX00 fractional-area expression.  The
    characteristic pair is the Amesim method-1 definition, not an inferred
    geometric Cd*A law.
    """

    alias_suffix: str
    branch: str
    curve: str
    q_characteristic: float = 1.0 / 60_000.0  # 1 L/min -> m3/s
    dp_characteristic: float = 1.0e5  # 1 bar -> Pa
    critical_flow_number: float = 1000.0
    # S0 identifies the installed 2021.1 orif3f_ operating-range scale from
    # independent port pressure/flow measurements: 1.425 L/min/sqrt(bar).
    # The metadata qchar=1 L/min remains recorded above; this single scale is
    # explicit because the private orif3f_ body is unavailable.  S1/S2 are
    # retained as validation rather than calibration data.
    amesim_operating_range_scale: float = 1.425


@dataclass(frozen=True)
class SC1ValveParameters:
    alias: str
    spool_curve: str
    orifices: tuple[SC1OrificeParameters, ...]


def default_sc1_valves() -> dict[str, SC1ValveParameters]:
    """Return the seven active SC_1 variants transferred from 04_parameters.

    Branch semantics follow the wrapper's exposed parameter bindings:
    orifice_14=P-A, 13=P-B, 24=T-A, 23=T-B.  The three redundant wrappers
    contain only P-A and T-B, as recorded by IR V3.
    """

    primary_a = (
        SC1OrificeParameters("orifice_14", "P-A", "ramp_minus_to_zero_then_full"),
        SC1OrificeParameters("orifice_13", "P-B", "full_to_zero_on_positive"),
        SC1OrificeParameters("orifice_24", "T-A", "open_on_negative"),
        SC1OrificeParameters("orifice_23", "T-B", "open_on_positive"),
    )
    # dirvalve_6 uses a different crossed-centre table set.
    primary_c = (
        SC1OrificeParameters("orifice_14", "P-A", "full_to_zero_on_positive"),
        SC1OrificeParameters("orifice_13", "P-B", "ramp_minus_to_zero_then_full"),
        SC1OrificeParameters("orifice_24", "T-A", "ramp_minus_to_zero_then_full"),
        SC1OrificeParameters("orifice_23", "T-B", "full_to_zero_on_positive"),
    )
    redundant = (
        SC1OrificeParameters("orifice_14", "P-A", "positive_linear"),
        SC1OrificeParameters("orifice_23", "T-B", "positive_linear"),
    )
    return {
        "dirvalve_1": SC1ValveParameters("dirvalve_1", "identity_saturated", primary_a),
        "dirvalve_2": SC1ValveParameters("dirvalve_2", "identity_saturated", redundant),
        "dirvalve_6": SC1ValveParameters("dirvalve_6", "identity_saturated", primary_c),
        "dirvalve_8": SC1ValveParameters("dirvalve_8", "identity_saturated", primary_a),
        "dirvalve_9": SC1ValveParameters("dirvalve_9", "identity_saturated", redundant),
        "dirvalve_11": SC1ValveParameters("dirvalve_11", "identity_saturated", primary_a),
        "dirvalve_12": SC1ValveParameters("dirvalve_12", "identity_saturated", redundant),
    }


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
    return_path_resistance: float = 2.59e9
    valve_feed_resistance: float = 1.00e9
    auxiliary_flow: float = 0.0
    reducing_valve_margin: float = 1.10e6
    # Phase L1-Fast engineering boundary values.  Pump-outlet pressure is a
    # reported group boundary; the SC_1 high/return rails retain their actual
    # R3 spatial meaning and are not silently collapsed to the pump sensor.
    regulated_pump_outlet_pressure: float = 16.9e6
    regulated_high_rail_pressure: float = 16.9e6
    regulated_return_rail_pressure: float = 0.0


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
        # J0-R1 F2 修正：IR V3 审计（phase_L1_R2_macro_mapping_report.md）明确记录
        # “dirvalve_6 相对 actuator002 的 A/B 工作口也换位”，与后三只主阀同构；
        # 且 audit_parameters.py 记录 dirvalve_6 与 dirvalve_8 的 SUBMODEL 外端口
        # 暴露映射完全相同（ext0=P、ext1=T、ext2=B、ext3=A）。
        # 本行原为 (False,)，与上述证据相反，是 F2 的根因。
        ("channel_front", ("pump01", "pump01_1"), ("dirvalve_6",), (True,), "actuator002", "supply_front", 0.30, a2, b2),
        # SC_1 external port 3 (zero-based) is local A.  IR V3 routes the
        # primary rear valves' local A to the physical B chamber, while the
        # redundant two-orifice valves route local A to physical A.
        ("channel_rear_1", ("pump01_2", "pump01_3"), ("dirvalve_1", "dirvalve_2"), (True, False), "actuator001", "supply_rear", 0.13, a1, b1),
        ("channel_rear_2", ("pump01_2", "pump01_3"), ("dirvalve_8", "dirvalve_9"), (True, False), "actuator001_1", "supply_rear", 0.195, a1, b1),
        ("channel_rear_3", ("pump01_2", "pump01_3"), ("dirvalve_11", "dirvalve_12"), (True, False), "actuator001_2", "supply_rear", 0.265, a1, b1),
    ]
    result: list[ChannelParameters] = []
    for name, pumps, valves, swaps, actuator, supply_group, stroke, aa, ab in specs:
        # J0-R1 F2 修正：actuator002 原被单独赋予 0.5 L/min @ 100 bar 的内泄漏
        # （8.333e-11 m3/(s*Pa)），后三个通道为 0。该值没有源参数支持，且与
        #   - R03B15_AMESim_manual_execution_guide.md:60「leakage 0 L/min/bar」
        #   - R03B1_implementation_report.md:70「leakage/viscous friction 均为 0」
        #   - phase_L1_R3_physics_mapping_report.md:5「no artificial leakage」
        # 三处证据相反。它的实际作用是给原被硬置零的前缸 A 腔留一条补油通路；
        # 该通路使两腔压力被强制拉平，把前桥作动力锁死在约 ±900 N。
        # A 腔恢复真实阀口后该补丁不再需要，按源参数取 0。
        leak = 0.0
        if supply_group == "supply_front":
            # S0 identification, S1/S2 validation: pump outlet -> RV010 inlet,
            # and RV010 outlet -> tank/cooler return path respectively.
            supply = SupplyParameters(
                relief_cracking_pressure=16.0e6,
                path_resistance=6.624e9,
                return_path_resistance=2.592e9,
                valve_feed_resistance=1.00e9,
                auxiliary_flow=0.0,
                regulated_pump_outlet_pressure=18.662269954197333e6,
                regulated_high_rail_pressure=17.62180106765323e6,
                regulated_return_rail_pressure=1.1664526248902003e6,
            )
        else:
            # Rear group includes a verified 4.47 L/min macro auxiliary load:
            # q_pump - sum(pprv flow) - RV010 flow in S0, independently stable
            # in S1/S2.  It represents omitted spring-return/control branches,
            # not an artificial pressure leak.
            supply = SupplyParameters(
                relief_cracking_pressure=15.0e6,
                path_resistance=4.633e9,
                return_path_resistance=2.192e9,
                valve_feed_resistance=0.0,
                auxiliary_flow=4.47 / 60_000.0,
                regulated_pump_outlet_pressure=16.868491702365873e6,
                regulated_high_rail_pressure=2.75018809959472e6,
                regulated_return_rail_pressure=0.825038470827933e6,
            )
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
            supply=supply,
        ))
    return result
