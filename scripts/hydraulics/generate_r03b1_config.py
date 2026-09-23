"""Generate R03-B1 JSON configurations from the frozen A2.5 audit tables."""

from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "configs" / "hydraulics" / "amesim_audit"
OUTPUT = ROOT / "configs" / "hydraulics" / "r03b1"
KEYS = AUDIT / "r03a25_resolved_key_parameters.csv"
PARAMETERS = AUDIT / "hydraulic_parameters.csv"


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _find(rows: list[dict[str, str]], component: str, name: str) -> dict[str, str]:
    matches = [row for row in rows if row["component_id"] == component and row["parameter_name"] == name]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one frozen row for {component!r}/{name!r}; found {len(matches)}")
    return matches[0]


def _number(rows: list[dict[str, str]], component: str, name: str) -> float:
    row = _find(rows, component, name)
    value = row.get("resolved_value") or row.get("value")
    if not value or value == "missing":
        raise RuntimeError(f"Frozen numeric value is missing: {component}/{name}")
    return float(value)


def _raw(rows: list[dict[str, str]], component: str, name: str) -> str:
    return _find(rows, component, name)["raw_value"]


def _number_by_data_path(rows: list[dict[str, str]], component: str, data_path: str) -> float:
    matches = [row for row in rows if row["component_id"] == component and f"Data_Path={data_path}@" in row.get("notes", "")]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one row for {component!r} Data_Path={data_path!r}; found {len(matches)}")
    return float(matches[0]["value"])


def _write(name: str, payload: dict[str, object]) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / name).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    keys, all_parameters = _rows(KEYS), _rows(PARAMETERS)
    provenance = {"audit_file": str(KEYS.relative_to(ROOT)).replace("\\", "/")}

    fp = "elementaryhydraulicprops_1"
    _write("fluid_fp04.json", {
        "schema_version": "R03-B1-v1",
        "provenance": {**provenance, "source_component": fp, "source_submodel": "FP04"},
        "fluid_index": int(_number(all_parameters, fp, "index of hydraulic fluid")),
        "density_kg_m3": _number(all_parameters, fp, "density"),
        "bulk_modulus_bar": _number(all_parameters, fp, "bulk modulus"),
        "dynamic_viscosity_cp": _number(all_parameters, fp, "absolute viscosity"),
        "air_content_percent": _number(all_parameters, fp, "air/gas content"),
        "saturation_pressure_bar": _number_by_data_path(all_parameters, fp, "fpsp"),
        "notes": "FP04 type=2; pressure-property utilities remain an explicit R03-B1 blocker.",
    })

    actuator = "actuator001"
    _write("actuator001_hj020.json", {
        "schema_version": "R03-B1-v1",
        "provenance": {**provenance, "source_component": actuator, "source_submodel": "HJ020"},
        "piston_diameter_mm": _number(keys, actuator, "piston diameter"),
        "rod_diameter_mm": _number(keys, actuator, "rod diameter"),
        "stroke_m": _number(keys, actuator, "length of stroke"),
        "dead_volume_1_cm3": _number(keys, actuator, "dead volume at port 1 end"),
        "dead_volume_2_cm3": _number(keys, actuator, "dead volume at port 2 end"),
        "leakage_lpm_per_bar": _number(keys, actuator, "leakage coefficient"),
        "viscous_friction_n_per_mps": _number(keys, actuator, "viscous friction coefficient"),
        "initial_pressure_1_bar": _number(keys, actuator, "pressure at port 1"),
        "initial_pressure_2_bar": _number(keys, actuator, "pressure at port 2"),
        "displacement_definition": "xact reported by HJ020; prescribed velocity is dxact/dt=-v_port",
    })

    parent = "dirvalve_6"
    internal = f"{parent}/fractional_spool_position_dynamics"
    paths = {"P-B": "orifice_13", "P-A": "orifice_14", "T-B": "orifice_23", "T-A": "orifice_24"}
    prefix = {"P-B": "P-B", "P-A": "P-A", "T-B": "T-B", "T-A": "T-A"}
    valve_paths: dict[str, object] = {}
    for path, component_leaf in paths.items():
        component = f"{parent}/{component_leaf}"
        valve_paths[path] = {
            "internal_component": component,
            "opening_expression": _raw(keys, parent, f"{prefix[path]} fractional area [null] function of fractional spool position [null]"),
            "characteristic_flow_lpm": _number(keys, component, "characteristic flow rate at maximum opening"),
            "characteristic_pressure_drop_bar": _number(keys, component, "corresponding pressure drop"),
            "critical_flow_number": _number(keys, component, "critical flow number (laminar/turbulent)"),
            "measurement_density_kg_m3": _number(keys, component, "working density for pressure drop measurement"),
            "measurement_kinematic_viscosity_cst": _number(keys, component, "working kinematic viscosity for pressure drop measurement"),
            "method": int(_number(keys, component, "pressure drop definition method")),
            "minimum_signal": _number(keys, component, "minimum signal value"),
            "maximum_signal": _number(keys, component, "maximum signal value"),
        }
    _write("dirvalve_6_sc1.json", {
        "schema_version": "R03-B1-v1",
        "provenance": {**provenance, "source_component": parent, "source_submodel": "SC_1"},
        "external_ports": {"ext0": "P", "ext1": "T", "ext2": "B", "ext3": "A", "ext4": "signal"},
        "spool_mapping_expression": _raw(keys, parent, "fractional spool position [null] function of Fractional displacement [null]"),
        "dynamics": {
            "mode": int(_number(keys, internal, "spool dynamics")),
            "minimum": _number(keys, internal, "minimum output signal"),
            "maximum": _number(keys, internal, "maximum output signal"),
            "inactive_saved_parameters": {
                "time_constant_s": _number(keys, internal, "valve time constant"),
                "natural_frequency_hz": _number(keys, internal, "valve natural frequency"),
                "damping_ratio": _number(keys, internal, "valve damping ratio"),
            },
        },
        "paths": valve_paths,
    })


if __name__ == "__main__":
    main()
