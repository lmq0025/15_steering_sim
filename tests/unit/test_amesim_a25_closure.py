"""R03-A2.5 closure checks; no hydraulic physics implementation."""
import csv
import importlib.util
import json
from collections import Counter
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).parents[2]
AUDIT = ROOT / "configs/hydraulics/amesim_audit"
SPEC = importlib.util.spec_from_file_location(
    "amesim_a25_closure", ROOT / "scripts/hydraulics/amesim_audit/audit_closure.py")
closure = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(closure)


def load(name):
    path = AUDIT / name
    if not path.exists():
        pytest.skip(f"Customer audit artifact unavailable: {name}")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def test_original_model_identity_preserved():
    manifest = json.loads((AUDIT / "r03a25_manifest.json").read_text(encoding="utf-8"))
    assert manifest["start"] == manifest["end"]
    assert manifest["original_unchanged"] is True
    assert manifest["start"]["sha256"] == closure.EXPECTED_SHA
    assert closure.file_identity(ROOT / "qh1_1.ame") == manifest["start"]


def test_all_reference_chains_close_without_cycles():
    rows = load("r03a25_global_parameter_resolution.csv")
    assert len(rows) == 128
    assert Counter(r["reference_type"] for r in rows) == {
        "global_reference": 84, "local_reference": 44}
    assert not any(r["status"] == "CYCLE" for r in rows)
    assert all(r["resolved_value"] not in {"", "missing"}
               for r in rows if r["status"] == "RESOLVED")
    assert all(r["status"] == "RESOLVED" for r in rows)


def test_named_key_references_have_expected_current_values_and_units():
    rows = load("r03a25_global_parameter_resolution.csv")
    expected = {
        "pd": ("10", "cc/rev"), "tps": ("1350", "rev/min"),
        "pid": ("79.7884560802865", "mm"), "rd": ("40.6842894512822", "mm"),
        "sl4": ("0.13", "m"), "sl5": ("0.195", "m"), "sl6": ("0.265", "m"),
    }
    for name, (value, unit) in expected.items():
        selected = [r for r in rows if r["reference_name"] == name]
        assert selected
        assert {(r["resolved_value"], r["unit"]) for r in selected} == {(value, unit)}


def test_scalar_variable_keys_are_unique_and_preserve_base_id():
    rows = load("r03a25_scalar_variable_keys.csv")
    assert len(rows) == 2371
    keys = [r["scalar_variable_key"] for r in rows]
    assert len(keys) == len(set(keys))
    assert all(r["amesim_variable_id"] for r in rows)
    hydraulic = [r for r in rows if r["component_id"] == "hydraulic"
                 and r["amesim_variable_id"] == "15055"]
    assert len(hydraulic) == 5
    assert len({r["scalar_variable_key"] for r in hydraulic}) == 5


def test_scalar_state_keys_are_unique():
    rows = load("r03a25_scalar_state_keys.csv")
    assert len(rows) == 369
    assert len({r["scalar_state_key"] for r in rows}) == len(rows)


def test_validation_channels_are_rekeyed_uniquely():
    rows = load("r03a25_validation_channels_rekeyed.csv")
    assert len(rows) == len(load("r03a2_validation_channels.csv")) == 608
    assert len({r["new_channel_id"] for r in rows}) == len(rows)
    assert all(r["old_channel_id"] and r["scalar_variable_key"] for r in rows)


def test_baseline_validation_set_is_small_and_representative():
    rows = load("r03a25_baseline_validation_channels.csv")
    assert 20 <= len(rows) <= 40
    assert len({r["baseline_channel_id"] for r in rows}) == len(rows)
    assert {"supply", "return", "pump", "valve", "cylinder", "accumulator",
            "pressure_valve"} <= {r["physical_domain"] for r in rows}
    assert sum(r["submodel"].startswith("HL") for r in rows) <= 2
    assert not any(r["variable_name"].startswith(("pn_", "qn_")) for r in rows)


def test_r03b_key_parameters_cover_required_submodels():
    rows = load("r03a25_resolved_key_parameters.csv")
    required = {"PU001", "HJ020", "HJ0022", "HJ021", "SC_1", "VALVEDYNAMICS0",
                "HYDVORF0", "HA001", "RV010"}
    assert required <= {r["submodel"] for r in rows}
    assert all(r["raw_value"] not in {"", "missing"} for r in rows)
    assert not any(r["resolution_status"] == "UNRESOLVED" for r in rows)


def test_valvedynamics0_mode_one_is_defined_from_official_sources():
    rows = load("r03a25_valvedynamics0_definition.csv")
    assert {r["enum_value"] for r in rows} == {"1", "2", "3"}
    mode = next(r for r in rows if r["enum_value"] == "1")
    assert mode["enum_meaning"] == "no (static)"
    assert mode["dynamic_order"] == "0"
    assert mode["uses_time_constant"] == "false"
    assert mode["uses_natural_frequency"] == "false"
    assert mode["uses_damping_ratio"] == "false"
    assert mode["confidence"] == "confirmed"


def test_discrete_state_relevance_does_not_invent_names():
    rows = load("r03a25_discrete_state_relevance.csv")
    assert {r["blocking"] for r in rows} <= {"YES", "NO", "UNKNOWN"}
    assert any(r["submodel"] == "VALVEDYNAMICS0" and r["blocking"] == "NO"
               for r in rows)
    assert not any("state_name=" in r["notes"] for r in rows)


def test_closure_report_contains_all_required_sections():
    text = (AUDIT / "R03A25_closure_report.md").read_text(encoding="utf-8")
    assert all(f"## {index}." in text for index in range(1, 19))
    assert "YES WITH CONDITIONS" in text


def test_no_out_of_scope_hydraulic_physics_module_created():
    """R03-B1 authorizes valve/cylinder files but not the later network models."""
    forbidden = {"Pump.py", "SC1Valve.py", "HydraulicModel.py",
                 "pump.py", "sc1_valve.py", "hydraulic_model.py"}
    existing = {p.name for p in (ROOT / "src/steering_sim/hydraulics").glob("*.py")}
    assert not (forbidden & existing)


def test_mechanical_frozen_area_has_no_git_diff():
    result = subprocess.run(
        ["git", "diff", "--exit-code", "--", "src/steering_sim/mechanics", "configs/mechanics",
         "examples/run_mechanical_demo_interactive.py"], cwd=ROOT,
        check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_r03a25_rerun_requires_explicit_overwrite():
    with pytest.raises(closure.ClosureError, match="R03-A2.5 output exists"):
        closure.run()
