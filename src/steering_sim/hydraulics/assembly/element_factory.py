from __future__ import annotations

from dataclasses import dataclass

from .parameter_loader import ParameterDatabase, ParameterValue


SIGNAL_TYPES = {"signal block"}
NON_POWER_TYPES = {"non-power property object", "environment/configuration object"}

# Every active family in IR V3 has an explicit FAST strategy.  Strategies are
# deliberately coarse at Phase 2-A; none means "ignore the component".
FAST_STRATEGIES = {
    "CV010": "static_check_valve_surrogate",
    "CV012": "static_spring_check_orifice_surrogate",
    "FORC": "force_source_exact",
    "FP04": "calibratable_resistance_surrogate",
    "HA001": "gas_accumulator_surrogate",
    "HJ0022": "spring_return_cylinder_surrogate",
    "HJ020": "double_acting_cylinder_surrogate",
    "HJ021": "double_rod_cylinder_surrogate",
    "HL0000": "one_cell_compliance_line",
    "HL0002": "r_c_r_line_surrogate",
    "HL011": "reduced_segmented_r_c_line",
    "HL012": "reduced_segmented_c_r_line",
    "HYDCONSHTL0": "static_flow_control_surrogate",
    "HYDORF0": "regularized_fixed_orifice",
    "HYDORT0": "regularized_orifice_table_surrogate",
    "HYDPG0": "pressure_source_gauge_surrogate",
    "HYDPRV0": "static_pressure_reducing_valve_surrogate",
    "HYDVORF0": "regularized_modulated_orifice",
    "MAS001": "translational_inertia_exact",
    "MAS004": "translational_load_composite_surrogate",
    "PM000": "angular_speed_source_exact",
    "PU001": "fixed_displacement_pump_q0top_unity",
    "PV00022": "static_pressure_control_with_mechanical_states",
    "RV010": "static_relief_valve_surrogate",
    "RV011": "modulated_relief_valve_surrogate",
    "SC_1": "level2_static_spool_valve_composite",
    "TK000": "pressure_boundary_exact",
}


class UnsupportedActiveElementError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RuntimeElement:
    element_id: str
    instance_alias: str
    submodel: str
    level: int
    domain: str
    bg_type: str
    implementation_status: str
    classification: str
    strategy: str
    parameters: tuple[ParameterValue, ...]
    original_state_names: tuple[str, ...]
    port_count: int
    active_power: bool
    rhs_provider: bool


class ElementFactory:
    def __init__(self, parameters: ParameterDatabase) -> None:
        self.parameters = parameters

    @staticmethod
    def is_active(row: dict[str, str]) -> bool:
        return row["bg_type"] not in SIGNAL_TYPES | NON_POWER_TYPES and any(
            domain in row["domain"] for domain in ("hydraulic", "translation", "rotation")
        )

    def create(self, row: dict[str, str]) -> RuntimeElement:
        active = self.is_active(row)
        if row["bg_type"] in SIGNAL_TYPES:
            classification, strategy = "SIGNAL_ONLY", "signal_graph_node"
        elif row["bg_type"] in NON_POWER_TYPES:
            classification, strategy = "NON_POWER", "configuration_object"
        elif active:
            classification = row["implementation_status"]
            strategy = FAST_STRATEGIES.get(row["submodel"], "")
            if not strategy:
                raise UnsupportedActiveElementError(
                    f"active element has no FAST strategy: {row['instance_alias']} / {row['submodel']}"
                )
        else:
            classification, strategy = row["implementation_status"], "passive_metadata"
        state_names = tuple(name for name in row["state_names"].split(";") if name)
        return RuntimeElement(
            row["element_id"], row["instance_alias"], row["submodel"], int(row["level"]),
            row["domain"], row["bg_type"], row["implementation_status"], classification,
            strategy, self.parameters.for_alias(row["instance_alias"]), state_names,
            int(row["port_count"] or 0), active, bool(state_names) and active,
        )
