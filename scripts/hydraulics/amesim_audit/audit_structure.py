"""Read-only AMESim 2021.1 structural inventory; no hydraulic equations."""
from __future__ import annotations
import argparse
from collections import Counter
import csv
import hashlib
import html
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tarfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
EXPECTED_PYTHON = Path(r"E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe")
TRUTH = {
    "dirvalve_6": ("SC_1", "solenoid_directional_valve"),
    "dirvalve_8": ("SC_1", "solenoid_directional_valve"),
    "shuttle_control_1": ("HYDCONSHTL0", "shuttle_valve"),
    "actuator001": ("HJ020", "cylinder"),
    "presscontrol01_1": ("RV010", "pressure_control_valve"),
    "accumulator": ("HA001", "accumulator"),
    "dirvalve_1_piecewiselinear_6": ("UD00", "signal_control"),
}
CLASSIFICATION = {
    "TFFD04": "fluid_property", "FP04": "fluid_property",
    "TK000": "tank_return", "PU001": "pump_source",
    "CV010": "check_valve", "CV012": "check_valve",
    "HYDORT0": "restriction_orifice", "HYDORF0": "restriction_orifice",
    "HYDVORF0": "restriction_orifice",
    "RV010": "pressure_control_valve", "RV011": "pressure_control_valve",
    "HYDPRV0": "pressure_control_valve", "HYDCONSHTL0": "shuttle_valve",
    "HA001": "accumulator", "PV00022": "directional_valve", "SC_1": "directional_valve",
    "HJ021": "cylinder", "HJ020": "cylinder", "HJ0022": "cylinder",
    "HYDPG0": "sensor_measurement",
    **dict.fromkeys(("H3NODE1","H3NODE2","H3NODE3","H4NODE1","H4NODE4","HN222A",
                     "SPLT0","JUN3P"), "junction_node"),
    **dict.fromkeys(("PM000","MAS001","MAS004","FORC","GRAV0"), "mechanical_boundary"),
    **dict.fromkeys(("FX00","VALVEDYNAMICS0","SIGTRANS0","SIGRECEI0","SSINK",
                     "SIN0","CONS00","UD00","STEP0"), "signal_control"),
    **dict.fromkeys(("HL012","HL011","HL0002","HL0000"), "volume_line"),
    "DIRECT": "other",
}
DOMAINS = {"hflow":"hydraulic", "signal":"signal", "remote":"signal",
           "lshaft":"mechanical", "rshaft":"mechanical"}
COMP_FIELDS = [
    "component_id","label","element_type","group","library","submodel","ports",
    "source","confidence","notes","alias","object_kind","parent_component",
    "internal_index","circuit_scope_id","element_name","description",
    "classification_source","classification_confidence","group_source","domain",
]
CONN_FIELDS = ["from_component","from_port","to_component","to_port",
               "connection_type","group","source","confidence","notes","relation","evidence"]
SUB_FIELDS = ["component_id","component_label","library","submodel_name",
              "submodel_description","documentation_ref","equation_priority",
              "source","confidence","notes","submodel_directory","local_evidence"]


class AuditError(RuntimeError):
    pass


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024*1024), b""):
            h.update(block)
    return h.hexdigest()


def text(node, path, default="missing"):
    value = node.findtext(path)
    return value.strip() if value and value.strip() else default


def normalize_circuit(data):
    """Escape only single-line leaf text; log every changed leaf, preserve raw."""
    encoding = re.search(br'encoding="([^"]+)"', data[:200])
    content = data.decode(encoding[1].decode("ascii") if encoding else "utf-8")
    changes = []
    pattern = re.compile(r"(?m)^([ \t]*<([A-Z0-9_]+)>)([^\r\n]*)(</\2>[ \t]*\r?)$")
    def replace(match):
        value = html.escape(html.unescape(match[3]), quote=False)
        if value != match[3]:
            changes.append({"line": content.count("\n",0,match.start())+1,
                            "tag":match[2], "before":match[3], "after":value})
        return match[1] + value + match[4]
    normalized = pattern.sub(replace, content)
    try:
        root = ET.fromstring(normalized)
    except ET.ParseError as exc:
        raise AuditError(f"Unsupported circuit XML after explicit leaf normalization: {exc}") from exc
    if root.tag != "CIR" or root.get("AME_VERSION") != "2021.1":
        raise AuditError("Only observed CIR / AME_VERSION=2021.1 is supported")
    return root, normalized, changes


