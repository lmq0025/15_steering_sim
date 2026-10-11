"""Batch execution and CSV/XLSX I/O for PHASE M1."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path
import sys
from typing import Iterable

import numpy as np
import pandas as pd

from .model import CaseInput, DOF_ORDER, REAR_CYLINDERS, WHEEL_ORDER, PhaseM1Model


REQUIRED_CASE_COLUMNS = (
    "speed_kmh",
    "first_axle_outer_angle_deg",
    "friction_coefficient",
    "axle1_mass_t",
    "axle2_mass_t",
    "axle3_mass_t",
    "axle4_mass_t",
    "axle5_mass_t",
    "axle6_mass_t",
)


def default_cases(config: dict) -> list[CaseInput]:
    scan = config["default_scan"]
    speed_cfg = scan["speed_kmh"]
    angle_cfg = scan["first_axle_outer_angle_deg"]
    speeds = np.arange(speed_cfg["start"], speed_cfg["stop"] + 0.5 * speed_cfg["step"], speed_cfg["step"])
    angles = np.arange(angle_cfg["start"], angle_cfg["stop"] + 0.5 * angle_cfg["step"], angle_cfg["step"])
    masses = tuple(map(float, scan["axle_mass_t"]))
    scenario = str(scan["default_stiffness_scenario"])
    return [
        CaseInput(float(speed), float(angle), float(mu), masses, scenario)
        for angle in angles
        for speed in speeds
        for mu in scan["friction_coefficients"]
    ]


def read_cases(path: str | Path, config: dict) -> list[CaseInput]:
    path = Path(path)
    if path.suffix.lower() == ".csv":
        frame = pd.read_csv(path)
    elif path.suffix.lower() in {".xlsx", ".xls"}:
        frame = pd.read_excel(path)
    else:
        raise ValueError("case table must be CSV or XLSX")
    missing = [name for name in REQUIRED_CASE_COLUMNS if name not in frame.columns]
    if missing:
        raise ValueError(f"case table missing columns: {missing}")
    default_scenario = config["default_scan"]["default_stiffness_scenario"]
    cases = []
    for row in frame.to_dict(orient="records"):
        cases.append(CaseInput(
            speed_kmh=float(row["speed_kmh"]),
            first_axle_outer_angle_deg=float(row["first_axle_outer_angle_deg"]),
            friction_coefficient=float(row["friction_coefficient"]),
            axle_mass_t=tuple(float(row[f"axle{axle}_mass_t"]) for axle in range(1, 7)),
            stiffness_scenario=str(row.get("stiffness_scenario", default_scenario)),
        ))
    return cases


def _case_id(index: int) -> str:
    return f"M1_{index:05d}"


def _finite_or_blank(value):
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return np.nan
    return value


def run_cases(model: PhaseM1Model, cases: Iterable[CaseInput]):
    cases = list(cases)
    geometry_cache = {
        angle: model.solve_geometry(angle)
        for angle in sorted({case.first_axle_outer_angle_deg for case in cases})
    }
    all_rows: list[dict] = []
    wheel_rows: list[dict] = []
    for index, case in enumerate(cases, start=1):
        case_id = _case_id(index)
        geometry = geometry_cache[case.first_axle_outer_angle_deg]
        result = model.solve_loaded_case(case, geometry)
        row = {
            "case_id": case_id,
            "speed_kmh": case.speed_kmh,
            "first_axle_outer_angle_deg": case.first_axle_outer_angle_deg,
            "friction_coefficient": case.friction_coefficient,
            "stiffness_scenario": case.stiffness_scenario,
            **{f"axle{axle}_mass_t": case.axle_mass_t[axle - 1] for axle in range(1, 7)},
            "outer_wheel": geometry.outer_wheel or "straight",
            "x_icr_m": _finite_or_blank(geometry.x_icr_m),
            "y_icr_m": _finite_or_blank(geometry.y_icr_m),
            "turn_radius_m": _finite_or_blank(geometry.turn_radius_m),
            "curvature_1pm": geometry.curvature_1pm,
            "lateral_acceleration_mps2": result.lateral_acceleration_mps2,
            "lateral_force_total_demand_N": result.lateral_force_total_demand_N,
            "lateral_force_total_available_N": result.lateral_force_total_available_N,
            "adhesion_utilization": result.adhesion_utilization,
            "max_abs_slip_angle_deg": result.max_abs_slip_angle_deg,
            "max_link_length_error_m": geometry.max_link_length_error_m,
            "geometry_reachable": geometry.geometry_reachable,
            "loaded_geometry_reachable": result.loaded_geometry_reachable,
            "geometry_status": geometry.geometry_status,
            "applicability_status": result.applicability_status,
        }
        for dof in DOF_ORDER:
            row[f"{dof}_theoretical_rad"] = geometry.q_rad[dof]
            row[f"{dof}_loaded_rad"] = result.loaded_q_rad[dof]
            row[f"{dof}_generalized_road_moment_Nm"] = result.generalized_road_moment_Nm[dof]
        for wheel in WHEEL_ORDER:
            row[f"{wheel}_ideal_ackermann_angle_deg"] = geometry.ideal_ackermann_angle_deg[wheel]
            row[f"{wheel}_theoretical_angle_deg"] = geometry.theoretical_angle_deg[wheel]
            row[f"{wheel}_actual_loaded_angle_deg"] = result.actual_loaded_angle_deg[wheel]
            row[f"{wheel}_ackermann_geometry_error_deg"] = geometry.ackermann_geometry_error_deg[wheel]
            row[f"{wheel}_load_induced_angle_error_deg"] = result.load_induced_angle_error_deg[wheel]
            wheel_rows.append({
                "case_id": case_id,
                "speed_kmh": case.speed_kmh,
                "first_axle_outer_angle_deg": case.first_axle_outer_angle_deg,
                "friction_coefficient": case.friction_coefficient,
                "stiffness_scenario": case.stiffness_scenario,
                "wheel": wheel,
                "axle": int(wheel[4]),
                "side": wheel.split("_", 1)[1],
                "ideal_ackermann_angle_deg": geometry.ideal_ackermann_angle_deg[wheel],
                "theoretical_angle_deg": geometry.theoretical_angle_deg[wheel],
                "actual_loaded_angle_deg": result.actual_loaded_angle_deg[wheel],
                "ackermann_geometry_error_deg": geometry.ackermann_geometry_error_deg[wheel],
                "load_induced_angle_error_deg": result.load_induced_angle_error_deg[wheel],
                "tire_slip_angle_deg": result.tire_slip_angle_deg[wheel],
                "lateral_force_demand_N": result.lateral_force_demand_N[wheel],
                "lateral_force_available_N": result.lateral_force_available_N[wheel],
                "normal_load_N": result.normal_load_N[wheel],
                "road_moment_Nm": result.road_moment_Nm[wheel],
                "applicability_status": result.applicability_status,
            })
        all_rows.append(row)
    cylinder_rows = []
    for angle, geometry in sorted(geometry_cache.items()):
        for cylinder in ("front_group_1", *REAR_CYLINDERS):
            if cylinder == "front_group_1":
                frame_mount = model.config["front_cylinder_interface"]["frame_mount"]
                moving_mount = model.config["front_cylinder_interface"]["moving_mount"]
                source = model.config["front_cylinder_interface"]["stroke_mapping_source"]
            else:
                axle, side = cylinder.removeprefix("axle").split("_")
                actuator = model.reference.actuators[f"ACTUATOR_{axle}_{side}"]
                frame_mount = actuator.frame_point_id
                moving_mount = actuator.moving_point_id
                source = "CUSTOMER_COORDINATES_DERIVED_FIXED_LENGTH_KINEMATICS"
            cylinder_rows.append({
                "first_axle_outer_angle_deg": angle,
                "cylinder_id": cylinder,
                "frame_mount": frame_mount,
                "moving_mount": moving_mount,
                "displacement_mm": geometry.cylinder_displacement_mm[cylinder],
                "absolute_length_mm": _finite_or_blank(geometry.cylinder_absolute_length_mm[cylinder]),
                "active_in_M1": True,
                "source": source,
            })
    return pd.DataFrame(all_rows), pd.DataFrame(wheel_rows), pd.DataFrame(cylinder_rows), geometry_cache


def parameter_frame(model: PhaseM1Model) -> pd.DataFrame:
    rows = []

    def add(name, value, unit, source, notes=""):
        rows.append({"parameter": name, "value": value, "unit": unit, "source": source, "notes": notes})

    ground = model.config["ground_load"]
    add("gravity", ground["gravity_mps2"], "m/s^2", "PHYSICAL_CONSTANT")
    add("cornering_stiffness_per_wheel", ground["cornering_stiffness_per_wheel_N_per_rad"], "N/rad", ground["cornering_stiffness_source"])
    add("linear_slip_limit", ground["linear_slip_limit_deg"], "deg", "ASSUMED_ENGINEERING_PARAMETER")
    add("effective_trail", ground["effective_trail_m"], "m", ground["effective_trail_source"])
    add("pivot_effective_radius", ground["pivot_effective_radius_m"], "m", ground["pivot_effective_radius_source"])
    add("pivot_transition_speed", ground["pivot_transition_speed_kmh"], "km/h", ground["pivot_transition_source"])
    add("pivot_engagement_angle", ground["pivot_engagement_angle_deg"], "deg", ground["pivot_engagement_source"])
    for scenario, values in ground["stiffness_scenarios_Nm_per_rad"].items():
        for dof, value in values.items():
            add(f"steering_stiffness.{scenario}.{dof}", value, "Nm/rad", ground["stiffness_source"])
    geometry = model.config["geometry"]
    for dof, bounds in geometry["q_envelopes_rad"].items():
        add(f"numerical_q_envelope.{dof}", json.dumps(bounds), "rad", geometry["q_envelope_source"])
    for wheel, (x, y) in model.centers.items():
        add(f"wheel_center.{wheel}", f"{x * 1000:.6f},{y * 1000:.6f}", "mm", "CUSTOMER_COORDINATE")
    add("third_axle_point20", "-7290,-996", "mm", "CUSTOMER_COORDINATE", "fixed wheel-frame pivot; axle locked in M1")
    add("third_axle_actuator_records", "inactive", "status", geometry["third_axle_actuator_records"])
    front = model.config["front_cylinder_interface"]
    add("front_cylinder.stroke_per_q", front["stroke_per_q_mm_per_rad"], "mm/rad", front["stroke_mapping_source"])
    add("front_cylinder.mounts", f"{front['frame_mount']} -> {front['moving_mount']}", "text", front["stroke_mapping_source"])
    return pd.DataFrame(rows)


def sensitivity_frame(model: PhaseM1Model) -> pd.DataFrame:
    rows = []
    masses = tuple(map(float, model.config["default_scan"]["axle_mass_t"]))
    geometry = model.solve_geometry(10.0)
    for scenario in ("low_flexibility", "medium_flexibility", "high_flexibility"):
        result = model.solve_loaded_case(CaseInput(20.0, 10.0, 0.75, masses, scenario), geometry)
        for wheel in WHEEL_ORDER:
            rows.append({
                "stiffness_scenario": scenario,
                "wheel": wheel,
                "theoretical_angle_deg": geometry.theoretical_angle_deg[wheel],
                "actual_loaded_angle_deg": result.actual_loaded_angle_deg[wheel],
                "load_induced_angle_error_deg": result.load_induced_angle_error_deg[wheel],
            })
    return pd.DataFrame(rows)


def write_outputs(model: PhaseM1Model, cases: list[CaseInput], output_dir: str | Path):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    all_cases, wheel_angles, cylinders, geometry_cache = run_cases(model, cases)
    parameters = parameter_frame(model)
    sensitivity = sensitivity_frame(model)
    all_cases.to_csv(output_dir / "all_cases.csv", index=False, encoding="utf-8-sig")
    wheel_angles.to_csv(output_dir / "wheel_angles.csv", index=False, encoding="utf-8-sig")
    cylinders.to_csv(output_dir / "cylinder_displacements.csv", index=False, encoding="utf-8-sig")
    parameters.to_csv(output_dir / "model_parameters.csv", index=False, encoding="utf-8-sig")
    sensitivity.to_csv(output_dir / "flexibility_sensitivity.csv", index=False, encoding="utf-8-sig")
    return all_cases, wheel_angles, cylinders, parameters, sensitivity, geometry_cache


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run PHASE M1 six-axle mechanical model")
    root = Path(__file__).resolve().parents[1]
    parser.add_argument("--geometry", type=Path, default=root / "mechanical_model_input_spec_v1.0.yaml")
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.json"))
    parser.add_argument("--cases", type=Path, default=None, help="optional CSV/XLSX case table")
    parser.add_argument("--output-dir", type=Path, default=root / "outputs/mechanics/phase_M1")
    args = parser.parse_args(argv)
    model = PhaseM1Model(args.geometry, args.config)
    cases = read_cases(args.cases, model.config) if args.cases else default_cases(model.config)
    all_cases, *_ = write_outputs(model, cases, args.output_dir)
    infeasible = int((all_cases["applicability_status"] != "APPLICABLE_WITH_ASSUMED_PARAMETERS").sum())
    geometry_fail = int((~all_cases["geometry_reachable"]).sum())
    print(f"PHASE M1 batch rows: {len(all_cases)}")
    print(f"infeasible/conditional rows: {infeasible}")
    print(f"geometry-infeasible rows: {geometry_fail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
