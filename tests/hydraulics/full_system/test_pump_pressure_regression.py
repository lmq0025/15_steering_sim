import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_c2a_keeps_pump_displacement_flow_and_state_contract():
    result = json.loads((ROOT / "hydraulic_audit" / "21O_phase2C2A_results.json").read_text())
    assert result["regression"]["pump_flow_still_good"]
    assert result["regression"]["states_unchanged"]
    assert result["fast_states"] == 109