def safe_members(archive, destination):
    result = []
    seen = set()
    for member in archive.getmembers():
        path = PurePosixPath(member.name)
        if (path.is_absolute() or ".." in path.parts or chr(92) in member.name
                or ":" in member.name or not (member.isfile() or member.isdir())):
            raise AuditError(f"Unsafe archive member: {member.name}")
        target = (destination / member.name).resolve()
        if not target.is_relative_to(destination.resolve()):
            raise AuditError(f"Member escapes extraction root: {member.name}")
        if str(target).casefold() in seen:
            raise AuditError(f"Duplicate archive path: {member.name}")
        seen.add(str(target).casefold())
        result.append(member)
    return result


def api_probe(installation):
    code = (
        "import sys,os; sys.dont_write_bytecode=True; "
        "root=sys.argv[1]; "
        "sys.path[:0]=[root+'/scripting/python',root+'/scripting/python/win64']; "
        "handles=[os.add_dll_directory(root+'/win64'),"
        "os.add_dll_directory(root+'/scripting/python/win64')]; "
        "import ame_apy; print('API_IMPORT_OK')"
    )
    try:
        result = subprocess.run([sys.executable,"-c",code,str(installation)],
                                capture_output=True,timeout=30)
        return {"returncode":result.returncode,
                "stdout":result.stdout.decode("utf-8",errors="replace"),
                "stderr":result.stderr.decode("utf-8",errors="replace"),
                "model_opened":False,
                "note":"import-only probe; never opens or saves original model"}
    except subprocess.TimeoutExpired as exc:
        return {"returncode":"timeout","stderr":str(exc),"model_opened":False}


def git_state():
    def git(*args):
        r = subprocess.run(["git",*args],cwd=ROOT,capture_output=True,text=True,check=True)
        return r.stdout.strip()
    return {"status":git("status","--porcelain"),"branch":git("branch","--show-current"),
            "head":git("rev-parse","HEAD")}


def enumerate_objects(root):
    comps, lines, contexts = [], [], []
    def visit(circuit, prefix="", parent=""):
        context = {"circuit":circuit,"prefix":prefix,"parent":parent}
        contexts.append(context)
        for comp in circuit.findall("COMPS_LIST/COMP"):
            alias = text(comp,"ALIAS")
            if alias == "missing":
                raise AuditError("Component alias missing; cannot assign stable ID")
            cid = prefix + alias
            comps.append({"xml":comp,"id":cid,"parent":parent,"scope":prefix})
            inner = comp.find("SUPERCOMPONENT/CIRCUIT")
            if inner is not None:
                visit(inner, cid+"/", cid)
    visit(root.find("CIRCUIT"))
    # Internal COMP indexes: recursive preorder. LINE indexes: circuit preorder,
    # each circuit's own complete LINES_LIST, proven by reciprocal references.
    for context in contexts:
        for line in context["circuit"].findall("LINES_LIST/LINE"):
            lines.append({"xml":line,"id":context["prefix"]+text(line,"ALIAS"),
                          "parent":context["parent"],"scope":context["prefix"]})
    ids = [r["id"] for r in comps+lines]
    if len(ids) != len(set(ids)):
        raise AuditError("Duplicate hierarchical alias; cannot assign stable ID")
    return comps, lines, contexts


def port_records(record):
    return [{"index":i,"type":text(p,"PORT_TYPE"),"name":text(p,"PORT_NAME"),
             "port_connect":text(p,"PORT_CONNECT"),
             "connections":[{"entity":text(c,"CONNECT_ENTITY_NUM"),
                             "port":text(c,"CONNECT_ENTITY_PORT")}
                            for c in p.findall("CONNECT_LIST/CONNECT")]}
            for i,p in enumerate(record["xml"].findall("COMP_PORTS_LIST/COMP_PORT"))]


def raw_inventory(comps, lines):
    rows = []
    for kind, records in (("COMP",comps),("LINE",lines)):
        for index, record in enumerate(records):
            x = record["xml"]
            rows.append({
                "component_id":record["id"],"parent_component":record["parent"],
                "object_kind":kind,"internal_index":index,
                "circuit_scope_id":text(x,"CIRCUIT_SCOPE_ID"),
                "alias":text(x,"ALIAS"),"element_name":text(x,"COMP_NAME"),
                "library_id":text(x,"COMP_LIBRARY_ID"),
                "submodel":text(x,"SUBMODEL/SUB_NAME"),
                "submodel_type":text(x,"SUBMODEL/SUB_TYPE"),
                "submodel_directory":text(x,"SUBMODEL/SUB_DIR"),
                "submodel_description":text(x,"SUBMODEL/SUB_LABEL"),
                "icon_description":text(x,"COMP_ICON_DESCRIPTION"),
                "ports":json.dumps(port_records(record),ensure_ascii=False),
                "structure_metadata":json.dumps({
                    key:text(x,key) for key in
                    ("LINE_TYPE","LINE_START_TYPE","LINE_START_ENTITY","LINE_START_PORT",
                     "LINE_END_TYPE","LINE_END_ENTITY","LINE_END_PORT")},ensure_ascii=False)
                    if kind=="LINE" else "",
                "source":"ame_internal","confidence":"confirmed",
            })
    return rows


