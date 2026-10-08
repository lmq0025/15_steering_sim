import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts" / "hydraulics"))

from run_phase2c2a import binding_audit
from steering_sim.hydraulics.solver import FastHydraulicModel


def test_pressure_control_ports_match_ir_v3():
    rows = binding_audit(FastHydraulicModel.from_ir(ROOT / "hydraulic_audit"))
    assert rows
    assert all(row["match"] == "PASS" for row in rows)

