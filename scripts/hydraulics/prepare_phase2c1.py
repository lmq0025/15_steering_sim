from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "hydraulic_audit"


def read(name: str) -> list[dict[str, str]]:
    with (AUDIT / name).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write(name: str, rows: list[dict[str, object]], fields: list[str]) -> None:
    with (AUDIT / name).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)


def main() -> None:
    components = {row["alias"]: row for row in read("01_components.csv")}
    parameters = read("04_parameters.csv")
    variables = read("05_variables.csv")
    signals = read("12D_bondgraph_signal_links_v2.csv")
    params_by_alias: dict[str, list[dict[str, str]]] = {}
    vars_by_alias: dict[str, list[dict[str, str]]] = {}
    for row in parameters: params_by_alias.setdefault(row["alias"], []).append(row)
    for row in variables: vars_by_alias.setdefault(row["alias"], []).append(row)

    source_models = {"CONS00", "STEP0", "SIN0", "UD00"}
    manifest = []
    request_paths: set[str] = set()
    for alias, component in components.items():
        if component["submodel"] not in source_models:
            continue
        params = params_by_alias.get(alias, [])
        outputs = [row for row in vars_by_alias.get(alias, []) if row["io_type"] == "ame_variable_io_output"]
        output_path = outputs[0]["data_path"] if outputs else ""
        if output_path: request_paths.add(output_path)
        parameter_text = "; ".join(f"{row['data_path'].split('@')[0]}={row['resolved_value']} {row['unit']}".strip() for row in params)
        if component["submodel"] == "CONS00": function = "constant from source parameter"
        elif component["submodel"] == "STEP0": function = "Amesim STEP0 piecewise constant step"
        elif component["submodel"] == "SIN0": function = "Amesim SIN0 sinusoid"
        else: function = "Amesim UD00 staged piecewise-linear signal"
        outgoing = [row for row in signals if row["source"] == alias]
        if not outgoing:
            outgoing = [{"target": "", "target_port": "", "direction_verified": "unconnected"}]
        for link in outgoing:
            manifest.append({
                "source_alias": alias, "submodel": component["submodel"],
                "signal_name": output_path, "downstream_component": link["target"],
                "downstream_port": link["target_port"], "parameter/value": parameter_text,
                "time_function": function, "unit": outputs[0]["unit"] if outputs else "",
                "python_equivalent": f"interpolation of measured {output_path}" if output_path else "unmapped",
                "mapping_status": "DIRECT_SOURCE_TRACE" if output_path else "NO_OUTPUT_VARIABLE",
            })
    write("20A_amesim_input_manifest.csv", manifest, ["source_alias", "submodel", "signal_name", "downstream_component", "downstream_port", "parameter/value", "time_function", "unit", "python_equivalent", "mapping_status"])

    mappings: list[dict[str, object]] = []
    def add(quantity: str, alias: str, var: str, unit: str, py: str, py_unit: str, conversion: str, sign: str = "+1", priority: str = "HIGH", status: str = "DIRECT") -> None:
        path = f"{var}@{alias}"
        mappings.append({"physical_quantity": quantity, "amesim_alias": alias, "amesim_data_path": path, "amesim_unit": unit, "python_output": py, "python_unit": py_unit, "conversion": conversion, "sign_relation": sign, "comparison_priority": priority, "mapping_status": status})
        request_paths.add(path)

    for alias in ("pump01", "pump01_1", "pump01_2", "pump01_3"):
        add("pump speed", alias, "speed", "rev/min", f"{alias}.speed_rad_s", "rad/s", "x*pi/30")
        add("pump outlet flow", alias, "qout", "L/min", f"{alias}.flow_m3_s", "m^3/s", "x/60000")
        add("pump inlet flow", alias, "qin", "L/min", f"{alias}.flow_m3_s", "m^3/s", "x/60000", "-1", "MEDIUM")
        add("pump inlet pressure", alias, "pin", "bar", f"{alias}.pin_pa", "Pa", "x*1e5")
        add("pump outlet pressure", alias, "pout", "bar", f"{alias}.pout_pa", "Pa", "x*1e5")
        add("pump torque", alias, "torque", "Nm", f"{alias}.torque_nm", "N*m", "x")

    actuator_aliases = ("actuator001", "actuator001_1", "actuator001_2", "actuator002", "springreturnactuator", "springreturnactuator_1", "springreturnactuator_2")
    for alias in actuator_aliases:
        existing = {row["data_path"].split("@")[0]: row for row in vars_by_alias.get(alias, [])}
        specs = (("p1", "pressure chamber 1", "bar", "p1_pa", "Pa", "x*1e5"), ("p2", "pressure chamber 2", "bar", "p2_pa", "Pa", "x*1e5"), ("frod", "rod force", "N", "force_n", "N", "x"), ("x", "rod position", "m", "position_m", "m", "x"), ("v", "rod velocity", "m/s", "velocity_m_s", "m/s", "x"))
        for var, quantity, unit, suffix, pyunit, conversion in specs:
            if var in existing:
                add(quantity, alias, var, unit, f"{alias}.{suffix}", pyunit, conversion)

    # One representative of every frozen SC_1 structural variant.
    for alias in ("dirvalve_1", "dirvalve_2", "dirvalve_6", "dirvalve_3"):
        add("SC_1 external command", alias, "signal_input", "null", f"{alias}.command", "1", "x", priority="HIGH")
        add("SC_1 fractional spool position", alias, "frac_spool_position", "null", f"{alias}.opening", "1", "x", priority="HIGH", status="FAST_STATIC_MAPPING")
        add("SC_1 P-A area", alias, "marea_P_A", "mm**2", f"{alias}.opening", "1", "normalized proxy", priority="MEDIUM", status="PROXY_NOT_DIRECTLY_COMPARABLE")
        orifices = [name for name in ("orifice_13", "orifice_14", "orifice_23", "orifice_24") if f"{alias}.{name}" in components]
        if orifices:
            add("SC_1 active MR branch flow", f"{alias}.{orifices[0]}", "q2", "L/min", f"{alias}.flow_m3_s", "m^3/s", "x/60000", priority="MEDIUM", status="FAST_AGGREGATE_PROXY")

    pressure_models = {"CV010", "CV012", "RV010", "RV011", "HYDPRV0", "PV00022"}
    for alias, component in components.items():
        if component["submodel"] not in pressure_models or "." in alias:
            continue
        names = {row["data_path"].split("@")[0] for row in vars_by_alias.get(alias, [])}
        for var, quantity, unit, suffix, conversion in (("p1", "control valve p1", "bar", "p1_pa", "x*1e5"), ("p2", "control valve p2", "bar", "p2_pa", "x*1e5"), ("pa", "control valve p1", "bar", "p1_pa", "x*1e5"), ("pb", "control valve p2", "bar", "p2_pa", "x*1e5"), ("q2", "control valve flow", "L/min", "flow_m3_s", "x/60000"), ("qb", "control valve flow", "L/min", "flow_m3_s", "x/60000"), ("x", "control valve opening", "null", "opening", "x"), ("sigin", "control valve command", "null", "command", "x")):
            if var in names:
                add(quantity, alias, var, unit, f"{alias}.{suffix}", "Pa" if suffix.endswith("pa") else ("m^3/s" if "flow" in suffix else "1"), conversion, priority="HIGH" if suffix in {"p1_pa", "p2_pa", "flow_m3_s"} else "MEDIUM", status="RUNTIME_DERIVED")

    add("tank pressure", "tank01", "press", "bar", "tank01.pressure_pa", "Pa", "x*1e5")
    for alias in ("hydraulic", "hydraulic_1", "hydraulic_34", "hydraulic_35"):
        add("key physical line inlet pressure", alias, "p1", "bar", f"{alias}.p1_pa", "Pa", "x*1e5")
        add("key physical line outlet pressure", alias, "p2", "bar", f"{alias}.p2_pa", "Pa", "x*1e5")
        add("key physical line inlet flow", alias, "q1", "L/min", f"{alias}.flow_m3_s", "m^3/s", "x/60000")
    write("20B_amesim_python_variable_map.csv", mappings, ["physical_quantity", "amesim_alias", "amesim_data_path", "amesim_unit", "python_output", "python_unit", "conversion", "sign_relation", "comparison_priority", "mapping_status"])

    # Map each 109-state FAST state to original Amesim physical state paths.
    registry = read("11A_state_variable_registry.csv")
    registry_keys = {(row["instance"], row["state_name"]): row for row in registry}
    state_rows = []
    for state in read("16E_full_state_index_FAST.csv"):
        source_names = [name for name in state["source_states"].split(";") if name]
        source_paths = [f"{name}@{state['instance']}" for name in source_names if (state["instance"], name) in registry_keys]
        if not source_paths and (state["instance"], state["state_name"]) in registry_keys:
            source_paths = [f"{state['state_name']}@{state['instance']}"]
        if state["state_name"].endswith("_1") and len(source_paths) > 1:
            source_paths = source_paths[:4]
        elif state["state_name"].endswith("_2") and len(source_paths) > 1:
            source_paths = source_paths[4:]
        rule = "direct retained state" if len(source_paths) == 1 else ("equal-volume pressure average" if source_paths else "engineering default")
        weights = ";".join([str(1.0 / len(source_paths))] * len(source_paths)) if source_paths else ""
        state_rows.append({"fast_state": f"{state['instance']}.{state['state_name']}", "state_index": state["index"], "amesim_source_states": ";".join(source_paths), "mapping_rule": rule, "weights": weights, "confidence": "HIGH" if len(source_paths) == 1 else ("MEDIUM" if source_paths else "LOW")})
        request_paths.update(source_paths)
    write("20C_full_to_fast_state_mapping.csv", state_rows, ["fast_state", "state_index", "amesim_source_states", "mapping_rule", "weights", "confidence"])

    # Runtime input traces are read at their actual modulated component inputs.
    input_targets = []
    port_rows = read("17B_bondgraph_ports_v3.csv")
    mechanical_junctions: dict[str, list[str]] = {}
    for port in port_rows:
        if port["domain"] == "translation":
            mechanical_junctions.setdefault(port["connected_junction"], []).append(port["element_id"].removeprefix("L1_"))
    for alias, component in components.items():
        names = {row["data_path"].split("@")[0] for row in vars_by_alias.get(alias, [])}
        if component["submodel"] == "SC_1" and "signal_input" in names:
            input_targets.append({"python_key": alias, "amesim_path": f"signal_input@{alias}", "kind": "command"})
        elif component["submodel"] == "PV00022" and "sigin" in names:
            input_targets.append({"python_key": alias, "amesim_path": f"sigin@{alias}", "kind": "command"})
        elif component["submodel"] in {"HYDVORF0"} and "input" in names and "." not in alias:
            input_targets.append({"python_key": alias, "amesim_path": f"input@{alias}", "kind": "command"})
        if component["submodel"] == "PU001" and "speed" in names:
            input_targets.append({"python_key": f"{alias}.speed_rad_s", "amesim_path": f"speed@{alias}", "kind": "speed_rpm"})
        if component["submodel"] == "FORC" and "force" in names:
            junction = next((port["connected_junction"] for port in port_rows if port["element_id"] == f"L1_{alias}" and port["domain"] == "translation"), "")
            masses = [item for item in mechanical_junctions.get(junction, []) if components.get(item, {}).get("submodel") in {"MAS001", "MAS004"}]
            if masses:
                input_targets.append({"python_key": f"{masses[0]}.force_n", "amesim_path": f"force@{alias}", "kind": "force_n"})
        request_paths.update(item["amesim_path"] for item in input_targets)

    request = {"paths": sorted(request_paths), "input_targets": input_targets, "duration_s": 1.0, "interval_s": 0.001}
    (AUDIT / "20_amesim_request.json").write_text(json.dumps(request, indent=2), encoding="utf-8")
    print(f"INPUT MANIFEST = {len(manifest)} rows")
    print(f"VARIABLE MAP = {len(mappings)} rows")
    print(f"STATE MAP = {len(state_rows)} / 109")
    print(f"AMESIM REQUEST PATHS = {len(request_paths)}")


if __name__ == "__main__":
    main()
