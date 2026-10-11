import csv
from pathlib import Path


def test_parameter_mapping_has_only_allowed_source_types():
    path = Path("hydraulic_audit_lumped/30A_lumped_parameter_mapping.csv")
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    assert rows
    assert {r["source_type"] for r in rows} <= {"AMESIM_EXACT", "PHYSICS_DERIVED", "AMESIM_IDENTIFIED", "MISSING"}
    assert all(r["source_alias"] and r["used_in_equation"] for r in rows)


def test_state_and_pipe_count(model):
    assert model.state_count == 16
    assert all("pipe" not in c.name for c in model.channels)
