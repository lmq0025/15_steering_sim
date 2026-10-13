"""顺序保持的快速任务谱特征提取与 D1 退化预测。"""
from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Any, Mapping

from steering_sim.hydraulics_engineering import (
    CylinderDegradationParameters, EngineeringHydraulicParameters,
    EngineeringHydraulicSystem, PumpDegradationParameters, ValveDegradationParameters,
    with_component_degradation)
from steering_sim.j0_coupling.config import CHANNEL_ORDER, DOF_BY_CHANNEL, J0CaseConfig
from steering_sim.j0_coupling.road_load import road_load

from .damage import (ComponentDamageState, DegradationModelConfig,
                     DegradationState)
from .spectrum import TaskSpectrum


@dataclass(frozen=True, slots=True)
class D1Prediction:
    final_state: DegradationState
    final_parameters: EngineeringHydraulicParameters
    segment_records: tuple[dict[str, Any], ...]
    curve_records: tuple[dict[str, Any], ...]
    risks: tuple[dict[str, Any], ...]
    runtime_s: float
    cache_hits: int
    cache_misses: int


def parameters_from_damage(healthy: EngineeringHydraulicParameters,
                           state: DegradationState,
                           config: DegradationModelConfig
                           ) -> EngineeringHydraulicParameters:
    """把损伤状态映射成正式工程液压参数副本，不修改健康对象。"""
    pump_cfg = config.component("pump")
    valve_cfg = config.component("valve")
    cylinder_cfg = config.component("cylinder")
    pumps = {name: PumpDegradationParameters(
        # 内泄漏是 D1 的唯一泵流量损失作用量；效率在结果表中由它推导。
        volumetric_efficiency=1.0,
        internal_leakage_m3_s_per_pa=(
            float(pump_cfg["maximum_internal_leakage_m3_s_per_pa"])
            * item.damage)) for name, item in state.pumps.items()}
    valves = {name: ValveDegradationParameters(
        internal_leakage_m3_s_per_pa=(
            float(valve_cfg["maximum_internal_leakage_m3_s_per_pa"])
            * item.damage),
        flow_coefficient_scale=1.0,
        lag_scale=1.0) for name, item in state.valves.items()}
    cylinders = {name: CylinderDegradationParameters(
        internal_leakage_m3_s_per_pa=(
            float(cylinder_cfg["maximum_internal_leakage_m3_s_per_pa"])
            * item.damage),
        friction_scale=1.0) for name, item in state.cylinders.items()}
    return with_component_degradation(healthy, pumps=pumps, valves=valves,
                                      cylinders=cylinders)


def component_parameter_rows(parameters: EngineeringHydraulicParameters,
                             state: DegradationState,
                             config: DegradationModelConfig
                             ) -> list[dict[str, Any]]:
    """部件状态/最终参数的长表，含单位、来源和待标定标记。"""
    rows: list[dict[str, Any]] = []
    pump_cfg = config.component("pump")
    reference_pressure = float(pump_cfg["reference_pressure_pa"])
    for name, item in state.pumps.items():
        wear = parameters.degradation.pump(name)
        ideal = parameters.supplies[name].ideal_flow_m3_s
        effective_eta = max(float(pump_cfg["minimum_volumetric_efficiency"]),
                            1.0 - wear.internal_leakage_m3_s_per_pa
                            * reference_pressure / ideal)
        rows.extend((
            {"component_type": "gear_pump", "component_id": name,
             "parameter": "damage", "value": item.damage, "unit": "-"},
            {"component_type": "gear_pump", "component_id": name,
             "parameter": "volumetric_efficiency_at_reference", "value": effective_eta,
             "unit": "-"},
            {"component_type": "gear_pump", "component_id": name,
             "parameter": "internal_leakage_m3_s_per_pa",
             "value": wear.internal_leakage_m3_s_per_pa, "unit": "m3/s/Pa"}))
    for kind, states, getter in (
            ("steering_valve", state.valves, parameters.degradation.valve),
            ("hydraulic_cylinder", state.cylinders, parameters.degradation.cylinder)):
        for name, item in states.items():
            wear = getter(name)
            rows.extend((
                {"component_type": kind, "component_id": name,
                 "parameter": "damage", "value": item.damage, "unit": "-"},
                {"component_type": kind, "component_id": name,
                 "parameter": "internal_leakage_m3_s_per_pa",
                 "value": wear.internal_leakage_m3_s_per_pa, "unit": "m3/s/Pa"}))
    for row in rows:
        row.update({"model_version": config.model_version,
                    "source": config.assumption_tag,
                    "calibration_status": "PENDING_CLIENT_CALIBRATION"})
    return rows


