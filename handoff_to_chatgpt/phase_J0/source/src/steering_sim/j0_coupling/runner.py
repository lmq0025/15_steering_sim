"""PHASE J0 multi-rate closed-loop runner.

Single-ownership chain, evaluated once per RK4 stage:

    hydraulic state (pA, pB, x, v) x4
      -> invert the representative strokes to q_front, q4, q5, q6
      -> rigid closed chain: 12 wheel angles, 7 geometric strokes, residuals
      -> road load on the ACTUAL q: Q_road per group
      -> virtual work: F_load = Q_road / (dx/dq)
      -> L1-Fast RHS: pdot, xdot, vdot

Only the 16 L1-Fast states are integrated.  The mechanism coordinates are
algebraic; ``q`` is never integrated twice, the M1 static compliance correction
``q_loaded = q - Q/K`` is never applied, and the target angle is never copied
into a wheel-angle output.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Mapping

import numpy as np

from steering_sim.control.base import Measurement, Reference
from steering_sim.control.pid import PIDController
from steering_sim.hydraulics_lumped import (HydraulicInput, LumpedHydraulicSystem,
                                            evaluate_hydraulic)

from .authority import authority_as_dict, probe_channel_authority, working_point
from .config import CHANNEL_ORDER, DOF_BY_CHANNEL, J0CaseConfig, J0Config
from .geometry import DOF_ORDER, J0GeometryAdapter, J0MappingError
from .road_load import RoadLoad, road_load, virtual_work_residual

WHEELS = tuple(f"axle{a}_{s}" for a in range(1, 7) for s in ("left", "right"))
THIRD_AXLE_WHEELS = ("axle3_left", "axle3_right")


class J0StopCondition(RuntimeError):
    """A J0 stop condition from ``03_J0_IMPLEMENTATION_BRIEF.md`` section 11."""


@dataclass
class J0CaseResult:
    case: J0CaseConfig
    samples: dict[str, np.ndarray]
    summary: dict[str, Any]
    completed: bool
    failure_time_s: float | None = None
    failure_reason: str | None = None
    diagnostic_damping_n_s_per_m: float = 0.0

    @property
    def case_id(self) -> str:
        return self.case.id


def _ramp(value: float, duration: float) -> float:
    """Smooth 0->1 ramp with zero slope at both ends."""
    if duration <= 0.0:
        return 1.0
    fraction = min(max(value / duration, 0.0), 1.0)
    return float(fraction * fraction * (3.0 - 2.0 * fraction))


@dataclass
class _Recorder:
    fields: dict[str, list[float]] = field(default_factory=dict)

    def add(self, row: Mapping[str, float]) -> None:
        for key, value in row.items():
            self.fields.setdefault(key, []).append(float(value))

    def arrays(self) -> dict[str, np.ndarray]:
        return {key: np.asarray(values, dtype=float) for key, values in self.fields.items()}


class J0Runner:
    """Builds the coupled system once and can run any number of J0 cases."""

    def __init__(self, config: J0Config, geometry_model, *,
                 probe_authority: bool = True) -> None:
        self.config = config
        self.hydraulic = LumpedHydraulicSystem.fast_engineering()
        self.geometry = J0GeometryAdapter(geometry_model, config)
        self.state0, bias = working_point(self.hydraulic)
        self.speeds = tuple(channel.pump.nominal_speed for channel in self.hydraulic.channels)
        self.neutral_commands = tuple(item.neutral_command for item in config.channels)
        self.authorities = (probe_channel_authority(
            self.hydraulic, neutral_commands=self.neutral_commands) if probe_authority else ())
        self.mu = float(config.load["friction_coefficient"])
        self.axle_mass_t = tuple(float(value) for value in config.load["axle_mass_t"])
        self.singular_threshold = float(config.mapping["singular_jacobian_threshold_m_per_rad"])
        self.dt_h = config.dt_hydraulic_s
        self.dt_c = config.dt_control_s
        self.substeps = config.substeps_per_control
        self.stride = config.sample_stride
        self.initial_bias = tuple(bias) if config.hydraulic["load_model"][
            "neutralize_initial_bias"] else (0.0,) * 4
        self.road_ramp_s = float(config.hydraulic["load_model"]["road_load_ramp_s"])
        self.ref_ramp_s = float(config.control["reference_ramp_s"])
        self.redundant = dict(config.hydraulic["redundant_valve_commands"])

    # ------------------------------------------------------------------ target
    def target(self, case: J0CaseConfig) -> dict[str, Any]:
        geometry = self.geometry.target(case.target_outer_angle_deg)
        q_ref = {dof: float(geometry.q_rad[dof]) for dof in DOF_ORDER}
        strokes = self.geometry.seven_cylinder_strokes(q_ref)
        x_ref = {item.channel: strokes[item.cylinder_group.split("+")[0]]
                 for item in self.config.channels}
        return {
            "geometry": geometry,
            "q_ref": q_ref,
            "x_ref": x_ref,
            "curvature_1pm": float(geometry.curvature_1pm),
            # The ideal Ackermann angle is what the customer target implies; the
            # theoretical angle is what the M1 rigid linkage actually reaches at
            # q_ref.  Their difference is the mechanism's own Ackermann error and
            # is not something the J0 hydraulic loop can remove.
            "ideal_deg": {wheel: float(geometry.ideal_ackermann_angle_deg[wheel])
                          for wheel in WHEELS},
            "mechanism_deg": {wheel: float(geometry.theoretical_angle_deg[wheel])
                              for wheel in WHEELS},
        }

    # ------------------------------------------------------------------- stage
    def _stage(self, t: float, state: np.ndarray, commands: list[float],
               curvature_1pm: float, speed_kmh: float, damping: float):
        x_by_channel = {item.channel: float(state[4 * index + 2])
                        for index, item in enumerate(self.config.channels)}
        q_values, status = self.geometry.q_from_strokes(x_by_channel)
        bad = [f"{name}:{item.label}" for name, item in status.items() if not item.ok]
        if bad:
            raise J0StopCondition("mapping " + ";".join(bad))
        road = road_load(self.geometry, q_values, speed_kmh=speed_kmh,
                         friction_coefficient=self.mu, axle_mass_t=self.axle_mass_t,
                         curvature_1pm=curvature_1pm,
                         singular_threshold_m_per_rad=self.singular_threshold)
        if road.flags:
            raise J0StopCondition("road load " + "|".join(road.flags))
        fraction = _ramp(t, self.road_ramp_s)
        loads: list[float] = []
        for index, item in enumerate(self.config.channels):
            road_force = road.hydraulic_load_force_n[DOF_BY_CHANNEL[item.channel]]
            if not math.isfinite(road_force):
                raise J0StopCondition(f"{item.dof}: non-finite road load force")
            value = self.initial_bias[index] + fraction * road_force
            if damping:
                value += damping * float(state[4 * index + 3])
            loads.append(value)
        inputs = HydraulicInput(tuple(commands), self.speeds, tuple(loads),
                                redundant_valve_commands=self.redundant)
        dx, outputs = evaluate_hydraulic(self.hydraulic, t, state, inputs)
        if not np.all(np.isfinite(dx)):
            raise J0StopCondition("non-finite hydraulic derivative")
        return dx, outputs, q_values, road, tuple(loads)

    # --------------------------------------------------------------------- row
    def _row(self, record_index: int, t: float, state: np.ndarray, commands: list[float],
             raw_pid: np.ndarray, outputs, q_values, road: RoadLoad, loads,
             q_ref, x_ref, ref_eff, target: dict, case: J0CaseConfig
             ) -> dict[str, float]:
        row: dict[str, float] = {"time_s": t}
        row["target_outer_angle_deg"] = case.target_outer_angle_deg
        row["speed_kmh"] = case.speed_kmh
        row["lateral_acceleration_mps2"] = road.lateral_acceleration_mps2
        row["adhesion_utilization"] = road.adhesion_utilization
        row["max_abs_slip_angle_deg"] = road.max_abs_slip_angle_deg
        row["road_load_status"] = 1.0 if not road.flags else 0.0
        for position, item in enumerate(self.config.channels):
            dof = DOF_BY_CHANNEL[item.channel]
            tag = item.channel
            row[f"{tag}_q_ref_rad"] = q_ref[dof]
            row[f"{tag}_q_actual_rad"] = q_values[dof]
            row[f"{tag}_x_ref_m"] = x_ref[tag]
            row[f"{tag}_x_ref_eff_m"] = ref_eff[position]
            row[f"{tag}_x_m"] = float(state[4 * position + 2])
            row[f"{tag}_v_m_s"] = float(state[4 * position + 3])
            row[f"{tag}_pA_mpa_g"] = float(state[4 * position]) / 1.0e6
            row[f"{tag}_pB_mpa_g"] = float(state[4 * position + 1]) / 1.0e6
            row[f"{tag}_valve_command"] = float(commands[position])
            row[f"{tag}_pid_raw_output"] = float(raw_pid[position])
            row[f"{tag}_flow_a_m3_s"] = float(outputs.channels[position].flow_a_m3_s)
            row[f"{tag}_flow_b_m3_s"] = float(outputs.channels[position].flow_b_m3_s)
            row[f"{tag}_hydraulic_force_n"] = float(outputs.channels[position].hydraulic_force_n)
            row[f"{tag}_load_force_n"] = float(loads[position])
            row[f"{tag}_dx_dq_m_per_rad"] = road.stroke_jacobian_m_per_rad[dof]
            row[f"{tag}_Q_road_nm"] = road.generalized_road_moment_nm[dof]
            q_dot = float(state[4 * position + 3]) / road.stroke_jacobian_m_per_rad[dof]
            row[f"{tag}_virtual_work_residual_nm_per_s"] = (
                road.hydraulic_load_force_n[dof] * float(state[4 * position + 3])
                - road.generalized_road_moment_nm[dof] * q_dot)
        angles_table = self.geometry.wheel_angles_deg(q_values)
        for wheel in WHEELS:
            row[f"wheel_{wheel}_actual_deg"] = angles_table[wheel]
            row[f"wheel_{wheel}_target_deg"] = target["ideal_deg"][wheel]
            row[f"wheel_{wheel}_target_mechanism_deg"] = target["mechanism_deg"][wheel]
            row[f"wheel_{wheel}_tire_slip_deg"] = road.tire_slip_angle_deg[wheel]
            row[f"wheel_{wheel}_fy_demand_n"] = road.lateral_force_demand_n[wheel]
            row[f"wheel_{wheel}_fy_available_n"] = road.lateral_force_available_n[wheel]
            row[f"wheel_{wheel}_fz_n"] = road.normal_load_n[wheel]
        for axle in (4, 5, 6):
            for side in ("A", "B"):
                row[f"cylinder_axle{axle}_{side}_stroke_m"] = (
                    self.geometry.representative_stroke(f"q{axle}", q_values[f"q{axle}"])
                    if side == "A" else self.geometry.companion_stroke(f"q{axle}", q_values[f"q{axle}"]))
        row["cylinder_front_group_1_stroke_m"] = self.geometry.representative_stroke(
            "q_front", q_values["q_front"])
        row["third_axle_max_abs_deg"] = max(abs(angles_table[w]) for w in THIRD_AXLE_WHEELS)
        row["supply_pressure_front_mpa_g"] = outputs.supply_pressures_pa_g[0] / 1.0e6
        row["supply_pressure_rear_mpa_g"] = outputs.supply_pressures_pa_g[1] / 1.0e6
        row["pump_capacity_insufficient_front"] = float(outputs.pump_capacity_insufficient[0])
        row["pump_capacity_insufficient_rear"] = float(outputs.pump_capacity_insufficient[1])
        row["pump_capacity_margin_front_m3_s"] = outputs.pump_capacity_margin_m3_s[0]
        row["pump_capacity_margin_rear_m3_s"] = outputs.pump_capacity_margin_m3_s[1]
        # The recorder already samples every ``stride`` hydraulic steps, so the
        # exact closed-chain evaluation is affordable at every recorded sample
        # and gives the authoritative residual and wheel angles.
        try:
            exact = self.geometry.exact_linkage(q_values)
        except Exception:  # pragma: no cover - defensive
            row["max_link_residual_m"] = math.nan
            row["chain_condition_number"] = math.nan
            row["exact_linkage_error"] = 1.0
        else:
            row["max_link_residual_m"] = exact.max_link_residual_m
            row["chain_condition_number"] = exact.condition_number
            row["exact_linkage_error"] = 0.0
            row["third_axle_max_abs_deg"] = exact.third_axle_max_abs_deg
            for wheel in WHEELS:
                row[f"wheel_{wheel}_exact_deg"] = exact.wheel_angle_deg[wheel]
            for name, stroke in exact.cylinder_stroke_m.items():
                row[f"cylinder_{name}_exact_stroke_m"] = stroke
        return row

    # -------------------------------------------------------------------- loop
    def run_case(self, case: J0CaseConfig, *,
                 diagnostic_damping_n_s_per_m: float = 0.0,
                 gains: Mapping[str, tuple[float, float, float]] | None = None
                 ) -> J0CaseResult:
        """Run one J0 operating case.

        ``gains`` optionally overrides ``(kp, ki, kd)`` per channel name, which is
        how the J0 gain sensitivity study is produced.  It never changes the
        plant, only the controller.
        """
        target = self.target(case)
        q_ref, x_ref = target["q_ref"], target["x_ref"]
        curvature = target["curvature_1pm"]
        controllers = []
        for item in self.config.channels:
            kp, ki, kd = (gains or {}).get(item.channel, (item.kp, item.ki, item.kd))
            controllers.append(PIDController(kp, ki, kd, limit=item.command_limit))
        for controller in controllers:
            controller.reset()
        limits = np.array([item.command_limit for item in self.config.channels])
        state = self.state0.copy()
        commands = [float(value) for value in self.neutral_commands]
        raw_pid = np.zeros(4)
        recorder = _Recorder()
        steps = int(round(case.duration_s / self.dt_h))
        saturated = 0
        anti_windup = 0
        control_updates = 0
        failure_time: float | None = None
        failure_reason: str | None = None
        completed = True
        step = 0

        try:
            for step in range(steps + 1):
                t = step * self.dt_h
                ref_eff = np.array([_ramp(t, self.ref_ramp_s) * x_ref[item.channel]
                                    for item in self.config.channels])
                if step % self.substeps == 0:
                    errors = ref_eff - np.array([state[4 * i + 2] for i in range(4)])
                    raw_pid = np.empty(4)
                    for position, controller in enumerate(controllers):
                        command = controller.step(
                            Measurement(np.array([state[4 * position + 2]])),
                            Reference(np.array([ref_eff[position]])), self.dt_c)
                        raw_pid[position] = float(command.values[0])
                    commands = [item.command_from_pid(raw_pid[position])
                                for position, item in enumerate(self.config.channels)]
                    over = np.abs(raw_pid) > limits + 1.0e-12
                    saturated += int(np.any(over))
                    anti_windup += int(np.any(over & (np.sign(errors) == np.sign(raw_pid))))
                    control_updates += 1

                dx0, outputs, q_values, road, loads = self._stage(
                    t, state, commands, curvature, case.speed_kmh,
                    diagnostic_damping_n_s_per_m)
                if step % self.stride == 0:
                    recorder.add(self._row(step // self.stride, t, state, commands,
                                           raw_pid, outputs, q_values, road, loads,
                                           q_ref, x_ref, ref_eff, target, case))
                if step == steps:
                    break
                k1 = dx0
                k2 = self._stage(t + self.dt_h / 2, state + self.dt_h * k1 / 2, commands,
                                 curvature, case.speed_kmh,
                                 diagnostic_damping_n_s_per_m)[0]
                k3 = self._stage(t + self.dt_h / 2, state + self.dt_h * k2 / 2, commands,
                                 curvature, case.speed_kmh,
                                 diagnostic_damping_n_s_per_m)[0]
                k4 = self._stage(t + self.dt_h, state + self.dt_h * k3, commands,
                                 curvature, case.speed_kmh,
                                 diagnostic_damping_n_s_per_m)[0]
                state = state + self.dt_h * (k1 + 2.0 * k2 + 2.0 * k3 + k4) / 6.0
                if not np.all(np.isfinite(state)):
                    raise J0StopCondition("non-finite hydraulic state")
        except (J0StopCondition, J0MappingError, ValueError, RuntimeError) as exc:
            completed = False
            failure_time = float(step) * self.dt_h
            failure_reason = f"{type(exc).__name__}: {exc}"

        samples = recorder.arrays()
        summary = self._summarise(case, samples, target, x_ref, saturated, anti_windup,
                                  control_updates, completed, failure_time, failure_reason,
                                  diagnostic_damping_n_s_per_m)
        summary["controller_gains"] = {
            item.channel: list((gains or {}).get(item.channel, (item.kp, item.ki, item.kd)))
            for item in self.config.channels}
        return J0CaseResult(case=case, samples=samples, summary=summary,
                            completed=completed, failure_time_s=failure_time,
                            failure_reason=failure_reason,
                            diagnostic_damping_n_s_per_m=diagnostic_damping_n_s_per_m)

    # ----------------------------------------------------------------- summary
    def _summarise(self, case, samples, target, x_ref, saturated, anti_windup,
                   control_updates, completed, failure_time, failure_reason,
                   diagnostic_damping) -> dict[str, Any]:
        acceptance = self.config.acceptance
        geometry = target["geometry"]
        summary: dict[str, Any] = {
            "case_id": case.id,
            "channel_names": list(CHANNEL_ORDER),
            "dof_order": list(DOF_ORDER),
            "target_outer_angle_deg": case.target_outer_angle_deg,
            "speed_kmh": case.speed_kmh,
            "duration_s": case.duration_s,
            "completed": completed,
            "failure_time_s": failure_time,
            "failure_reason": failure_reason,
            "diagnostic_damping_n_s_per_m": diagnostic_damping,
            "target_q_ref_rad": target["q_ref"],
            "target_x_ref_m": x_ref,
            "target_geometry_status": geometry.geometry_status,
            "target_max_link_residual_m": float(geometry.max_link_length_error_m),
            "third_axle_locked_deg": 0.0,
            "authority": [authority_as_dict(a) for a in self.authorities],
        }
        if "time_s" not in samples or len(samples["time_s"]) == 0:
            summary["status"] = "FAIL"
            summary["status_notes"] = ["no samples recorded"]
            return summary
        time = samples["time_s"]
        tail = slice(max(0, int(len(time) * 0.8)), len(time))
        notes: list[str] = []
        status = "PASS"

        wheel_error = {wheel: float(np.max(np.abs(
            samples[f"wheel_{wheel}_actual_deg"][tail]
            - samples[f"wheel_{wheel}_target_deg"][tail]))) for wheel in WHEELS}
        summary["steady_wheel_angle_error_deg"] = wheel_error
        summary["max_steady_wheel_angle_error_deg"] = max(wheel_error.values())
        summary["final_wheel_angle_deg"] = {wheel: float(samples[f"wheel_{wheel}_actual_deg"][-1])
                                            for wheel in WHEELS}
        summary["target_wheel_angle_deg"] = {wheel: target["ideal_deg"][wheel] for wheel in WHEELS}

        stroke_error = {}
        for item in self.config.channels:
            tag = item.channel
            x = samples[f"{tag}_x_m"]
            stroke_error[tag] = float(np.max(np.abs(x[tail] - x_ref[tag])))
        summary["steady_stroke_error_m"] = stroke_error
        summary["max_stroke_error_m"] = max(stroke_error.values())
        summary["peak_hydraulic_force_n"] = {
            item.channel: float(np.max(np.abs(samples[f"{item.channel}_hydraulic_force_n"])))
            for item in self.config.channels}
        summary["stroke_range_m"] = {
            item.channel: [float(np.min(samples[f"{item.channel}_x_m"])),
                           float(np.max(samples[f"{item.channel}_x_m"]))]
            for item in self.config.channels}
        summary["max_pressure_mpa_g"] = float(max(
            max(float(np.max(np.abs(samples[f"{tag}_pA_mpa_g"]))),
                float(np.max(np.abs(samples[f"{tag}_pB_mpa_g"]))))
            for tag in CHANNEL_ORDER))
        summary["max_abs_velocity_m_s"] = float(max(
            float(np.max(np.abs(samples[f"{tag}_v_m_s"]))) for tag in CHANNEL_ORDER))
        summary["max_abs_stroke_m"] = float(max(
            float(np.max(np.abs(samples[f"{tag}_x_m"]))) for tag in CHANNEL_ORDER))
        residual = samples.get("max_link_residual_m")
        summary["max_link_residual_m"] = (
            float(np.nanmax(residual)) if residual is not None and len(residual) else math.nan)
        summary["chain_condition_number_max"] = (
            float(np.nanmax(samples["chain_condition_number"]))
            if "chain_condition_number" in samples else math.nan)
        summary["third_axle_max_abs_deg"] = float(np.max(samples["third_axle_max_abs_deg"]))
        summary["control_saturation_fraction"] = (
            float(saturated) / float(control_updates) if control_updates else math.nan)
        summary["anti_windup_active_fraction"] = (
            float(anti_windup) / float(control_updates) if control_updates else math.nan)
        summary["pump_capacity_warnings"] = int(
            np.sum(samples["pump_capacity_insufficient_front"])
            + np.sum(samples["pump_capacity_insufficient_rear"]))
        summary["virtual_work_residual_max_abs"] = float(max(
            float(np.max(np.abs(samples[f"{tag}_virtual_work_residual_nm_per_s"])))
            for tag in CHANNEL_ORDER))
        summary["max_adhesion_utilization"] = float(np.max(samples["adhesion_utilization"]))
        summary["max_abs_slip_angle_deg"] = float(np.max(samples["max_abs_slip_angle_deg"]))

        differences = [
            float(np.nanmax(np.abs(samples[f"wheel_{wheel}_actual_deg"]
                                   - samples[f"wheel_{wheel}_exact_deg"])))
            for wheel in WHEELS if f"wheel_{wheel}_exact_deg" in samples]
        summary["max_table_vs_exact_wheel_deg"] = max(differences) if differences else math.nan

        authority_notes: list[str] = []
        for item in self.config.channels:
            tag = item.channel
            low, high = summary["stroke_range_m"][tag]
            required = x_ref[tag]
            if required < low - 1.0e-6 or required > high + 1.0e-6:
                authority_notes.append(f"{tag}:REFERENCE_NOT_REACHED"
                                       f"(ref={required:.6e},range=[{low:.6e},{high:.6e}])")
        summary["authority_flags"] = authority_notes

        if not completed:
            status = "FAIL"
            notes.append(f"stopped at {failure_time:.3f} s: {failure_reason}")
        else:
            if summary["max_steady_wheel_angle_error_deg"] > \
                    acceptance["steady_wheel_angle_error_deg_conditional"]:
                status = "FAIL"
                notes.append("steady wheel-angle error above the conditional band")
            elif summary["max_steady_wheel_angle_error_deg"] > \
                    acceptance["steady_wheel_angle_error_deg_pass"]:
                status = "CONDITIONAL"
                notes.append("steady wheel-angle error above the pass band")
            if not math.isnan(summary["max_link_residual_m"]) and \
                    summary["max_link_residual_m"] > acceptance["link_residual_limit_m"]:
                status = "FAIL"
                notes.append("closed-chain link residual above 1e-9 m")
            if summary["third_axle_max_abs_deg"] > acceptance["third_axle_abs_limit_deg"]:
                status = "FAIL"
                notes.append("third axle is not locked at 0 deg")
            if summary["pump_capacity_warnings"]:
                if status == "PASS":
                    status = "CONDITIONAL"
                notes.append("hydraulic supply capacity warning raised")
            if authority_notes:
                status = "FAIL"
                notes.append("commanded stroke not reachable: " + ", ".join(authority_notes))
        summary["status"] = status
        summary["status_notes"] = notes
        return summary
