"""Tests only for the read-only AMESim audit tooling."""
import csv
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import xml.etree.ElementTree as ET

import pytest

ROOT=Path(__file__).parents[2]
SPEC=importlib.util.spec_from_file_location(
    "amesim_structure_audit", ROOT/"scripts/hydraulics/amesim_audit/audit_structure.py")
audit=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)
OUTPUT=ROOT/"configs/hydraulics/amesim_audit"


@pytest.fixture(scope="module")
def data():
    if not (OUTPUT/"hydraulic_components.csv").exists():
        pytest.skip("Customer audit artifacts supplied outside Git")
    def read(name):
        with (OUTPUT/name).open(encoding="utf-8-sig",newline="") as stream:
            return list(csv.DictReader(stream))
    return read


def test_component_ids_unique_and_hierarchical(data):
    rows=data("hydraulic_components.csv")
    ids=[r["component_id"] for r in rows]
    assert len(ids)==len(set(ids))==773
    assert len([r for r in rows if r["object_kind"]=="COMP"])==403
    assert len([r for r in rows if r["object_kind"]=="LINE"])==370
    for row in rows:
        if row["parent_component"]:
            assert row["parent_component"] in ids
            assert row["component_id"].startswith(row["parent_component"]+"/")


def test_selected_submodel_ground_truth_not_compatible_list(data):
    rows=data("hydraulic_components.csv")
    checks=audit.ground_truth(rows)
    assert len(checks)==7
    assert all(c["status"]=="PASS" for c in checks)
    relief=next(r for r in rows if r["component_id"]=="presscontrol01_1")
    assert relief["submodel"]=="RV010"
    assert next(r for r in rows if r["component_id"]=="dirvalve_1_piecewiselinear_6")["element_type"]=="signal_control"
    mutated=[dict(r) for r in rows]
    next(r for r in mutated if r["component_id"]=="dirvalve_6")["submodel"]="WRONG"
    assert audit.ground_truth(mutated)[0]["status"]=="FAIL"


def test_connection_endpoints_domains_and_duplicates(data):
    comps=data("hydraulic_components.csv")
    ports={r["component_id"]:{p["index"]:p for p in json.loads(r["ports"])} for r in comps}
    edges=data("hydraulic_connections.csv")
    keys=[]
    for e in edges:
        a,b=e["from_component"],e["to_component"]
        ap,bp=int(e["from_port"]),int(e["to_port"])
        assert a in ports and b in ports
        assert ap in ports[a] and bp in ports[b]
        assert audit.DOMAINS[ports[a][ap]["type"]]==e["connection_type"]
        assert audit.DOMAINS[ports[b][bp]["type"]]==e["connection_type"]
        keys.append((a,ap,b,bp))
    assert len(keys)==len(set(keys))==878
    assert sum(e["relation"]=="supercomponent_port_alias" for e in edges)==47
    assert sum(e["relation"]=="remote_signal" for e in edges)==10


def test_csv_schema_provenance_and_confidence(data):
    for name,fields in (("hydraulic_components.csv",audit.COMP_FIELDS),
                        ("hydraulic_connections.csv",audit.CONN_FIELDS),
                        ("hydraulic_submodels.csv",audit.SUB_FIELDS)):
        rows=data(name)
        assert list(rows[0])==fields
        for r in rows:
            assert r["source"] in {"circuit_api","ame_internal","amesim_report","gui_manual","inferred","missing"}
            assert r["confidence"] in {"confirmed","manual_confirmed","inferred","missing"}
    for r in data("hydraulic_submodels.csv"):
        if r["submodel_name"]=="SC_1":
            assert r["equation_priority"]=="HIGH"
            assert r["submodel_description"]=="missing"


def test_raw_to_formal_explainable_counts(data):
    assert len(data("r03a1_raw_component_inventory.csv"))==len(data("hydraulic_components.csv"))
    raw=data("r03a1_raw_connection_inventory.csv")
    assert len(raw)==969+370+47
    assert sum(r["record_type"]=="COMP_PORT" for r in raw)==969
    assert len(data("hydraulic_connections.csv"))==370*2+162//2+20//2+47


def test_auxiliary_annotations_are_separate_from_solver_objects(data):
    rows=data("r03a1_auxiliary_object_inventory.csv")
    assert len(rows)==7
    assert all(r["object_kind"]=="STICKER_DEFINITION" for r in rows)
    assert all(r["source"]=="ame_internal" and r["confidence"]=="confirmed" for r in rows)
    assert len(data("hydraulic_components.csv"))==773


def test_original_hash_size_and_mtime_preserved():
    if not (OUTPUT/"r03a1_manifest.json").exists():
        pytest.skip("Audit artifacts unavailable")
    m=json.loads((OUTPUT/"r03a1_manifest.json").read_text(encoding="utf-8"))
    assert m["before"]==m["after"]
    assert m["original_unchanged"] is True
    assert audit.sha(m["model"])==m["before"]["sha256"]


def test_explicit_xml_normalization_preserves_expressions():
    raw=b'<CIR AME_VERSION="2021.1">\r\n <VALUE>(x<=0)&&(y>1)</VALUE>\r\n</CIR>'
    root,normalized,changes=audit.normalize_circuit(raw)
    assert root.findtext("VALUE")=="(x<=0)&&(y>1)"
    assert len(changes)==1
    assert changes[0]["line"]==2
    assert b"(x<=0)&&(y>1)" in raw
    with pytest.raises(audit.AuditError,match="Unsupported"):
        audit.normalize_circuit(b'<CIR AME_VERSION="2021.1"><broken></CIR>')


def test_unsupported_version_is_explicit():
    with pytest.raises(audit.AuditError,match="Only observed"):
        audit.normalize_circuit(b'<CIR AME_VERSION="9999"/>')


def test_archive_path_traversal_rejected():
    buffer=io.BytesIO()
    with tarfile.open(fileobj=buffer,mode="w") as t:
        info=tarfile.TarInfo("../escape.txt")
        info.size=1
        t.addfile(info,io.BytesIO(b"x"))
    buffer.seek(0)
    with tarfile.open(fileobj=buffer,mode="r") as t:
        with pytest.raises(audit.AuditError,match="Unsafe"):
            audit.safe_members(t,OUTPUT/"raw_extract")


def test_rerun_requires_explicit_overwrite():
    if not OUTPUT.exists():
        pytest.skip("Audit artifacts unavailable")
    with pytest.raises(audit.AuditError,match="Output exists"):
        audit.run(ROOT/"qh1_1.ame",OUTPUT,Path(r"E:\Simcenter\2021.1\Amesim"))


def test_duplicate_aliases_rejected():
    root=ET.fromstring('<CIR><CIRCUIT><COMPS_LIST><COMP><ALIAS>a</ALIAS></COMP>'
                       '<COMP><ALIAS>a</ALIAS></COMP></COMPS_LIST></CIRCUIT></CIR>')
    with pytest.raises(audit.AuditError,match="Duplicate"):
        audit.enumerate_objects(root)


def test_normalized_evidence_is_valid_xml():
    path=OUTPUT/"raw_extract/circuit.normalized.xml"
    if not path.exists():
        pytest.skip("Audit artifacts unavailable")
    root=ET.parse(path).getroot()
    assert root.tag=="CIR"
    assert root.get("AME_VERSION")=="2021.1"