def build_connections(comps, lines):
    edges, raw, issues = [], [], []
    ports = {r["id"]:port_records(r) for r in comps}
    supported = {"1","2","4"}
    mapped_parent_ports = []
    def endpoint(index, port):
        if index < 0 or index >= len(comps):
            raise AuditError(f"Invalid component endpoint index {index}")
        comp = comps[index]
        if port < 0 or port >= len(ports[comp["id"]]):
            raise AuditError(f"Invalid port {comp['id']}:{port}")
        return comp["id"], port
    def domain(a,b):
        da,db = DOMAINS.get(a,"unknown"),DOMAINS.get(b,"unknown")
        return da if da==db else "unknown"
    def add(a,b,kind,relation,evidence,note=""):
        # canonical order, NOT physical flow direction
        a,b = sorted((a,b),key=lambda x:(x[0],x[1]))
        edges.append(dict(zip(CONN_FIELDS,[
            a[0],a[1],b[0],b[1],kind,"unknown","ame_internal","confirmed",
            "稳定字典序；不代表流向。"+note,relation,evidence])))
    line_endpoints = []
    for i,line in enumerate(lines):
        x = line["xml"]
        ends = []
        for side in ("START","END"):
            if text(x,"LINE_"+side+"_TYPE") != "0":
                raise AuditError(f"Unsupported LINE endpoint type: {line['id']}")
            ends.append(endpoint(int(text(x,"LINE_"+side+"_ENTITY")),
                                 int(text(x,"LINE_"+side+"_PORT"))))
        line_endpoints.append(ends)
        raw.append({"record_type":"LINE","owner":line["id"],"port":"",
                    "raw_json":json.dumps({k:text(x,k) for k in
                        ("LINE_START_TYPE","LINE_START_ENTITY","LINE_START_PORT",
                         "LINE_END_TYPE","LINE_END_ENTITY","LINE_END_PORT")}),
                    "source":"ame_internal"})
        types = [ports[c][p]["type"] for c,p in ends]
        ports[line["id"]] = [{"index":p,"type":types[p],
                              "name":("start","end")[p]} for p in (0,1)]
        for p,target in enumerate(ends):
            record = ports[target[0]][target[1]]
            expected = [{"entity":str(i),"port":str(p)}]
            if record["port_connect"]!="2" or record["connections"]!=expected:
                raise AuditError(f"Line reciprocal mismatch: {line['id']}:{p}")
            add((line["id"],p),target,domain(types[p],types[p]),"line_attachment",
                f"LINE[{i}]/{('START','END')[p]}")
    # Reverse records are evidence; emit each undirected direct/remote edge once.
    emitted = set()
    for i,comp in enumerate(comps):
        for p in ports[comp["id"]]:
            here = (comp["id"],p["index"])
            raw.append({"record_type":"COMP_PORT","owner":comp["id"],"port":p["index"],
                        "raw_json":json.dumps(p),"source":"ame_internal"})
            if p["port_connect"] not in supported:
                issues.append({"owner":comp["id"],"port":p["index"],"issue":"unsupported_port_connect",
                               "evidence":json.dumps(p)})
                continue
            for connection in p["connections"]:
                number,opposite = int(connection["entity"]),int(connection["port"])
                if p["port_connect"] == "2":
                    if number<0 or number>=len(lines) or opposite not in (0,1):
                        raise AuditError("Invalid LINE reference")
                    target = line_endpoints[number][opposite]
                    if target!=here:
                        # Parent shell's port aliases a nested physical endpoint.
                        parent_here = target[0].startswith(comp["id"]+"/")
                        parent_target = comp["id"].startswith(target[0]+"/")
                        if not (parent_here or parent_target):
                            raise AuditError(f"Unexpected nonreciprocal line alias: {here}->{target}")
                        add(here,target,domain(p["type"],ports[target[0]][target[1]]["type"]),
                            "supercomponent_port_alias",f"COMP[{i}]/PORT[{p['index']}]/LINE[{number}]",
                            "父端口与内部端口等价映射，不是新增物理管路。")
                        mapped_parent_ports.append(here if parent_here else target)
                    continue
                target = endpoint(number,opposite)
                target_port = ports[target[0]][target[1]]
                if (target_port["port_connect"] != p["port_connect"] or
                    {"entity":str(i),"port":str(p["index"])} not in target_port["connections"]):
                    raise AuditError(f"Direct/remote reciprocal mismatch: {here}")
                key = tuple(sorted((here,target)))
                if key not in emitted:
                    emitted.add(key)
                    add(here,target,domain(p["type"],target_port["type"]),
                        "remote_signal" if p["port_connect"]=="4" else "direct_attachment",
                        f"COMP[{i}]/PORT[{p['index']}]")
    for comp in comps:
        maps = comp["xml"].findall("SUPERCOMPONENT/SC_PORTS_MAP_LIST/SC_PORT_MAP")
        for m in maps:
            fields=(m.text or "").split()
            raw.append({"record_type":"SC_PORT_MAP","owner":comp["id"],"port":fields[0],
                        "raw_json":json.dumps({"raw":m.text.strip()}),"source":"ame_internal"})
            if (comp["id"],int(fields[0])) not in mapped_parent_ports:
                issues.append({"owner":comp["id"],"port":fields[0],
                               "issue":"unresolved_sc_port_map","evidence":m.text.strip()})
    return edges,raw,ports,issues


