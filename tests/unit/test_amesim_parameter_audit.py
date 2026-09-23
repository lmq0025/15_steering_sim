"""R03-A2 audit integrity tests; no hydraulic physics implementation."""
import csv
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

ROOT=Path(__file__).parents[2]
AUDIT=ROOT/"configs/hydraulics/amesim_audit"
SPEC=importlib.util.spec_from_file_location(
    "amesim_parameter_audit",ROOT/"scripts/hydraulics/amesim_audit/audit_parameters.py")
audit=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def load(name):
    path=AUDIT/name
    if not path.exists():
        pytest.skip(f"Customer audit artifact unavailable: {name}")
    with path.open(encoding="utf-8-sig",newline="") as stream:
        return list(csv.DictReader(stream))


@pytest.fixture(scope="module")
def components():
    return {r["component_id"]:r for r in load("hydraulic_components.csv")}


def test_formal_component_foreign_keys_and_submodels(components):
    for name in ("hydraulic_parameters.csv","hydraulic_initial_states.csv",
                 "hydraulic_variables.csv"):
        for row in load(name):
            assert row["component_id"] in components
            assert row["submodel"]==components[row["component_id"]]["submodel"]


def test_parameter_schema_raw_values_and_enums():
    rows=load("hydraulic_parameters.csv")
    assert list(rows[0])==audit.PARAM_FIELDS
    assert len(rows)==4334
    assert all(r["raw_value"] not in {"","missing"} for r in rows)
    allowed={"numeric","expression","global_reference","local_reference","table","curve",
             "string","enum","boolean","missing","other"}
    assert {r["value_type"] for r in rows}<=allowed
    assert all(r["source"] and r["confidence"] in
               {"confirmed","manual_confirmed","inferred","missing"} for r in rows)


def test_raw_evidence_counts_and_alignment():
    assert len(load("r03a2_raw_parameters.csv"))==4142+30+11+162
    assert len(load("r03a2_raw_states.csv"))==359
    raw_variables=load("r03a2_raw_variables.csv")
    assert len(raw_variables)==2736+142
    assert sum(r["record_type"]=="compiled_variable" for r in raw_variables)==2229
    assert sum(r["record_type"]=="hidden_or_dummy" for r in raw_variables)==507
    assert sum(r["record_type"]=="supercomponent_exposed_variable" for r in raw_variables)==142
    params=load("r03a2_raw_parameters.csv")
    compiled=[r for r in params if r["record_type"]=="compiled_parameter"]
    assert len(compiled)==4142
    assert all(r["raw_descriptor"] and r["raw_data_value"]!="" for r in compiled)


def test_dynamic_states_are_not_algebraic_variables():
    states=load("hydraulic_initial_states.csv")
    variables=load("hydraulic_variables.csv")
    assert sum(r["state_type"]=="dynamic_state" for r in states)==359
    assert sum(r["state_type"]=="initial_condition_parameter" for r in states)==10
    assert any(r["state_or_algebraic"]=="dynamic_state" for r in variables)
    assert any(r["state_or_algebraic"]=="algebraic_or_output" for r in variables)
    assert not all(r["state_or_algebraic"]=="dynamic_state" for r in variables)


def test_sc1_all_instances_and_port_mappings():
    rows=load("r03a2_sc1_mapping.csv")
    instances={r["sc_instance"] for r in rows}
    assert instances==set(audit.SC1_IDS)
    ports=[r for r in rows if r["mapping_type"] in {"port_alias","signal_mapping"}]
    assert len(ports)==47
    assert all(any(r["sc_instance"]==sc and r["mapping_type"]=="signal_mapping"
                   for r in ports) for sc in audit.SC1_IDS)
    assert any(r["internal_submodel"]=="VALVEDYNAMICS0" and r["mapping_type"]=="other"
               for r in rows)
    assert any(r["internal_submodel"]=="HYDVORF0" and r["mapping_type"]=="other"
               for r in rows)
    dir6={r["external_port"]:r["parent_parameter"] for r in ports
          if r["sc_instance"]=="dirvalve_6"}
    assert dir6=={"0":"P","1":"T","2":"B","3":"A","4":"missing"}
    assert any(r["sc_instance"]=="dirvalve_6" and r["parent_parameter"].startswith("P-B ") and
               r["internal_component_id"]=="dirvalve_6/orifice_13"
               for r in rows if r["mapping_type"]=="parameter_mapping")


def test_sc1_comparison_is_per_instance_not_assumed_equal():
    rows=load("r03a2_sc1_instance_comparison.csv")
    assert {r["sc_instance"] for r in rows}==set(audit.SC1_IDS)
    assert all(len([r for r in rows if r["feature"]==feature])==10
               for feature in {r["feature"] for r in rows})
    assert any(r["same_across_all"]=="false" for r in rows)


def test_dirvalve6_parameter_ground_truth():
    rows=load("r03a2_parameter_ground_truth_check.csv")
    assert len(rows)==9
    assert all(r["status"]=="PASS" for r in rows)
    checks={r["parameter_name"]:r for r in rows}
    assert checks["index of hydraulic fluid"]["extracted_value"]=="0"
    assert checks["nominal density"]["extracted_value"]=="850"
    assert checks["nominal density"]["unit"]=="kg/m**3"
    assert checks["nominal kinematic viscosity"]["extracted_value"]=="60"
    assert checks["nominal kinematic viscosity"]["unit"]=="cSt"


def test_validation_channels_bind_real_variables(components):
    variables={(r["component_id"],r["amesim_variable_id"]) for r in
               load("hydraulic_variables.csv")}
    channels=load("r03a2_validation_channels.csv")
    assert channels
    assert all((r["component_id"],r["amesim_variable_id"]) in variables for r in channels)
    assert all(r["availability"]=="available" for r in channels)
    assert all(r["validation_priority"] in {"A","B"} for r in channels)


def test_documentation_index_does_not_substitute_compatible_models():
    rows=load("r03a2_submodel_documentation_index.csv")
    assert {r["submodel"] for r in rows}=={
        r["submodel"] for r in load("hydraulic_components.csv")}
    sc=[r for r in rows if r["submodel"]=="SC_1"]
    assert len(sc)==1 and sc[0]["documentation_status"]=="needs_manual_help_lookup"
    assert all(Path(r["installation_file"]).stem==r["submodel"]
               for r in rows if r["installation_file"]!="missing")


def test_original_model_identity_preserved():
    manifest=json.loads((AUDIT/"r03a2_manifest.json").read_text(encoding="utf-8"))
    assert manifest["start"]==manifest["end"]
    assert manifest["original_unchanged"] is True
    assert audit.file_identity(manifest["model"])==manifest["start"]
    assert manifest["start"]["sha256"]==audit.EXPECTED_SHA


def test_r03a2_rerun_requires_explicit_overwrite():
    with pytest.raises(audit.AuditError,match="R03-A2 output exists"):
        audit.run(ROOT/"qh1_1.ame",AUDIT,Path(r"E:\Simcenter\2021.1\Amesim"))


def test_mechanical_frozen_area_has_no_git_diff():
    result=subprocess.run(
        ["git","diff","--exit-code","--","src/steering_sim/mechanics","configs/mechanics",
         "examples/run_mechanical_demo_interactive.py"],
        cwd=ROOT,check=False,capture_output=True,text=True)
    assert result.returncode==0, result.stdout+result.stderr
