import csv
from pathlib import Path

from steering_sim.hydraulics.assembly import HydraulicSystem


ROOT = Path(__file__).resolve().parents[3]


def test_reduction_map_covers_every_physical_line_and_preserves_volume():
    with (ROOT / "hydraulic_audit" / "17G_fast_line_reduction_map.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 65
    assert all(row["original_volume"] == row["fast_equivalent_volume"] for row in rows)
    assert sum(int(row["original_state_count"]) for row in rows) == 323


def test_fast_has_one_or_two_pressure_states_per_physical_line():
    system = HydraulicSystem.from_ir(ROOT / "hydraulic_audit", "fast")
    line_states = [s for s in system.states if s.submodel in {"HL0000", "HL0002", "HL011", "HL012"}]
    assert 65 <= len(line_states) < 323
    counts = {}
    for state in line_states:
        counts[state.instance] = counts.get(state.instance, 0) + 1
    assert len(counts) == 65
    assert set(counts.values()) <= {1, 2}