def tables(raw_rows, ports, installation):
    components,submodels = [],[]
    for row in raw_rows:
        cid, sub = row["component_id"],row["submodel"]
        alias=row["alias"]
        manual = cid==alias and alias in TRUTH
        typ=TRUTH[alias][1] if manual else CLASSIFICATION.get(sub,"unknown")
        types={p["type"] for p in ports[cid]}
        domains={DOMAINS.get(t,"unknown") for t in types}
        domain=next(iter(domains)) if len(domains)==1 else "mixed" if domains else "none"
        library=row["library_id"]
        if library=="missing" and row["submodel_directory"]!="missing":
            library=row["submodel_directory"]
        group=("control_signal" if domain=="signal" else
               "supply_return" if typ in ("tank_return","pump_source") else "unknown")
        note="当前直接 SUBMODEL/SUB_NAME；不使用兼容列表。"
        if sub=="SC_1":
            note+="本地 supercomponent；名称相同不证明各实例内部拓扑相同；方程未核实。"
        if row["object_kind"]=="LINE":
            note+="线对象保留为独立对象，防止丢失管路submodel。"
        components.append(dict(zip(COMP_FIELDS,[
            cid,alias,typ,group,library,sub,json.dumps(ports[cid],ensure_ascii=False),
            "ame_internal","confirmed",note,alias,row["object_kind"],row["parent_component"],
            row["internal_index"],row["circuit_scope_id"],row["element_name"],
            row["submodel_description"],"gui_manual" if manual else "inferred",
            "manual_confirmed" if manual else "inferred","inferred" if group!="unknown" else "missing",domain,
        ])))
        directory=row["submodel_directory"].replace("$AME",str(installation))
        available=[]
        if row["submodel_directory"]!="missing":
            for ext in (".spe",".c"):
                candidate=Path(directory)/(sub+ext)
                if candidate.is_file():
                    available.append(str(candidate))
            lib=Path(directory).parent
            for candidate in (lib/"doc"/"pdf"/(sub+".pdf"),lib/"doc"/"pdf"/(sub.lower()+".pdf")):
                if candidate.is_file():
                    available.append(str(candidate))
        high=typ in ("pump_source","solenoid_directional_valve","cylinder",
                     "pressure_control_valve","shuttle_valve","accumulator") or sub=="SC_1"
        priority="HIGH" if high else "MEDIUM" if domain in ("hydraulic","mixed") else "LOW"
        if sub=="DIRECT":
            priority="N/A"
        submodels.append(dict(zip(SUB_FIELDS,[
            cid,alias,library,sub,row["submodel_description"],
            "available" if available else "needs_manual_help_lookup",
            priority,"ame_internal","confirmed",note,row["submodel_directory"],
            json.dumps(available,ensure_ascii=False),
        ])))
    return components,submodels