class D1Predictor:
    """用正式机构/道路负载计算特征，用等效暴露快速累计 30 天损伤。"""

    def __init__(self, runner, config: DegradationModelConfig) -> None:
        if runner.engineering_parameters is None:
            raise ValueError("D1 只支持正式 ENGINEERING_HYDRAULIC_V1")
        self.runner = runner
        self.healthy = runner.engineering_parameters
        self.config = config
        self._cache: dict[tuple[Any, ...], dict[str, Any]] = {}
        self.cache_hits = 0
        self.cache_misses = 0

    def _features(self, previous_angle: float, segment, state: DegradationState,
                  movement_allowed: bool) -> dict[str, Any]:
        key = (round(previous_angle, 6), round(segment.target_outer_angle_deg, 6),
               round(segment.speed_kmh, 6), round(segment.friction_coefficient, 6),
               tuple(round(value, 6) for value in segment.axle_mass_t),
               segment.pump_running, round(segment.contamination_severity, 6),
               # 明显退化后刷新；当前等效特征不依赖磨损，但键保留该约束。
               int(state.max_damage / float(self.config.raw["refresh_damage_interval"])))
        if key in self._cache:
            self.cache_hits += 1
            return dict(self._cache[key])
        self.cache_misses += 1
        case = J0CaseConfig(id=segment.segment_id,
                            target_outer_angle_deg=segment.target_outer_angle_deg,
                            speed_kmh=segment.speed_kmh,
                            duration_s=segment.segment_duration_s)
        previous = self.runner.target(J0CaseConfig(
            id="previous", target_outer_angle_deg=previous_angle,
            speed_kmh=segment.speed_kmh, duration_s=1.0))
        target = self.runner.target(case)
        load = road_load(
            self.runner.geometry, target["q_ref"], speed_kmh=segment.speed_kmh,
            friction_coefficient=segment.friction_coefficient,
            axle_mass_t=segment.axle_mass_t,
            curvature_1pm=target["curvature_1pm"],
            target_curvature_1pm=target["curvature_1pm"],
            singular_threshold_m_per_rad=self.runner.singular_threshold,
            use_actual_curvature=True)
        strokes = {name: abs(float(target["x_ref"][name])
                             - float(previous["x_ref"][name]))
                   if movement_allowed else 0.0 for name in CHANNEL_ORDER}
        cycles = {name: 1.0 if distance > 1.0e-9 else 0.0
                  for name, distance in strokes.items()}
        transition_time_s = (min(segment.segment_duration_s,
                                 max(self.runner.reference_minimum_time_s,
                                     abs(segment.target_outer_angle_deg - previous_angle)
                                     / max(self.runner.reference_rate_deg_per_s, 1.0e-9)))
                             if movement_allowed and any(cycles.values()) else 0.0)
        pressures: dict[str, float] = {}
        signed_forces: dict[str, float] = {}
        load_levels: dict[str, float] = {}
        volumes: dict[str, float] = {}
        for name in CHANNEL_ORDER:
            dof = DOF_BY_CHANNEL[name]
            force = abs(float(load.hydraulic_load_force_n[dof]))
            signed_forces[name] = float(load.hydraulic_load_force_n[dof])
            channel = self.healthy.channel(name)
            area = 0.5 * (channel.cylinder.area_a_m2 + channel.cylinder.area_b_m2)
            pressures[name] = min(
                self.healthy.supplies[channel.supply].relief_pressure_pa,
                force / max(area, 1.0e-12))
            load_levels[name] = min(2.0, force / max(
                area * float(self.config.raw["cylinder"]["reference_pressure_pa"]),
                1.0e-12))
            volumes[name] = area * strokes[name]
        # D2 载荷反馈：按当前退化状态构造同一正式供油方程，估算每条轨在本次
        # 转向动作中的需求流量、负载压力、可用泵流量和需求比。这样损伤刷新不仅
        # 改缓存键，也会真实改变下一段液压供给特征。
        current_parameters = parameters_from_damage(self.healthy, state, self.config)
        hydraulic = EngineeringHydraulicSystem(current_parameters)
        rail_features: dict[str, dict[str, float]] = {}
        for supply in current_parameters.supply_names:
            channel_names = [item.name for item in current_parameters.channels
                             if item.supply == supply]
            demand_flow = (sum(volumes[name] for name in channel_names)
                           / transition_time_s if transition_time_s > 0.0 else 0.0)
            load_pressure = max((pressures[name] for name in channel_names), default=0.0)
            pump = current_parameters.supplies[supply]
            equilibrium = hydraulic._supply_equilibrium_pressure(supply)
            minimum_active = (float(self.config.raw["pump"][
                "minimum_active_pressure_fraction"]) * pump.relief_pressure_pa)
            operating_pressure = min(
                equilibrium,
                current_parameters.tank_pressure_pa
                + max(load_pressure, minimum_active if demand_flow > 0.0 else 0.0))
            available_flow = hydraulic.available_pump_flow(supply, operating_pressure)
            valve_leak = sum(
                current_parameters.degradation.valve(name)
                .internal_leakage_m3_s_per_pa
                * max(0.0, operating_pressure - current_parameters.tank_pressure_pa)
                for name in channel_names)
            total_demand = demand_flow + valve_leak
            rail_features[supply] = {
                "transition_time_s": transition_time_s,
                "demand_flow_m3_s": total_demand,
                "motion_flow_m3_s": demand_flow,
                "valve_leakage_flow_m3_s": valve_leak,
                "load_pressure_pa": load_pressure,
                "operating_pressure_pa": operating_pressure,
                "equilibrium_pressure_pa": equilibrium,
                "available_pump_flow_m3_s": available_flow,
                "pump_demand_ratio": (total_demand / available_flow
                                      if available_flow > 0.0 else math.inf),
                "hydraulic_power_w": operating_pressure * total_demand,
            }
        result = {
            "strokes_m": strokes, "cycles": cycles, "throughput_m3": volumes,
            "pressure_diff_pa": pressures, "load_level": load_levels,
            "signed_load_force_n": signed_forces,
            "adhesion_utilization": float(load.adhesion_utilization),
            "load_flags": tuple(load.flags),
            "target_x_ref": dict(target["x_ref"]),
            "transition_time_s": transition_time_s,
            "rail_features": rail_features,
        }
        self._cache[key] = dict(result)
        return result

    @staticmethod
    def _advance_map(states: Mapping[str, ComponentDamageState], name: str,
                     *, rate: float, exposure: float, alpha: float,
                     maximum: float) -> tuple[dict[str, ComponentDamageState], float]:
        updated = dict(states)
        updated[name], increment = states[name].advanced(
            rate=rate, equivalent_exposure=exposure,
            state_factor_alpha=alpha, maximum_damage=maximum)
        return updated, increment

    def predict(self, spectrum: TaskSpectrum,
                initial_state: DegradationState | None = None,
                *, initial_outer_angle_deg: float = 0.0) -> D1Prediction:
        started = time.perf_counter()
        state = initial_state or DegradationState.healthy(CHANNEL_ORDER)
        records: list[dict[str, Any]] = []
        risks: list[dict[str, Any]] = []
        elapsed = 0.0
        previous_angle = float(initial_outer_angle_deg)
        curve = [self._curve_row(0.0, state)]
        pump_cfg = self.config.component("pump")
        valve_cfg = self.config.component("valve")
        cylinder_cfg = self.config.component("cylinder")

        for segment, repeat_index in spectrum.expanded():
            angle_changed = abs(segment.target_outer_angle_deg - previous_angle) > 1.0e-12
            movement_allowed = bool(segment.pump_running or not angle_changed)
            if angle_changed and not segment.pump_running:
                risks.append({"segment_id": segment.segment_id,
                              "code": "STEERING_COMMAND_WITH_PUMP_OFF",
                              "message": "泵停机时目标角发生变化；未计入虚构的阀循环或缸滑动。"})
            features = self._features(previous_angle, segment, state, movement_allowed)
            if features["adhesion_utilization"] > 1.0:
                risks.append({"segment_id": segment.segment_id,
                              "code": "ADHESION_INFEASIBLE",
                              "message": (f"目标轨迹附着利用率 "
                                          f"{features['adhesion_utilization']:.3f} > 1；"
                                          "保留载荷趋势但不宣称车辆可实现该轨迹。")})
            contamination = segment.contamination_severity
            temperature_factor = max(0.5, min(2.0, math.exp(
                float(pump_cfg["temperature_coefficient_per_c"])
                * (segment.oil_temperature_c
                   - float(pump_cfg["reference_temperature_c"])))))
            increments: dict[str, float] = {}
            pump_exposures: dict[str, float] = {}
            valve_exposures: dict[str, float] = {}
            cylinder_exposures: dict[str, float] = {}

            pumps = dict(state.pumps)
            for supply in ("front", "rear"):
                pump = self.healthy.supplies[supply]
                rail = features["rail_features"][supply]
                equilibrium_dp = max(
                    0.0, float(rail["equilibrium_pressure_pa"])
                    - self.healthy.tank_pressure_pa)
                active_dp = max(0.0, float(rail["operating_pressure_pa"])
                                - self.healthy.tank_pressure_pa)
                speed_ratio = (pump.nominal_speed_rad_s
                               / float(pump_cfg["reference_speed_rad_s"]))
                exposure = 0.0
                if segment.pump_running:
                    active_s = min(segment.segment_duration_s,
                                   float(rail["transition_time_s"]))
                    # Running-time wear is the baseline for the whole segment.
                    # Steering adds a load surcharge during the actual motion;
                    # it must not replace baseline hours (which could otherwise
                    # make a loaded segment look gentler than straight running).
                    idle = (segment.segment_duration_s / 3600.0
                            * float(pump_cfg["idle_exposure_weight"])
                            * (equilibrium_dp / float(pump_cfg["reference_pressure_pa"]))
                            ** float(pump_cfg["pressure_exponent"]))
                    demand_ratio = min(5.0, max(
                        0.0, float(rail["pump_demand_ratio"])))
                    active = (active_s / 3600.0
                              * (active_dp / float(pump_cfg["reference_pressure_pa"]))
                              ** float(pump_cfg["pressure_exponent"])
                              * (1.0 + float(pump_cfg["demand_flow_weight"])
                                 * demand_ratio))
                    exposure = ((idle + active) * speed_ratio * contamination
                                * temperature_factor)
                pumps, inc = self._advance_map(
                    pumps, supply, rate=float(pump_cfg["rate_per_equivalent_hour"]),
                    exposure=exposure,
                    alpha=float(pump_cfg["state_factor_alpha"]),
                    maximum=float(pump_cfg["maximum_damage"]))
                increments[f"pump_{supply}"] = inc
                pump_exposures[supply] = exposure

            valves = dict(state.valves)
            cylinders = dict(state.cylinders)
            for name in CHANNEL_ORDER:
                supply = self.healthy.channel(name).supply
                supply_dp = max(0.0,
                    self.runner.hydraulic._supply_equilibrium_pressure(supply)
                    - self.healthy.tank_pressure_pa)
                pressure = max(float(features["pressure_diff_pa"][name]),
                               0.25 * supply_dp if features["cycles"][name] else 0.0)
                valve_exposure = contamination * (
                    float(features["throughput_m3"][name])
                    / float(valve_cfg["reference_throughput_m3"])
                    * (pressure / float(valve_cfg["reference_pressure_pa"]))
                    ** float(valve_cfg["pressure_exponent"])
                    + float(features["cycles"][name])
                    * float(valve_cfg["cycle_equivalent_exposure"]))
                valves, inc = self._advance_map(
                    valves, name, rate=float(valve_cfg["rate_per_equivalent_exposure"]),
                    exposure=valve_exposure,
                    alpha=float(valve_cfg["state_factor_alpha"]),
                    maximum=float(valve_cfg["maximum_damage"]))
                increments[f"valve_{name}"] = inc
                valve_exposures[name] = valve_exposure

                cylinder_exposure = contamination * (
                    float(features["strokes_m"][name])
                    / float(cylinder_cfg["reference_sliding_distance_m"])
                    * (float(features["pressure_diff_pa"][name])
                       / float(cylinder_cfg["reference_pressure_pa"]))
                    ** float(cylinder_cfg["pressure_exponent"])
                    * max(float(cylinder_cfg["minimum_load_factor"]),
                          float(features["load_level"][name])))
                cylinders, inc = self._advance_map(
                    cylinders, name,
                    rate=float(cylinder_cfg["rate_per_equivalent_exposure"]),
                    exposure=cylinder_exposure,
                    alpha=float(cylinder_cfg["state_factor_alpha"]),
                    maximum=float(cylinder_cfg["maximum_damage"]))
                increments[f"cylinder_{name}"] = inc
                cylinder_exposures[name] = cylinder_exposure

            state = DegradationState(pumps=pumps, valves=valves,
                                     cylinders=cylinders)
            elapsed += segment.segment_duration_s
            record: dict[str, Any] = {
                "segment_id": segment.segment_id, "repeat_index": repeat_index,
                "elapsed_s": elapsed, "elapsed_day": elapsed / 86400.0,
                "speed_kmh": segment.speed_kmh,
                "target_outer_angle_deg": segment.target_outer_angle_deg,
                "previous_outer_angle_deg": previous_angle,
                "segment_duration_s": segment.segment_duration_s,
                "pump_running": segment.pump_running,
                "contamination_severity": contamination,
                "adhesion_utilization": features["adhesion_utilization"],
                "load_flags": "|".join(features["load_flags"]),
            }
            for name in CHANNEL_ORDER:
                record[f"{name}_pressure_diff_pa"] = features["pressure_diff_pa"][name]
                record[f"{name}_throughput_m3"] = features["throughput_m3"][name]
                record[f"{name}_valve_cycles"] = features["cycles"][name]
                record[f"{name}_sliding_distance_m"] = features["strokes_m"][name]
                record[f"{name}_signed_load_force_n"] = features["signed_load_force_n"][name]
                record[f"equivalent_exposure_valve_{name}"] = valve_exposures[name]
                record[f"equivalent_exposure_cylinder_{name}"] = cylinder_exposures[name]
            for supply in ("front", "rear"):
                for key, value in features["rail_features"][supply].items():
                    record[f"pump_{supply}_{key}"] = value
                record[f"equivalent_exposure_pump_{supply}"] = pump_exposures[supply]
            record.update({f"damage_increment_{key}": value
                           for key, value in increments.items()})
            record.update(self._flat_damage(state))
            records.append(record)
            curve.append(self._curve_row(elapsed / 86400.0, state))
            if movement_allowed:
                previous_angle = segment.target_outer_angle_deg

        final_parameters = parameters_from_damage(self.healthy, state, self.config)
        return D1Prediction(
            final_state=state, final_parameters=final_parameters,
            segment_records=tuple(records), curve_records=tuple(curve),
            risks=tuple(risks), runtime_s=time.perf_counter() - started,
            cache_hits=self.cache_hits, cache_misses=self.cache_misses)

    @staticmethod
    def _flat_damage(state: DegradationState) -> dict[str, float]:
        result = {f"cumulative_damage_pump_{name}": item.damage
                  for name, item in state.pumps.items()}
        result.update({f"cumulative_damage_valve_{name}": item.damage
                       for name, item in state.valves.items()})
        result.update({f"cumulative_damage_cylinder_{name}": item.damage
                       for name, item in state.cylinders.items()})
        return result

    @classmethod
    def _curve_row(cls, day: float, state: DegradationState) -> dict[str, float]:
        return {"day": day, **cls._flat_damage(state)}


