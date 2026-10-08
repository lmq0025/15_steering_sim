from pathlib import Path

from steering_sim.hydraulics.graph import load_ir_v2


ROOT = Path(__file__).resolve().parents[2]


def test_every_power_port_references_existing_junction():
    ir = load_ir_v2(ROOT / "hydraulic_audit")
    ids = {j["junction_id"] for j in ir.junctions}
    assert ir.ports
    assert all(p["connected_junction"] in ids for p in ir.ports)


def test_ir_contains_hydraulic_translation_and_rotation_junctions():
    ir = load_ir_v2(ROOT / "hydraulic_audit")
    domains = {j["domain"] for j in ir.junctions}
    assert {"hydraulic", "translation", "rotation"} <= domains