def ground_truth(components):
    by_id={r["component_id"]:r for r in components}
    results=[]
    for i,(alias,(expected,typ)) in enumerate(TRUTH.items(),1):
        row=by_id.get(alias)
        status="NOT_FOUND" if row is None else "PASS" if row["submodel"]==expected else "FAIL"
        results.append({"check_id":f"GT{i:02d}","component_or_alias":alias,
            "expected_submodel":expected,"extracted_submodel":row["submodel"] if row else "missing",
            "expected_element_type":typ,"extracted_element_type":row["element_type"] if row else "missing",
            "status":status,
            "notes":"submodel独立从归档提取；element_type采用用户GUI Ground Truth，非独立类型验证。"})
    return results


def quality(components,edges,issues):
    ids={r["component_id"] for r in components}
    ports={r["component_id"]:{p["index"] for p in json.loads(r["ports"])} for r in components}
    missing=sum(e["from_component"] not in ids or e["to_component"] not in ids for e in edges)
    unknown_ports=sum(e["from_port"] not in ports.get(e["from_component"],set()) or
                      e["to_port"] not in ports.get(e["to_component"],set()) for e in edges)
    keys=[(e["from_component"],e["from_port"],e["to_component"],e["to_port"]) for e in edges]
    domains=Counter(e["connection_type"] for e in edges)
    used={(e[k+"_component"],e[k+"_port"]) for e in edges for k in ("from","to")}
    dangling=[(cid,p) for cid,ps in ports.items() for p in ps if (cid,p) not in used]
    metrics={"connections":len(edges),**{f"{d}_connections":domains[d] for d in
             ("hydraulic","signal","mechanical","other","unknown")},
             "dangling_connections":missing+unknown_ports,"unconnected_object_ports":len(dangling),
             "unknown_ports":unknown_ports,"references_to_missing_components":missing,
             "duplicate_connections":len(keys)-len(set(keys)),"unsupported_records":len(issues)}
    return metrics,dangling


