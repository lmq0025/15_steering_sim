import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_accepted_optimization_has_zero_physics_regression():
    with (ROOT / "hydraulic_audit" / "19G_performance_optimization_steps.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = {row["optimization_stage"]: row for row in csv.DictReader(stream)}
    accepted = rows["ALGEBRAIC_CACHE"]
    assert accepted["physics_regression"] == "PASS"
    assert float(accepted["max_normalized_error"]) <= 1.0e-3
    assert float(accepted["actual_algebraic_solves"]) < float(accepted["algebraic_calls"])

