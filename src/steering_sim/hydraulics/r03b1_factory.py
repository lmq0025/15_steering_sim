"""Construct R03-B1 components from generated, provenance-bearing JSON."""

from __future__ import annotations

from pathlib import Path
from .cylinder import HJ020Config, HJ020Cylinder
from .expressions import SafeExpression
from .fluid import ConstantFluidProperties
from .orifice import HYDVORF0, HYDVORF0Config
from .r03b1_config import load_json_config
from .single_actuator_rig import SingleActuatorPrescribedMotionRig
from .units import bar_to_pa, cm3_to_m3, cp_to_pa_s, cst_to_m2ps, lpm_to_m3ps, mm_to_m
from .valve import SC1StaticValve
from .valve_dynamics import StaticValveDynamics


def build_r03b1_rig(config_dir: str | Path) -> SingleActuatorPrescribedMotionRig:
    root = Path(config_dir)
    fluid_raw = load_json_config(root / "fluid_fp04.json")
    fluid = ConstantFluidProperties(
        int(fluid_raw["fluid_index"]), float(fluid_raw["density_kg_m3"]),
        bar_to_pa(float(fluid_raw["bulk_modulus_bar"])), cp_to_pa_s(float(fluid_raw["dynamic_viscosity_cp"])),
        float(fluid_raw["air_content_percent"]), bar_to_pa(float(fluid_raw["saturation_pressure_bar"])),
    )
    cyl_raw = load_json_config(root / "actuator001_hj020.json")
    cylinder = HJ020Cylinder(HJ020Config(
        mm_to_m(float(cyl_raw["piston_diameter_mm"])), mm_to_m(float(cyl_raw["rod_diameter_mm"])),
        float(cyl_raw["stroke_m"]), cm3_to_m3(float(cyl_raw["dead_volume_1_cm3"])),
        cm3_to_m3(float(cyl_raw["dead_volume_2_cm3"])),
        lpm_to_m3ps(float(cyl_raw["leakage_lpm_per_bar"])) / bar_to_pa(1.0),
        float(cyl_raw["viscous_friction_n_per_mps"]),
    ), fluid)
    valve_raw = load_json_config(root / "dirvalve_6_sc1.json")
    dynamics_raw = valve_raw["dynamics"]
    dynamics = StaticValveDynamics(float(dynamics_raw["minimum"]), float(dynamics_raw["maximum"]), int(dynamics_raw["mode"]))
    openings, orifices = {}, {}
    for name, raw in valve_raw["paths"].items():
        openings[name] = SafeExpression(raw["opening_expression"], variables=("x",))
        orifices[name] = HYDVORF0(HYDVORF0Config(
            lpm_to_m3ps(float(raw["characteristic_flow_lpm"])), bar_to_pa(float(raw["characteristic_pressure_drop_bar"])),
            float(raw["critical_flow_number"]), float(raw["measurement_density_kg_m3"]),
            cst_to_m2ps(float(raw["measurement_kinematic_viscosity_cst"])), float(raw["minimum_signal"]),
            float(raw["maximum_signal"]), int(raw["method"]),
        ))
    valve = SC1StaticValve(SafeExpression(valve_raw["spool_mapping_expression"], variables=("x",)), openings, dynamics, orifices)
    return SingleActuatorPrescribedMotionRig(valve, cylinder)