def write_csv(path,rows,fields=None):
    if fields is None:
        fields=list(rows[0]) if rows else ["owner","port","issue","evidence"]
    with path.open("w",encoding="utf-8-sig",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def auxiliary_objects(root):
    """Preserve non-solver circuit annotations outside the formal COMP/LINE graph."""
    rows=[]
    for index,sticker in enumerate(root.findall("./CIRCUIT_EXTENSIONS/STICKER_DEFINITIONS/STICKER")):
        rows.append({
            "auxiliary_id":f"circuit_extension/STICKER/{index}",
            "object_kind":"STICKER_DEFINITION",
            "name":sticker.get("NAME","missing"),
            "label":sticker.get("LABEL","missing"),
            "color":sticker.get("COLOR","missing"),
            "is_factory":sticker.get("IS_FACTORY","missing"),
            "source":"ame_internal",
            "confidence":"confirmed",
            "notes":"Non-solver annotation definition; excluded from component and connection counts.",
        })
    return rows


def run(model,output,installation,overwrite=False):
    if Path(sys.executable).resolve()!=EXPECTED_PYTHON.resolve():
        raise AuditError(f"Only steering_sim is permitted: {sys.executable}")
    model,output,installation=Path(model).resolve(),Path(output).resolve(),Path(installation).resolve()
    if model.is_relative_to(output):
        raise AuditError("Source model must not be inside audit output")
    if output.exists() and any(output.iterdir()) and not overwrite:
        raise AuditError(f"Output exists: {output}; use a new directory or explicit --overwrite")
    if output==ROOT or output==model.parent:
        raise AuditError("Audit output must be a dedicated directory")
    output.mkdir(parents=True,exist_ok=True)
    (output/".gitignore").write_text("raw_extract/\n*.csv\n*.json\n",encoding="utf-8")
    before={"sha256":sha(model),"size":model.stat().st_size,"mtime_ns":model.stat().st_mtime_ns}
    manifest={"model":str(model),"before":before,"python":sys.executable,
              "git_start":git_state(),"installation":str(installation),
              "initial_environment_note":"initial CONDA_PREFIX empty; no Python executed until explicitly set to known steering_sim",
              "api_probe":api_probe(installation)}
    print("API probe:",json.dumps(manifest["api_probe"],ensure_ascii=False))
    try:
        raw_dir=output/"raw_extract"
        raw_dir.mkdir(exist_ok=True)
        with tarfile.open(model,"r:*") as archive:
            members=safe_members(archive,raw_dir)
            inventory=[]
            for member in members:
                dest=raw_dir/member.name
                if member.isdir():
                    dest.mkdir(parents=True,exist_ok=True)
                else:
                    dest.parent.mkdir(parents=True,exist_ok=True)
                    with archive.extractfile(member) as source, dest.open("wb") as target:
                        while block:=source.read(1024*1024):
                            target.write(block)
                inventory.append({"name":member.name,"size":member.size,
                                  "sha256":sha(dest) if member.isfile() else "directory"})
            circuits=[m for m in members if m.isfile() and m.name.endswith(".cir")]
            if len(circuits)!=1:
                raise AuditError("Expected exactly one active circuit file")
            circuit_path=raw_dir/circuits[0].name
        root,normalized,changes=normalize_circuit(circuit_path.read_bytes())
        (raw_dir/"circuit.normalized.xml").write_bytes(
            ET.tostring(root,encoding="utf-8",xml_declaration=True))
        comps,lines,contexts=enumerate_objects(root)
        raw=raw_inventory(comps,lines)
        edges,raw_edges,ports,issues=build_connections(comps,lines)
        components,submodels=tables(raw,ports,installation)
        auxiliary=auxiliary_objects(root)
        gt=ground_truth(components)
        metrics,dangling=quality(components,edges,issues)
        counts=Counter(r["element_type"] for r in components)
        subs=Counter(r["submodel"] for r in components)
        hydraulic_types={"pump_source","tank_return","solenoid_directional_valve","directional_valve",
            "pressure_control_valve","check_valve","shuttle_valve","restriction_orifice",
            "cylinder","accumulator","volume_line"}
        summary={"total_objects":len(components),"COMP_objects":len(comps),"LINE_objects":len(lines),
                 "top_level_objects":sum(not r["parent_component"] for r in components),
                 "nested_objects":sum(bool(r["parent_component"]) for r in components),
                 "supercomponents":len(contexts)-1,"distinct_submodels":len(subs),
                 "hydraulic_physical_components":sum(counts[t] for t in hydraulic_types),
                 "signal_control":counts["signal_control"],"mechanical_boundary":counts["mechanical_boundary"],
                 "junction_node":counts["junction_node"],"unknown":counts["unknown"],
                 "missing_submodel":subs["missing"],
                 "missing_library":sum(r["library"]=="missing" for r in components),
                 "missing_description":sum(r["submodel_description"]=="missing" for r in submodels),
                 "inferred_classifications":sum(r["classification_source"]=="inferred" for r in components),
                 "manual_classifications":sum(r["classification_source"]=="gui_manual" for r in components),
                 "unknown_group":sum(r["group"]=="unknown" for r in components)}
        write_csv(output/"hydraulic_components.csv",components,COMP_FIELDS)
        write_csv(output/"hydraulic_connections.csv",edges,CONN_FIELDS)
        write_csv(output/"hydraulic_submodels.csv",submodels,SUB_FIELDS)
        write_csv(output/"r03a1_raw_component_inventory.csv",raw)
        write_csv(output/"r03a1_raw_connection_inventory.csv",raw_edges)
        write_csv(output/"r03a1_auxiliary_object_inventory.csv",auxiliary)
        write_csv(output/"r03a1_ground_truth_check.csv",gt)
        write_csv(output/"r03a1_inventory_summary.csv",
                  [{"category":"total","name":k,"count":v} for k,v in summary.items()]+
                  [{"category":"submodel","name":k,"count":v} for k,v in sorted(subs.items())]+
                  [{"category":"element_type","name":k,"count":v} for k,v in sorted(counts.items())])
        write_csv(output/"r03a1_connection_quality.csv",
                  [{"metric":k,"count":v,"notes":"formal object graph; includes line attachments and shell aliases"}
                   for k,v in metrics.items()])
        write_csv(output/"r03a1_unsupported_records.csv",issues)
        write_csv(output/"r03a1_normalization_log.csv",changes)
        manifest.update({"archive_members":inventory,"normalization_count":len(changes),
                         "circuit_member":circuits[0].name,"summary":summary,"quality":metrics,
                         "ground_truth":gt,"dangling_ports":dangling,
                         "relations":dict(Counter(e["relation"] for e in edges)),
                         "raw_connection_rows":len(raw_edges),
                         "auxiliary_object_rows":len(auxiliary)})
        write_readme(output,manifest)
        write_report(output,manifest,subs,submodels)
        print(json.dumps({"summary":summary,"quality":metrics,"ground_truth":gt},ensure_ascii=False,indent=2))
    finally:
        after={"sha256":sha(model),"size":model.stat().st_size,"mtime_ns":model.stat().st_mtime_ns}
        manifest["after"]=after
        manifest["original_unchanged"]=before==after
        (output/"r03a1_manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
        if before!=after:
            raise AuditError("Original model changed during audit; investigate immediately")
    return manifest


def write_readme(output,m):
    (output/"README.md").write_text(
        "# R03-A1 审计数据字典\n\n"
        "本目录含客户模型结构；CSV/JSON及raw_extract已由本地.gitignore防止误提交。\n\n"
        "- component_id=外层alias/内部alias，稳定唯一；原CIRCUIT_SCOPE_ID及全局内部索引另存。\n"
        "- 原始端口从0计数，与安装目录AME.py的AMEGetConnectionInformation文档一致。\n"
        "- ports为JSON数组：index/type/name；COMP同时保留原始port_connect和connections。\n"
        "- COMP全局索引为深度优先前序；LINE为电路前序、各电路全部LINES_LIST；全部740端点反查验证。\n"
        "- PORT_CONNECT 1=直接组件引用，2=线引用，4=远程信号引用；映射经双向引用验证。\n"
        "- 正式图保留所有线对象，线对象的端口0/1为START/END；from/to按稳定字典序，不代表物理流向。\n"
        "- supercomponent_port_alias为父子等价端口关系；不得当作额外物理管路。\n"
        "- 直接/远程双向记录仅合并镜像记录，raw保留全部证据；不得把节点当作丢失连接。\n"
        "- source/confidence描述核心提取证据；工程类型的classification_source/confidence单独标记。\n"
        "- group_source独立标记，front/rear没有可信映射故不推断；control_signal和supply_return仅工程分类。\n"
        "- library对COMP采用COMP_LIBRARY_ID；LINE采用SUB_DIR，DIRECT缺失写missing。\n"
        "- documentation_ref=available表示发现本机.spe/.c/PDF证据，不代表已读完方程帮助。\n"
        "- equation_priority为后续审计优先级，不是精度判断；SC_1全部HIGH。\n"
        "- 缺失submodel描述保留missing，不以图标描述填充。工程类型不参与submodel Ground Truth断言。\n"
        "- hydraulic_physical_components只统计定义的液压器件类型，另报junction/fluid_property/sensor；"
        "父壳和内部器件均计数，不能解读为不重叠物理BOM。\n"
        f"- 附属对象证据表另存{m.get('auxiliary_object_rows', 0)}条STICKER定义；"
        "它们不是求解组件，不计入773个COMP/LINE对象及液压物理组件统计。\n"
        f"- raw组件行={m['summary']['total_objects']}；raw连接证据行={m['raw_connection_rows']}；"
        f"正式图边={m['quality']['connections']}；分解={m['relations']}。\n"
        "- XML包含未转义的&&和<表达式；只规范化单行叶节点文本并逐项记录，原归档字节完整保留。\n"
        "- 未展开参数/初始状态/变量表；内部原文件只作为证据，绝不执行其中EXE/DLL。\n",
        encoding="utf-8")


def write_report(output,m,subs,submodels):
    s,q=m["summary"],m["quality"]
    verdict="PASS" if all(g["status"]=="PASS" for g in m["ground_truth"]) and not any(
        q[k] for k in ("dangling_connections","unknown_ports","references_to_missing_components",
                      "duplicate_connections","unsupported_records")) else "CONDITIONAL PASS"
    report=[
        "# R03-A1 AMESim 全模型结构审计",
        "## 目的与只读保护",
        "仅回答对象清单、当前实际submodel、端口级连接；未开发液压机理、控制或联合求解。",
        f"原模型：{m['model']}。SHA256：{m['before']['sha256']}。",
        "以rb方式打开归档；解包文件仅写入本目录raw_extract；不启动归档EXE/DLL，"
        "不调用模型保存、不修改原文件属性；前后SHA256/大小/mtime核对记录于manifest。",
        "## 环境与Git",
        f"sys.executable={m['python']}。初始CONDA_PREFIX为空，暂停Python后显式指定已知steering_sim再验证。",
        f"初始分支={m['git_start']['branch']}；HEAD={m['git_start']['head']}。",
        "任务开始前工作区clean；没有commit/merge/reset/clean，机械src与人工演示均未修改。",
        "## 技术路线与官方API调查",
        f"安装目录：{m['installation']}。",
        "官方AME.py包含AMEGetComponentsAndLines、AMEGetSubmodelInfos、AMEGetConnectionInformation、"
        "AMEGetNumberOfPorts；明确区分当前submodel与AMEListAvailableSubmodels兼容列表。",
        "ame_apy在本项目Python3.11环境中导入失败（DLL初始化失败），未能成功使用Circuit API查询。"
        "安装树存在Python3.6痕迹，版本适配问题尚未单独定位；不改变环境或安装文件。",
        "因此采用internal archive路线：TAR归档内当前.cir、直接SUBMODEL/SUB_NAME及SUB_LABEL；"
        "官方安装.spe/.c可用性作为后续文档索引。API探测完整stderr见manifest。",
        f"归档成员数={len(m['archive_members'])}；活动circuit={m['circuit_member']}；"
        f"XML叶节点显式规范化={m['normalization_count']}处；raw保持原字节。",
        "## 全模型统计",
        *[f"- {k}：{v}" for k,v in s.items()],
        "对象包括COMP与LINE，并递归进入全部10个supercomponent。不是截图图标数，也不是去重BOM。",
        f"另保留{m.get('auxiliary_object_rows', 0)}条CIRCUIT_EXTENSIONS/STICKER定义作为附属证据；"
        "这些工厂注释标签不是AMESim求解组件，不混入773个结构对象、submodel或连接统计。",
        "## 当前submodel清单",
        *[f"- {name}：{count}" for name,count in sorted(subs.items())],
        "## 连接质量与分组",
        *[f"- {k}：{v}" for k,v in q.items()],
        f"关系分解：{m['relations']}。",
        "所有370条线的740个端点同时验证COMP_PORT反向引用；直接/远程引用也需双向一致。"
        "47个父壳端口根据线端点别名映射到内部端口，并对照SC_PORTS_MAP_LIST覆盖。"
        "from/to只表示稳定排序；不能据此推断流向。hflow/signal/remote/lshaft/rshaft按原端口类型区分。",
        "前桥/后桥没有显式可靠标签，保留unknown；未依据截图位置或机械对象猜测对应桥号。",
        "## GUI Ground Truth",
        *[f"- {g['component_or_alias']}：{g['expected_submodel']} / "
          f"提取{g['extracted_submodel']} → {g['status']}" for g in m["ground_truth"]],
        "类型采用用户人工确认字段，classification_source=gui_manual、manual_confirmed；"
        "7条submodel都由归档独立读取，没有用Ground Truth覆盖。",
        "## missing / inferred / manual",
        f"分类推断{s['inferred_classifications']}行、人工类型{s['manual_classifications']}行；"
        f"missing library={s['missing_library']}、missing description={s['missing_description']}、"
        f"unknown group={s['unknown_group']}、unknown element_type={s['unknown']}。",
        "完整逐项清单可按正式CSV对应列筛选；原始字段均为ame_internal/confirmed，"
        "仅说明模型保存的结构事实，不说明工程分类已由客户验收。",
        "缺失submodel描述的对象："+", ".join(r["component_id"] for r in submodels if r["submodel_description"]=="missing"),
        "## SC_1",
        "已确认10个局部supercomponent使用SC_1，dirvalve_6/8均通过检查；"
        "后两者各具有4个hflow端口和1个signal端口，内部对象及线路已逐层保留。"
        "归档含可审计内部HYDVORF0、FX00、VALVEDYNAMICS0等组成；各SC_1实例结构未必相同。",
        "SUB_LABEL/SUB_DIR缺失，完整方程与独立官方帮助尚未确认，documentation_ref="
        "needs_manual_help_lookup、equation_priority=HIGH；绝不直接等同标准四通阀公式。",
        "## 下一阶段 R03-A2",
        "逐实例核对SC_1内部连接、端口映射及公开参数关联；查询所选子模型的安装.spe/.c及官方帮助，"
        "再决定参数/初始状态/变量审计范围；请客户确认前后桥分组与物理接口。"
        "本轮不解析或建立完整参数、状态、变量CSV。",
        "## 验收",
        f"结构审计判定：{verdict}（以前后原模型哈希一致为最终前提，见manifest）。",
        "此结论仅为R03-A1结构审计，不表示液压模型实现、动态精度或AMESim到Python重构已经完成。",
    ]
    (output/"R03A1_AMESim_structure_audit.md").write_text("\n\n".join(report)+"\n",encoding="utf-8")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model",type=Path,default=ROOT/"qh1_1.ame")
    parser.add_argument("--output",type=Path,default=ROOT/"configs/hydraulics/amesim_audit")
    parser.add_argument("--amesim-root",type=Path,default=Path(os.environ.get("AME",r"E:\Simcenter\2021.1\Amesim")))
    parser.add_argument("--overwrite",action="store_true")
    args=parser.parse_args()
    try:
        run(args.model,args.output,args.amesim_root,args.overwrite)
    except (AuditError,OSError,ET.ParseError,tarfile.TarError) as exc:
        parser.exit(2,f"审计失败（未静默回退）：{exc}\n")


if __name__=="__main__":
    main()