def state_from_record(record: Mapping[str, Any]) -> DegradationState:
    """Rebuild a component state from a D1 segment/curve record.

    This is the read-only bridge used by D2 checkpoints.  It deliberately
    reconstructs only damage; D1 exposure bookkeeping remains in the segment
    table and is never inferred from damage.
    """
    pumps = {
        name: ComponentDamageState(
            damage=float(record[f"cumulative_damage_pump_{name}"]))
        for name in ("front", "rear")
    }
    valves = {
        name: ComponentDamageState(
            damage=float(record[f"cumulative_damage_valve_{name}"]))
        for name in CHANNEL_ORDER
    }
    cylinders = {
        name: ComponentDamageState(
            damage=float(record[f"cumulative_damage_cylinder_{name}"]))
        for name in CHANNEL_ORDER
    }
    return DegradationState(pumps=pumps, valves=valves, cylinders=cylinders)


def checkpoint_states(prediction: D1Prediction,
                      days: tuple[float, ...] = (0.0, 10.0, 20.0, 30.0)
                      ) -> dict[float, DegradationState]:
    """Return the first inherited D1 state at or after each requested day."""
    result: dict[float, DegradationState] = {}
    healthy = DegradationState.healthy(CHANNEL_ORDER)
    records = prediction.segment_records
    for requested in days:
        if requested <= 0.0:
            result[requested] = healthy
            continue
        match = next((row for row in records
                      if float(row["elapsed_day"]) >= requested - 1.0e-12), None)
        if match is None:
            raise ValueError(
                f"D1 prediction ends before requested checkpoint day {requested:g}")
        result[requested] = state_from_record(match)
    return result
