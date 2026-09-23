"""Generate R03-B1.5 AMESim experiment matrices from frozen R03-B1 configs."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from common import load_json


ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "configs" / "hydraulics" / "r03b1"
DEFAULT_OUTPUT = ROOT / "amesim_experiments" / "r03b15"


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict], overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite existing artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def hydvorf_rows(valve: dict) -> list[dict]:
    path = valve["paths"]["P-A"]
    ident_openings = [0, 1, 5, 10, 25, 50, 75, 100]
    valid_openings = [7, 18, 40, 65, 90]
    ident_positive = [0.001, 0.003, 0.01, 0.03, 0.1, 0.3, 0.5, 1, 2, 5, 10, 20, 50]
    valid_positive = [0.002, 0.007, 0.02, 0.07, 0.2, 0.4, 0.75, 1.5, 3, 7, 15, 30, 40]
    rows: list[dict] = []
    sequence = 1
    for role, openings, positives in [
        ("identification", ident_openings, ident_positive),
        ("validation", valid_openings, valid_positive),
    ]:
        drops = ([0.0] if role == "identification" else []) + [v for p in positives for v in (-p, p)]
        for opening in openings:
            for dp in drops:
                base_pressure = 5.0
                if dp >= 0:
                    p1, p2 = base_pressure + dp, base_pressure
                else:
                    p1, p2 = base_pressure, base_pressure + abs(dp)
                rows.append(
                    {
                        "test_id": f"HV-{sequence:04d}",
                        "set_role": role,
                        "derived_model_id": "R03B15_HYDVORF0_characterization",
                        "source_component": path["internal_component"],
                        "source_submodel": "HYDVORF0",
                        "method": path["method"],
                        "opening_input": opening,
                        "opening_fraction": opening / path["maximum_signal"],
                        "upstream_pressure_bar_g": p1,
                        "downstream_pressure_bar_g": p2,
                        "pressure_drop_bar": dp,
                        "characteristic_flow_lpm": path["characteristic_flow_lpm"],
                        "characteristic_pressure_drop_bar": path["characteristic_pressure_drop_bar"],
                        "critical_flow_number": path["critical_flow_number"],
                        "measurement_density_kg_m3": path["measurement_density_kg_m3"],
                        "measurement_kinematic_viscosity_cst": path["measurement_kinematic_viscosity_cst"],
                        "result_file": "r03b15_hydvorf_results.csv",
                        "provenance": valve["provenance"]["audit_file"],
                        "notes": "pressures arranged so both boundaries remain >=5 bar gauge",
                    }
                )
                sequence += 1
    return rows


def hj020_rows(cylinder: dict, fluid: dict) -> list[dict]:
    stroke = float(cylinder["stroke_m"])
    common = {
        "derived_model_id": "R03B15_HJ020_characterization",
        "source_component": cylinder["provenance"]["source_component"],
        "source_submodel": cylinder["provenance"]["source_submodel"],
        "fluid_submodel": fluid["provenance"]["source_submodel"],
        "fluid_index": fluid["fluid_index"],
        "duration_s": 0.02,
        "output_interval_s": 0.0001,
        "derivative_window_start_s": 0.002,
        "derivative_window_end_s": 0.008,
        "solver": "AMESim Standard variable-step; record exact GUI selection on export",
        "relative_tolerance": 1.0e-8,
        "initialization": "explicitly set p1/p2 and x; avoid endstop",
        "result_file": "r03b15_hj020_results.csv",
        "provenance": cylinder["provenance"]["audit_file"],
    }
    rows: list[dict] = []
    sequence = 1

    def add(role: str, subtest: str, x: float, v: float, q1: float, q2: float, p1: float, p2: float, note: str) -> None:
        nonlocal sequence
        row = dict(common)
        row.update(
            {
                "test_id": f"HJ-{sequence:04d}", "set_role": role, "subtest": subtest,
                "x_initial_m": x, "velocity_mps": v, "q1_lpm": q1, "q2_lpm": q2,
                "p1_initial_bar_g": p1, "p2_initial_bar_g": p2, "notes": note,
            }
        )
        rows.append(row)
        sequence += 1

    for chamber in (1, 2):
        for p in (5, 50, 100, 200):
            for x in (0.1 * stroke, 0.5 * stroke, 0.9 * stroke):
                for q in (-0.05, -0.01, 0.01, 0.05):
                    add("identification", "B1_fixed_piston_prescribed_flow", x, 0, q if chamber == 1 else 0, q if chamber == 2 else 0, p, p, f"excite chamber {chamber}")
        for p in (20, 150):
            for x in (0.25 * stroke, 0.75 * stroke):
                for q in (-0.02, 0.02):
                    add("validation", "B1_fixed_piston_prescribed_flow", x, 0, q if chamber == 1 else 0, q if chamber == 2 else 0, p, p, f"interstitial validation; excite chamber {chamber}")

    for p in (5, 50, 100, 200):
        for x in (0.1 * stroke, 0.5 * stroke, 0.9 * stroke):
            for v in (-0.005, -0.002, 0.002, 0.005):
                add("identification", "B2_zero_flow_prescribed_motion", x, v, 0, 0, p, p, "infer equivalent swept flow for both chambers")
    for p in (20, 150):
        for x in (0.25 * stroke, 0.75 * stroke):
            for v in (-0.003, 0.003):
                add("validation", "B2_zero_flow_prescribed_motion", x, v, 0, 0, p, p, "interstitial motion validation")

    for x in (0.2 * stroke, 0.5 * stroke, 0.8 * stroke):
        for p1, p2 in ((20, 5), (100, 20), (150, 50)):
            for q1, q2, v in ((0.02, -0.01, 0.003), (-0.015, 0.02, -0.003)):
                add("validation", "B3_combined_validation", x, v, q1, q2, p1, p2, "independent combined-condition validation only")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    valve = load_json(CONFIG / "dirvalve_6_sc1.json")
    cylinder = load_json(CONFIG / "actuator001_hj020.json")
    fluid = load_json(CONFIG / "fluid_fp04.json")

    hyd = hydvorf_rows(valve)
    hj = hj020_rows(cylinder, fluid)
    _write_csv(args.output / "r03b15_hydvorf_experiment_matrix.csv", list(hyd[0]), hyd, args.overwrite)
    _write_csv(args.output / "r03b15_hj020_experiment_matrix.csv", list(hj[0]), hj, args.overwrite)

    template_dir = args.output / "results_templates"
    templates = {
        "r03b15_hydvorf_results.csv": ["test_id", "opening_input", "upstream_pressure_bar_g", "downstream_pressure_bar_g", "pressure_drop_bar", "flow_lpm", "area_mm2", "hydraulic_diameter_mm", "amesim_model_checksum", "run_timestamp", "notes"],
        "r03b15_hydvorf_identification.csv": ["test_id", "set_role", "opening_input", "pressure_drop_bar", "flow_lpm", "sign_consistent", "local_exponent", "candidate_flow_lpm", "residual_lpm", "notes"],
        "r03b15_hj020_results.csv": ["test_id", "time_s", "x_m", "velocity_mps", "q1_lpm", "q2_lpm", "p1_bar_g", "p2_bar_g", "force_n", "amesim_model_checksum", "run_timestamp", "notes"],
        "r03b15_hj020_identification.csv": ["test_id", "set_role", "subtest", "x_m", "velocity_mps", "volume1_m3", "volume2_m3", "q1_m3_s", "q2_m3_s", "p1_bar_g", "p2_bar_g", "dp1_dt_pa_s", "dp2_dt_pa_s", "compliance1_m3_pa", "compliance2_m3_pa", "beta_eff1_pa", "beta_eff2_pa", "swept_flow1_m3_s", "swept_flow2_m3_s", "notes"],
        "r03b15_hj020_validation.csv": ["test_id", "subtest", "observed_dp1_dt_pa_s", "predicted_dp1_dt_pa_s", "observed_dp2_dt_pa_s", "predicted_dp2_dt_pa_s", "error1_pa_s", "error2_pa_s", "within_identified_range", "notes"],
    }
    for name, fields in templates.items():
        _write_csv(template_dir / name, fields, [], args.overwrite)

    export_rows = [
        {"experiment": "HYDVORF0", "variable": name, "unit": unit, "required": required, "purpose": purpose}
        for name, unit, required, purpose in [
            ("upstream pressure", "bar", "YES", "p1 and dp"), ("downstream pressure", "bar", "YES", "p2 and dp"),
            ("volumetric flow rate", "L/min", "YES", "constitutive response"), ("opening input", "0..100", "YES", "control variable"),
            ("actual area", "mm^2", "IF_AVAILABLE", "diagnostic"), ("hydraulic diameter", "mm", "IF_AVAILABLE", "diagnostic"),
        ]
    ] + [
        {"experiment": "HJ020", "variable": name, "unit": unit, "required": required, "purpose": purpose}
        for name, unit, required, purpose in [
            ("time", "s", "YES", "derivative regression"), ("xact", "m", "YES", "chamber volume"), ("velocity at mechanical port", "m/s", "YES", "prescribed motion"),
            ("flow at port 1", "L/min", "YES", "B1/B3 input confirmation"), ("flow at port 2", "L/min", "YES", "B1/B3 input confirmation"),
            ("pressure at port 1", "bar", "YES", "state response"), ("pressure at port 2", "bar", "YES", "state response"), ("jack force", "N", "IF_AVAILABLE", "sign diagnostic"),
        ]
    ]
    _write_csv(args.output / "r03b15_amesim_variable_export_list.csv", ["experiment", "variable", "unit", "required", "purpose"], export_rows, args.overwrite)
    print(f"HYDVORF0 matrix: {len(hyd)} rows")
    print(f"HJ020 matrix: {len(hj)} rows")
    print(f"Output: {args.output}")


if __name__ == "__main__":
    main()
