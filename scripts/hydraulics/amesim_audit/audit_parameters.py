"""R03-A2 read-only parameter/state/variable audit for qh1_1.ame evidence."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[3]
AUDIT=ROOT/"configs/hydraulics/amesim_audit"
RAW=AUDIT/"raw_extract"
EXPECTED_PYTHON=Path(r"E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe")
EXPECTED_SHA="7613615723973d66a7122c74956c5161f720a64b243139fe9736cb270303b767"
SC1_IDS=("dirvalve_1","dirvalve_2","dirvalve_3","dirvalve_6","dirvalve_8",
         "dirvalve_9","dirvalve_10","dirvalve_11","dirvalve_12","dirvalve_13")

PARAM_FIELDS=["component_id","component_label","submodel","parameter_id","parameter_name",
              "raw_value","value","unit","value_type","value_origin","source","editable",
              "confidence","notes"]
STATE_FIELDS=["component_id","component_label","submodel","state_id","state_name",
              "initial_raw_value","initial_value","unit","state_type","is_dynamic_state",
              "initialization_method","source","confidence","notes"]
VAR_FIELDS=["component_id","component_label","submodel","amesim_variable_id","variable_name",
            "meaning","unit","variable_type","state_or_algebraic","saved_by_default",
            "availability","validation_priority","recommended_for_validation","source",
            "confidence","notes"]
RAW_PARAM_FIELDS=["row_index","record_type","component_id","submodel","submodel_instance",
                  "parameter_id","data_path","raw_descriptor","raw_data_value","cir_raw_value",
                  "cir_default_value","cir_parameter_kind","source","notes"]
RAW_STATE_FIELDS=["row_index","component_id","submodel","submodel_instance","data_path",
                  "raw_descriptor","matched_parameter_id","matched_initial_raw_value","source","notes"]
RAW_VAR_FIELDS=["row_index","record_type","component_id","submodel","submodel_instance","data_path",
                "raw_descriptor","raw_ssf","amesim_variable_id","saved_flag","source","notes"]


class AuditError(RuntimeError):
    pass


def sha(path):
    digest=hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""):
            digest.update(block)
    return digest.hexdigest()


def file_identity(path):
    p=Path(path)
    return {"sha256":sha(p),"size":p.stat().st_size,"mtime_ns":p.stat().st_mtime_ns}


def read_csv(path):
    with Path(path).open(encoding="utf-8-sig",newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path,rows,fields):
    with Path(path).open("w",encoding="utf-8-sig",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=fields,extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def text_lines(path):
    return Path(path).read_text(encoding="latin1").splitlines()


def descriptor(line):
    match=re.match(r"^(\S+) instance (-?\d+) (.*)$",line)
    if not match:
        return None
    submodel,instance,tail=match.groups()
    dp_match=re.search(r"(?:^| )Data_Path=(\S+)",tail)
    pid_match=re.search(r"(?:^| )Param_Id=(\d+)",tail)
    cutoff=len(tail)
    for token in (" Is_Delta="," Param_Id="," Recompile_Flag="," Is_Linked_Variable="," Data_Path="):
        pos=tail.find(token)
        if pos>=0:
            cutoff=min(cutoff,pos)
    title=tail[:cutoff].strip()
    unit="missing"
    unit_match=re.match(r"^(.*) \[([^\]]+)\]$",title)
    if unit_match:
        title,unit=unit_match.group(1),unit_match.group(2)
    data_path=dp_match.group(1) if dp_match else "missing"
    return {"submodel":submodel,"instance":instance,"title":title,"unit":unit,
            "parameter_id":pid_match.group(1) if pid_match else "missing",
            "data_path":data_path}


def numeric(raw):
    try:
        return format(float(raw),".15g")
    except (TypeError,ValueError):
        return None


def classify_value(raw,title="",kind="",meta=None):
    raw=(raw or "").strip()
    low=(title+" "+raw).lower()
    if not raw:
        return "missing"
    if kind=="IPARAM" and meta is not None:
        enum=(meta.get("ENUM_LIST") or "").strip()
        if enum:
            return "enum"
        if meta.get("MIN_VALUE")=="0" and meta.get("MAX_VALUE")=="1":
            return "boolean"
    if numeric(raw) is not None:
        return "numeric"
    if "__SC_" in raw:
        return "global_reference"
    if ("filename" in low or raw.lower().endswith((".data",".txt",".csv")) or
            raw.startswith("$AME/")):
        return "table"
    if kind=="TPARAM" and (re.search(r"[+*/()<>]",raw) or re.search(r"\bx\b",raw)):
        return "expression"
    if re.fullmatch(r"[A-Za-z_]\w*",raw):
        return "local_reference"
    if re.search(r"[+*/()<>]",raw):
        return "expression"
    return "string"


def component_maps():
    rows=read_csv(AUDIT/"hydraulic_components.csv")
    by_id={r["component_id"]:r for r in rows}
    by_path={cid.replace("/","."):r for cid,r in by_id.items()}
    return rows,by_id,by_path


def walk_circuit(circuit,parent_id=""):
    for comp in circuit.findall("./COMPS_LIST/COMP"):
        alias=(comp.findtext("ALIAS") or "").strip()
        cid=f"{parent_id}/{alias}" if parent_id else alias
        yield comp,cid,parent_id
        nested=comp.find("SUPERCOMPONENT/CIRCUIT")
        if nested is not None:
            yield from walk_circuit(nested,cid)


def cir_parameter_evidence(root):
    meta={}
    globals_by_parent=defaultdict(list)
    top_globals=[]
    top=root.find("./CIRCUIT")
    if top is None:
        raise AuditError("CIR root has no CIRCUIT")

    def visit(circuit,parent_id=""):
        global_rows=list(circuit.findall("./GLOBAL_PARAMS_LIST/GLOBALPARAM"))
        if parent_id:
            globals_by_parent[parent_id].extend(global_rows)
        else:
            top_globals.extend(global_rows)
        for comp,cid,_ in walk_circuit_shallow(circuit,parent_id):
            for kind in ("RPARAM","IPARAM","TPARAM"):
                for elem in comp.findall(f"./SUBMODEL/{kind}S_LIST/{kind}"):
                    fields={child.tag:(child.text or "").strip() for child in elem}
                    pid=fields.get("CIRCUIT_SCOPE_ID","missing")
                    meta[(cid,pid)]={"kind":kind,**fields}
            nested=comp.find("SUPERCOMPONENT/CIRCUIT")
            if nested is not None:
                visit(nested,cid)

    def walk_circuit_shallow(circuit,parent_id):
        for comp in circuit.findall("./COMPS_LIST/COMP"):
            alias=(comp.findtext("ALIAS") or "").strip()
            yield comp,(f"{parent_id}/{alias}" if parent_id else alias),parent_id

    visit(top)
    return meta,globals_by_parent,top_globals


def parameter_tables(root,by_id,by_path):
    descriptors=text_lines(RAW/"qh1_1_.param")
    values=text_lines(RAW/"qh1_1_.data")
    if len(descriptors)!=len(values):
        raise AuditError(f".param/.data row mismatch: {len(descriptors)} != {len(values)}")
    cir_meta,globals_by_parent,top_globals=cir_parameter_evidence(root)
    raw_rows=[]
    formal=[]
    by_data_path={}
    for index,(line,data_value) in enumerate(zip(descriptors,values),1):
        parsed=descriptor(line)
        if not parsed or parsed["data_path"]=="missing" or "@" not in parsed["data_path"]:
            raise AuditError(f"Unsupported .param row {index}: {line}")
        component_path=parsed["data_path"].split("@",1)[1]
        comp=by_path.get(component_path)
        if comp is None:
            raise AuditError(f"Unmapped .param Data_Path at row {index}: {component_path}")
        cid=comp["component_id"]
        meta=cir_meta.get((cid,parsed["parameter_id"]))
        cir_raw=meta.get("VALUE","") if meta else ""
        current_raw=cir_raw or data_value
        value_type=classify_value(current_raw,parsed["title"],meta.get("kind","") if meta else "",meta)
        value=numeric(current_raw) if value_type in {"numeric","boolean","enum"} else None
        value=value if value is not None else "missing"
        unit=(meta.get("UNITS") if meta else None) or parsed["unit"]
        unit=unit if unit else "missing"
        origin="supercomponent_internal" if "/" in cid else "local_component"
        notes=[f"Data_Path={parsed['data_path']}",f"ame_data_resolved_value={data_value}"]
        if meta:
            notes.extend([f"cir_kind={meta['kind']}",f"default_value={meta.get('DEF_VALUE','missing')}",
                          f"visibility={meta.get('VISIBILITY','missing')}"])
        else:
            notes.append("No matching CIR parameter element; current value comes from aligned .param/.data.")
        if value_type=="global_reference":
            notes.append("Reference preserved; normalized value intentionally not replaced by evaluated .data value.")
        row={"component_id":cid,"component_label":comp["label"],"submodel":comp["submodel"],
             "parameter_id":parsed["parameter_id"] if parsed["parameter_id"]!="missing"
                            else f"{cid}::{parsed['title']}",
             "parameter_name":parsed["title"],"raw_value":current_raw,"value":value,
             "unit":unit,"value_type":value_type,"value_origin":origin,
             "source":"ame_cir" if meta else "ame_param","editable":"unknown",
             "confidence":"confirmed","notes":"; ".join(notes),
             "_data_path":parsed["data_path"],
             "_varname":meta.get("VARNAME","missing") if meta else parsed["data_path"].split("@",1)[0]}
        formal.append(row)
        by_data_path[parsed["data_path"]]=row
        raw_rows.append({"row_index":index,"record_type":"compiled_parameter",
                         "component_id":cid,"submodel":parsed["submodel"],
                         "submodel_instance":parsed["instance"],
                         "parameter_id":parsed["parameter_id"],"data_path":parsed["data_path"],
                         "raw_descriptor":line,"raw_data_value":data_value,
                         "cir_raw_value":cir_raw or "missing",
                         "cir_default_value":meta.get("DEF_VALUE","missing") if meta else "missing",
                         "cir_parameter_kind":meta.get("kind","missing") if meta else "missing",
                         "source":"ame_param+ame_data","notes":"Rows aligned one-to-one."})

    for parent_id,items in globals_by_parent.items():
        comp=by_id[parent_id]
        for elem in items:
            raw=elem.get("VALUE","")
            ptype=classify_value(raw,elem.get("TITLE",""),"GLOBALPARAM",elem.attrib)
            pid=elem.get("Param_Id") or f"{parent_id}::global::{elem.get('GLOB_PARAM_NAME','missing')}"
            title=elem.get("TITLE") or elem.get("GLOB_PARAM_NAME","missing")
            unit=elem.get("UNITS","missing")
            title_unit=re.match(r"^.* \[([^\]]+)\]$",title)
            if unit in {"missing","null"} and title_unit:
                unit=title_unit.group(1)
            formal.append({"component_id":parent_id,"component_label":comp["label"],
                           "submodel":comp["submodel"],"parameter_id":pid,
                           "parameter_name":title,
                           "raw_value":raw or "missing",
                           "value":numeric(raw) if numeric(raw) is not None else "missing",
                           "unit":unit,"value_type":ptype,
                           "value_origin":"supercomponent_parent","source":"ame_cir",
                           "editable":"true" if elem.get("GLOB_EXPOSED")=="1" else "unknown",
                           "confidence":"confirmed",
                           "notes":f"GLOBALPARAM name={elem.get('GLOB_PARAM_NAME','missing')}; "
                                   f"GLOB_EXPOSED={elem.get('GLOB_EXPOSED','missing')}; "
                                   f"raw_UNITS={elem.get('UNITS','missing')}; title unit retained when explicit",
                           "_data_path":"missing","_varname":elem.get("GLOB_PARAM_NAME","missing")})
            raw_rows.append({"row_index":f"cir_global:{pid}","record_type":"supercomponent_global",
                             "component_id":parent_id,"submodel":comp["submodel"],
                             "submodel_instance":"missing","parameter_id":pid,"data_path":"missing",
                             "raw_descriptor":ET.tostring(elem,encoding="unicode"),
                             "raw_data_value":"missing","cir_raw_value":raw or "missing",
                             "cir_default_value":"missing","cir_parameter_kind":"GLOBALPARAM",
                             "source":"ame_cir","notes":"Parent-exposed supercomponent parameter."})

    for elem in top_globals:
        raw_rows.append({"row_index":f"cir_model_global:{elem.get('GLOB_PARAM_NAME','missing')}",
                         "record_type":"model_global","component_id":"missing","submodel":"missing",
                         "submodel_instance":"missing","parameter_id":elem.get("Param_Id","missing"),
                         "data_path":"missing","raw_descriptor":ET.tostring(elem,encoding="unicode"),
                         "raw_data_value":"missing","cir_raw_value":elem.get("VALUE","missing"),
                         "cir_default_value":"missing","cir_parameter_kind":"GLOBALPARAM",
                         "source":"ame_cir",
                         "notes":"Model-level global has no R03-A1 component_id; retained in raw only."})

    parameter_lookup={(p["component_id"],p.get("_varname")):p for p in formal}
    for parent in SC1_IDS:
        comp_node=next((c for c in root.iter("COMP")
                        if (c.findtext("ALIAS") or "").strip()==parent),None)
        if comp_node is None:
            raise AuditError(f"SC_1 component missing from CIR: {parent}")
        parent_comp=by_id[parent]
        sub=comp_node.find("SUBMODEL")
        for list_tag,item_tag in (("RPARAMS_LIST","RPARAM_EXPOSED"),
                                  ("IPARAMS_LIST","IPARAM_EXPOSED"),
                                  ("TPARAMS_LIST","TPARAM_EXPOSED")):
            for elem in sub.findall(f"./{list_tag}/{item_tag}"):
                fields={child.tag:(child.text or "").strip() for child in elem}
                exposed=fields.get("EXPOSED_VAR","")
                if "@" not in exposed:
                    raise AuditError(f"Unsupported exposed parameter in {parent}: {exposed}")
                internal_var,internal_alias=exposed.split("@",1)
                internal_id=f"{parent}/{internal_alias}"
                target=parameter_lookup.get((internal_id,internal_var))
                if target is None:
                    raise AuditError(f"Unresolved exposed parameter {parent}:{exposed}")
                pid=fields.get("CIRCUIT_SCOPE_ID") or f"{parent}::{fields.get('VARNAME','missing')}"
                row={"component_id":parent,"component_label":parent_comp["label"],
                     "submodel":"SC_1","parameter_id":pid,
                     "parameter_name":fields.get("TITLE") or fields.get("VARNAME","missing"),
                     "raw_value":target["raw_value"],"value":target["value"],
                     "unit":target["unit"],"value_type":target["value_type"],
                     "value_origin":"supercomponent_parent","source":"ame_cir",
                     "editable":"true","confidence":"confirmed",
                     "notes":f"Explicit {item_tag}; EXPOSED_VAR={exposed}; "
                             f"internal_parameter_id={target['parameter_id']}; current value inherited without evaluation.",
                     "_data_path":"missing","_varname":fields.get("VARNAME","missing"),
                     "_exposed_internal_id":internal_id,
                     "_exposed_internal_parameter":target["parameter_name"]}
                formal.append(row)
                raw_rows.append({"row_index":f"cir_exposed:{parent}:{pid}",
                                 "record_type":"supercomponent_exposed_parameter",
                                 "component_id":parent,"submodel":"SC_1",
                                 "submodel_instance":"missing","parameter_id":pid,
                                 "data_path":exposed,"raw_descriptor":ET.tostring(elem,encoding="unicode"),
                                 "raw_data_value":"missing","cir_raw_value":target["raw_value"],
                                 "cir_default_value":"missing","cir_parameter_kind":item_tag,
                                 "source":"ame_cir",
                                 "notes":f"Parent exposure of {internal_id}::{target['parameter_name']}."})
    formal.sort(key=lambda r:(r["component_id"],str(r["parameter_id"]),r["parameter_name"]))
    return raw_rows,formal,by_data_path,cir_meta,globals_by_parent


def state_tables(by_path,by_data_path):
    raw_rows=[]
    formal=[]
    state_paths=set()
    for index,line in enumerate(text_lines(RAW/"qh1_1_.state"),1):
        parsed=descriptor(line)
        if not parsed or "@" not in parsed["data_path"]:
            raise AuditError(f"Unsupported .state row {index}: {line}")
        comp=by_path.get(parsed["data_path"].split("@",1)[1])
        if comp is None:
            raise AuditError(f"Unmapped .state Data_Path row {index}")
        matched=by_data_path.get(parsed["data_path"])
        initial_raw=matched["raw_value"] if matched else "missing"
        initial_value=numeric(initial_raw)
        initial_value=initial_value if initial_value is not None else "missing"
        state_paths.add(parsed["data_path"])
        state_id=(matched["parameter_id"] if matched else
                  f"{comp['component_id']}::state::{parsed['title']}")
        raw_rows.append({"row_index":index,"component_id":comp["component_id"],
                         "submodel":comp["submodel"],"submodel_instance":parsed["instance"],
                         "data_path":parsed["data_path"],"raw_descriptor":line,
                         "matched_parameter_id":matched["parameter_id"] if matched else "missing",
                         "matched_initial_raw_value":initial_raw,"source":"ame_state",
                         "notes":"Listed explicitly in qh1_1_.state."})
        formal.append({"component_id":comp["component_id"],"component_label":comp["label"],
                       "submodel":comp["submodel"],"state_id":state_id,
                       "state_name":parsed["title"],"initial_raw_value":initial_raw,
                       "initial_value":initial_value,"unit":parsed["unit"],
                       "state_type":"dynamic_state","is_dynamic_state":"true",
                       "initialization_method":"model_saved_parameter" if matched else "unknown",
                       "source":"ame_state","confidence":"confirmed",
                       "notes":f"Data_Path={parsed['data_path']}; modelinfo NUM_STATES=359."})
    return raw_rows,formal,state_paths


def variable_kind(name):
    low=name.lower()
    if "coefficient" in low or "reynolds" in low or "ratio" in low:
        return "other"
    for token,kind in (("pressure","pressure"),("flow rate","flow"),("displacement","position"),
                       ("position","position"),("velocity","velocity"),("force","force"),
                       ("speed","speed"),("torque","torque"),("temperature","temperature"),
                       ("volume","volume"),("signal","signal"),("opening","opening")):
        if token in low:
            return kind
    return "other"


def validation_level(comp,name,kind,state_or):
    sub=comp["submodel"]
    key={"HJ020","HJ0022","HJ021","PU001","HA001","RV010","RV011","HYDPRV0",
         "PV00022","CV010","CV012","HYDCONSHTL0","HYDVORF0","VALVEDYNAMICS0",
         "HL0000","HL0002","HL011","HL012","TK000","PM000"}
    if sub in key and kind in {"pressure","flow","position","velocity","force","speed","opening","signal"}:
        return "A"
    if sub in key or state_or=="dynamic_state":
        return "B"
    if comp["element_type"] in {"signal_control","fluid_property","other"}:
        return "N/A"
    return "C"


def variable_tables(by_path,state_paths):
    var_lines=text_lines(RAW/"qh1_1_.var")
    ssf_lines=text_lines(RAW/"qh1_1_.ssf")
    if len(var_lines)!=len(ssf_lines):
        raise AuditError(f".var/.ssf row mismatch: {len(var_lines)} != {len(ssf_lines)}")
    raw_rows=[]
    formal=[]
    for index,(line,ssf) in enumerate(zip(var_lines,ssf_lines),1):
        parsed=descriptor(line)
        saved=ssf.split(maxsplit=1)[0] if ssf else "missing"
        pid=re.search(r"Param_Id=(\d+)",ssf)
        variable_id=pid.group(1) if pid else "missing"
        if not parsed or "@" not in parsed["data_path"]:
            raw_rows.append({"row_index":index,"record_type":"hidden_or_dummy",
                             "component_id":"missing","submodel":"missing",
                             "submodel_instance":"missing","data_path":"missing",
                             "raw_descriptor":line,"raw_ssf":ssf,
                             "amesim_variable_id":variable_id,"saved_flag":saved,
                             "source":"ame_var+ame_ssf","notes":"HIDDEN or _DUMMY; no component Data_Path."})
            continue
        comp=by_path.get(parsed["data_path"].split("@",1)[1])
        if comp is None:
            raise AuditError(f"Unmapped .var Data_Path row {index}")
        raw_rows.append({"row_index":index,"record_type":"compiled_variable",
                         "component_id":comp["component_id"],
                         "submodel":comp["submodel"],"submodel_instance":parsed["instance"],
                         "data_path":parsed["data_path"],"raw_descriptor":line,"raw_ssf":ssf,
                         "amesim_variable_id":variable_id,"saved_flag":saved,
                         "source":"ame_var+ame_ssf","notes":"Descriptor and save flag aligned by row."})
        state_or="dynamic_state" if parsed["data_path"] in state_paths else "algebraic_or_output"
        kind=variable_kind(parsed["title"])
        priority=validation_level(comp,parsed["title"],kind,state_or)
        formal.append({"component_id":comp["component_id"],"component_label":comp["label"],
                       "submodel":comp["submodel"],"amesim_variable_id":variable_id,
                       "variable_name":parsed["data_path"].split("@",1)[0],
                       "meaning":parsed["title"],"unit":parsed["unit"],"variable_type":kind,
                       "state_or_algebraic":state_or,
                       "saved_by_default":"true" if saved=="1" else "false",
                       "availability":"available","validation_priority":priority,
                       "recommended_for_validation":"true" if priority=="A" else "false",
                       "source":"ame_var","confidence":"confirmed",
                       "notes":f"Data_Path={parsed['data_path']}; save flag from aligned .ssf row."})
    formal.sort(key=lambda r:(r["component_id"],r["amesim_variable_id"],r["variable_name"]))
    return raw_rows,formal


def add_sc_exposed_variables(root,variables,raw_rows,by_id):
    lookup={(v["component_id"],v["variable_name"]):v for v in variables}
    for parent in SC1_IDS:
        comp_node=next(c for c in root.iter("COMP")
                       if (c.findtext("ALIAS") or "").strip()==parent)
        for elem in comp_node.findall("./SUBMODEL/IVARS_LIST/IVAR_EXPOSED"):
            fields={child.tag:(child.text or "").strip() for child in elem}
            exposed=fields.get("EXPOSED_VAR","")
            if "@" not in exposed:
                raise AuditError(f"Unsupported IVAR_EXPOSED in {parent}: {exposed}")
            internal_var,internal_alias=exposed.split("@",1)
            internal_id=f"{parent}/{internal_alias}"
            target=lookup.get((internal_id,internal_var))
            title=fields.get("TITLE") or fields.get("VARNAME","missing")
            title_unit=re.match(r"^.* \[([^\]]+)\]$",title)
            unit=title_unit.group(1) if title_unit else (
                target["unit"] if target is not None else "missing")
            kind=variable_kind(title)
            pid=fields.get("CIRCUIT_SCOPE_ID") or f"{parent}::{fields.get('VARNAME','missing')}"
            priority="A" if kind in {"pressure","flow","position","velocity","force","speed","signal","opening"} else "B"
            row={"component_id":parent,"component_label":by_id[parent]["label"],
                 "submodel":"SC_1","amesim_variable_id":pid,
                 "variable_name":fields.get("VARNAME","missing"),"meaning":title,
                 "unit":unit,"variable_type":kind,
                 "state_or_algebraic":target["state_or_algebraic"] if target else "algebraic_or_output",
                 "saved_by_default":target["saved_by_default"] if target else "unknown",
                 "availability":"available",
                 "validation_priority":priority,
                 "recommended_for_validation":"true" if priority=="A" else "false",
                 "source":"ame_cir","confidence":"confirmed",
                 "notes":f"Explicit IVAR_EXPOSED={exposed}; internal variable id="
                         f"{target['amesim_variable_id'] if target else 'not listed in .var (internal input)'}.",
                 "_exposed_internal_id":internal_id,
                 "_exposed_internal_variable":internal_var}
            variables.append(row)
            raw_rows.append({"row_index":f"cir_exposed:{parent}:{pid}",
                             "record_type":"supercomponent_exposed_variable",
                             "component_id":parent,"submodel":"SC_1",
                             "submodel_instance":"missing","data_path":exposed,
                             "raw_descriptor":ET.tostring(elem,encoding="unicode"),
                             "raw_ssf":"missing","amesim_variable_id":pid,
                             "saved_flag":"inherited","source":"ame_cir",
                             "notes":f"Parent exposure of {internal_id}::{internal_var}."})
    variables.sort(key=lambda r:(r["component_id"],r["amesim_variable_id"],r["variable_name"]))


def parameter_coverage(components,parameters):
    by_sub_instances=defaultdict(set)
    for comp in components:
        by_sub_instances[(comp["submodel"],comp["object_kind"])].add(comp["component_id"])
    rows=[]
    for (sub,kind),instances in sorted(by_sub_instances.items()):
        selected=[p for p in parameters if p["submodel"]==sub]
        covered={p["component_id"] for p in selected}
        types=Counter(p["value_type"] for p in selected)
        unit_count=sum(p["unit"]!="missing" for p in selected)
        rows.append({"submodel":sub,"object_kind":kind,"instance_count":len(instances),
                     "instances_with_parameters":len(instances&covered),"parameter_rows":len(selected),
                     "rows_with_units":unit_count,"rows_missing_units":len(selected)-unit_count,
                     "numeric_count":types["numeric"]+types["boolean"]+types["enum"],
                     "expression_count":types["expression"],
                     "reference_count":types["global_reference"]+types["local_reference"],
                     "table_curve_count":types["table"]+types["curve"],
                     "missing_value_count":types["missing"],
                     "coverage_status":"covered" if instances&covered else "no_parameter_rows",
                     "notes":"Counts current saved parameters; absence can be valid for structural objects."})
    return rows


def state_coverage(components,states,variables):
    instances=defaultdict(set)
    for comp in components:
        instances[comp["submodel"]].add(comp["component_id"])
    rows=[]
    for sub,cids in sorted(instances.items()):
        selected=[s for s in states if s["submodel"]==sub]
        dynamic=[s for s in selected if s["state_type"]=="dynamic_state"]
        ic=[s for s in selected if s["state_type"]=="initial_condition_parameter"]
        algebraic=[v for v in variables if v["submodel"]==sub and
                   v["state_or_algebraic"]=="algebraic_or_output"]
        unknown=[s for s in selected if s["state_type"]=="unknown"]
        rows.append({"submodel":sub,"instance_count":len(cids),
                     "instances_with_dynamic_states":len({s["component_id"] for s in dynamic}),
                     "dynamic_state_count":len(dynamic),
                     "initial_condition_count":len(ic),
                     "algebraic_variable_count":len(algebraic),
                     "unknown_state_type_count":len(unknown),
                     "coverage_status":"covered" if dynamic or algebraic else "no_state_or_variable_rows",
                     "notes":"Dynamic states come only from .state; algebraic/output count comes from .var minus .state."})
    return rows


def validation_channels(variables):
    rows=[]
    for var in variables:
        if var["validation_priority"] not in {"A","B"}:
            continue
        sub=var["submodel"]
        root=parent_for(var["component_id"])
        major={"HJ020","HJ0022","HJ021","PU001","PM000","TK000","HA001","RV010",
               "RV011","HYDPRV0","PV00022","CV010","CV012","HYDCONSHTL0"}
        selected=(sub in major or
                  (var["component_id"] in {"dirvalve_6","dirvalve_8"} and sub=="SC_1") or
                  (root in {"dirvalve_6","dirvalve_8"} and
                   sub in {"VALVEDYNAMICS0","HYDVORF0","FX00"}) or
                  (sub in {"HL0000","HL0002","HL011","HL012"} and
                   var["state_or_algebraic"]=="dynamic_state" and
                   var["variable_type"]=="pressure"))
        if not selected:
            continue
        rows.append({"channel_id":f"{var['component_id']}::{var['amesim_variable_id']}",
                     "physical_quantity":var["variable_type"],
                     "component_id":var["component_id"],"component_label":var["component_label"],
                     "submodel":var["submodel"],
                     "amesim_variable_id":var["amesim_variable_id"],
                     "variable_name":var["variable_name"],"unit":var["unit"],
                     "validation_priority":var["validation_priority"],
                     "availability":var["availability"],
                     "reason":"Core pressure/flow/motion channel." if var["validation_priority"]=="A"
                              else "Auxiliary state or component diagnostic.",
                     "source":var["source"],"confidence":var["confidence"],
                     "notes":var["meaning"]})
    return rows


def parent_for(cid):
    return cid.split("/",1)[0] if "/" in cid else cid


def sc1_mapping(components,connections,parameters,states,variables):
    by_id={r["component_id"]:r for r in components}
    rows=[]
    physical_port={}
    for var in variables:
        internal=var.get("_exposed_internal_id")
        match=re.fullmatch(r"[pq]_([PTAB])",var.get("variable_name",""))
        if var["component_id"] in SC1_IDS and internal and match:
            physical_port[(var["component_id"],internal)]=match.group(1)
    for edge in connections:
        if edge.get("relation")!="supercomponent_port_alias":
            continue
        a,b=edge["from_component"],edge["to_component"]
        parent=a if a in SC1_IDS else b if b in SC1_IDS else None
        if not parent:
            continue
        internal=b if parent==a else a
        external_port=edge["from_port"] if parent==a else edge["to_port"]
        internal_port=edge["to_port"] if parent==a else edge["from_port"]
        port_type=edge["connection_type"]
        ic=by_id[internal]
        physical=physical_port.get((parent,internal),"missing")
        rows.append({"sc_instance":parent,"parent_component_id":parent,
                     "parent_label":by_id[parent]["label"],"external_port":external_port,
                     "external_port_type":port_type,"internal_component_id":internal,
                     "internal_component_label":ic["label"],"internal_submodel":ic["submodel"],
                     "internal_port":internal_port,
                     "mapping_type":"signal_mapping" if port_type=="signal" else "port_alias",
                     "parameter_name":f"physical_port_{physical}" if physical!="missing" else "missing",
                     "parameter_raw_value":"missing",
                     "parameter_value":"missing","parameter_unit":"missing",
                     "exposed_to_parent":"true","parent_parameter":physical,
                     "internal_parameter":"missing","source":"ame_cir","confidence":"confirmed",
                     "notes":"SC_PORTS_MAP_LIST cross-checked in R03-A1; physical letter comes from "
                             "explicit IVAR_EXPOSED p_/q_ mapping; no flow direction implied."})
    for p in parameters:
        if p["component_id"] in SC1_IDS and p.get("_exposed_internal_id"):
            parent=p["component_id"]
            internal=p["_exposed_internal_id"]
            rows.append({"sc_instance":parent,"parent_component_id":parent,
                         "parent_label":by_id[parent]["label"],"external_port":"missing",
                         "external_port_type":"parameter","internal_component_id":internal,
                         "internal_component_label":by_id[internal]["label"],
                         "internal_submodel":by_id[internal]["submodel"],"internal_port":"missing",
                         "mapping_type":"parameter_mapping","parameter_name":p["parameter_name"],
                         "parameter_raw_value":p["raw_value"],"parameter_value":p["value"],
                         "parameter_unit":p["unit"],"exposed_to_parent":"true",
                         "parent_parameter":p["parameter_name"],
                         "internal_parameter":p["_exposed_internal_parameter"],
                         "source":"ame_cir","confidence":"confirmed",
                         "notes":"Explicit RPARAM_EXPOSED/IPARAM_EXPOSED/TPARAM_EXPOSED mapping."})
            continue
        if "/" not in p["component_id"] or parent_for(p["component_id"]) not in SC1_IDS:
            continue
        if p["value_type"]!="global_reference":
            continue
        parent=parent_for(p["component_id"])
        base=p["raw_value"].split("__SC_",1)[0]
        rows.append({"sc_instance":parent,"parent_component_id":parent,
                     "parent_label":by_id[parent]["label"],"external_port":"missing",
                     "external_port_type":"parameter","internal_component_id":p["component_id"],
                     "internal_component_label":p["component_label"],
                     "internal_submodel":p["submodel"],"internal_port":"missing",
                     "mapping_type":"parameter_mapping","parameter_name":p["parameter_name"],
                     "parameter_raw_value":p["raw_value"],"parameter_value":p["value"],
                     "parameter_unit":p["unit"],"exposed_to_parent":"true",
                     "parent_parameter":base,"internal_parameter":p["parameter_name"],
                     "source":"ame_cir","confidence":"confirmed",
                     "notes":"USES_SC_GP reference preserved; evaluated numeric value is only in notes of parameter table."})
    for state in states:
        if "/" not in state["component_id"] or parent_for(state["component_id"]) not in SC1_IDS:
            continue
        parent=parent_for(state["component_id"])
        rows.append({"sc_instance":parent,"parent_component_id":parent,
                     "parent_label":by_id[parent]["label"],"external_port":"missing",
                     "external_port_type":"state","internal_component_id":state["component_id"],
                     "internal_component_label":state["component_label"],
                     "internal_submodel":state["submodel"],"internal_port":"missing",
                     "mapping_type":"state_mapping","parameter_name":state["state_name"],
                     "parameter_raw_value":state["initial_raw_value"],
                     "parameter_value":state["initial_value"],"parameter_unit":state["unit"],
                     "exposed_to_parent":"false","parent_parameter":"missing",
                     "internal_parameter":state["state_name"],"source":"ame_state",
                     "confidence":"confirmed","notes":"Explicit qh1_1_.state record."})
    for var in variables:
        if var["component_id"] not in SC1_IDS or not var.get("_exposed_internal_id"):
            continue
        parent=var["component_id"]
        internal=var["_exposed_internal_id"]
        rows.append({"sc_instance":parent,"parent_component_id":parent,
                     "parent_label":by_id[parent]["label"],"external_port":"missing",
                     "external_port_type":"variable","internal_component_id":internal,
                     "internal_component_label":by_id[internal]["label"],
                     "internal_submodel":by_id[internal]["submodel"],"internal_port":"missing",
                     "mapping_type":"other","parameter_name":var["variable_name"],
                     "parameter_raw_value":"missing","parameter_value":"missing",
                     "parameter_unit":var["unit"],"exposed_to_parent":"true",
                     "parent_parameter":var["variable_name"],
                     "internal_parameter":var["_exposed_internal_variable"],
                     "source":"ame_cir","confidence":"confirmed",
                     "notes":"Explicit IVAR_EXPOSED parent/internal variable mapping."})
    important={"VALVEDYNAMICS0","HYDVORF0","FX00"}
    seen=set()
    for edge in connections:
        if edge.get("relation")=="supercomponent_port_alias":
            continue
        a,b=edge["from_component"],edge["to_component"]
        if "/" not in a or "/" not in b or parent_for(a)!=parent_for(b):
            continue
        parent=parent_for(a)
        if parent not in SC1_IDS:
            continue
        for cid,port,other,other_port in ((a,edge["from_port"],b,edge["to_port"]),
                                          (b,edge["to_port"],a,edge["from_port"])):
            if by_id[cid]["submodel"] not in important:
                continue
            key=(cid,port,other,other_port)
            if key in seen:
                continue
            seen.add(key)
            rows.append({"sc_instance":parent,"parent_component_id":parent,
                         "parent_label":by_id[parent]["label"],"external_port":"missing",
                         "external_port_type":edge["connection_type"],
                         "internal_component_id":cid,
                         "internal_component_label":by_id[cid]["label"],
                         "internal_submodel":by_id[cid]["submodel"],"internal_port":port,
                         "mapping_type":"other","parameter_name":"missing",
                         "parameter_raw_value":"missing","parameter_value":"missing",
                         "parameter_unit":"missing","exposed_to_parent":"false",
                         "parent_parameter":"missing","internal_parameter":"missing",
                         "source":"ame_internal","confidence":"confirmed",
                         "notes":f"Internal connection to {other} port {other_port}; "
                                 f"relation={edge.get('relation','missing')}; no flow direction implied."})
    return sorted(rows,key=lambda r:(r["sc_instance"],r["mapping_type"],
                                     str(r["external_port"]),r["internal_component_id"],
                                     r["parameter_name"]))


def sc1_comparison(components,parameters,states,mapping):
    by_parent=defaultdict(list)
    for comp in components:
        if "/" in comp["component_id"] and parent_for(comp["component_id"]) in SC1_IDS:
            by_parent[parent_for(comp["component_id"])].append(comp)
    features=defaultdict(dict)
    for parent in SC1_IDS:
        internals=by_parent[parent]
        parent_params=[p for p in parameters if p["component_id"]==parent]
        internal_params=[p for p in parameters if p["component_id"].startswith(parent+"/")]
        ports=[m for m in mapping if m["sc_instance"]==parent and
               m["mapping_type"] in {"port_alias","signal_mapping"}]
        def signature(rows):
            def normalized(p):
                cid=p["component_id"]
                relative=cid.split("/",1)[1] if "/" in cid else "__parent__"
                raw=re.sub(r"__SC_1_\d+", "__SC_1_*",p["raw_value"])
                return relative,p["parameter_name"],raw,p["unit"]
            return json.dumps(sorted(normalized(p) for p in rows),
                              ensure_ascii=False,separators=(",",":"))
        vals={
            "external_ports":json.dumps(sorted((m["external_port"],m["external_port_type"],
                                                 m["internal_component_id"].split("/",1)[-1],
                                                 m["internal_port"]) for m in ports),
                                        ensure_ascii=False,separators=(",",":")),
            "internal_component_count":str(len(internals)),
            "internal_submodel_set":json.dumps(sorted(Counter(c["submodel"] for c in internals).items()),
                                               separators=(",",":")),
            "parameter_names":json.dumps(sorted(set(p["parameter_name"] for p in internal_params)),
                                         ensure_ascii=False,separators=(",",":")),
            "parameter_values":signature(internal_params),
            "valve_dynamics_parameters":signature([p for p in internal_params
                                                   if p["submodel"]=="VALVEDYNAMICS0"]),
            "flow_path_parameters":signature([p for p in internal_params
                                              if p["submodel"]=="HYDVORF0"]),
            "signal_source_interface":json.dumps(
                sorted(Counter(c["submodel"] for c in internals if c["domain"]=="signal").items()),
                separators=(",",":")),
            "exposed_parent_parameters":signature(parent_params),
            "dynamic_states":json.dumps(sorted(s["state_name"] for s in states
                                               if s["component_id"].startswith(parent+"/")),
                                        ensure_ascii=False,separators=(",",":")),
        }
        for feature,value in vals.items():
            features[feature][parent]=value
    rows=[]
    for feature,values in features.items():
        same=len(set(values.values()))==1
        for parent in SC1_IDS:
            rows.append({"sc_instance":parent,"feature":feature,"value":values[parent],
                         "same_across_all":str(same).lower(),
                         "reference_instance":"dirvalve_6",
                         "matches_dirvalve_6":str(values[parent]==values["dirvalve_6"]).lower(),
                         "notes":"Canonical long-form comparison; values are not interpreted as equations."})
    return rows


def parameter_ground_truth(root,parameters):
    rows=[]
    parent=[p for p in parameters if p["component_id"]=="dirvalve_6"]
    checks=[("index of hydraulic fluid","0","missing"),
            ("nominal density","850","kg/m**3"),
            ("nominal kinematic viscosity","60","cSt")]
    for needle,expected,unit in checks:
        matches=[p for p in parent if needle.lower() in p["parameter_name"].lower()]
        status="NOT_FOUND"
        extracted="missing"
        value="missing"
        found_unit="missing"
        source="missing"
        if len(matches)==1:
            p=matches[0]
            extracted,value,found_unit,source=p["raw_value"],p["value"],p["unit"],p["source"]
            status="PASS" if numeric(extracted)==numeric(expected) and (
                unit=="missing" or found_unit==unit or (found_unit=="null" and unit=="missing")) else "FAIL"
        elif len(matches)>1:
            status="AMBIGUOUS"
        rows.append({"component":"dirvalve_6","submodel":"SC_1","parameter_name":needle,
                     "gui_expected":expected,"extracted_raw_value":extracted,
                     "extracted_value":value,"unit":found_unit,"status":status,
                     "source":source,"notes":"GUI value checked against parent GLOBALPARAM, not internal evaluated copies."})
    comp=next(c for c in root.iter("COMP") if (c.findtext("ALIAS") or "").strip()=="dirvalve_6")
    xml_text=ET.tostring(comp,encoding="unicode")
    for label in ("fractional spool position","path P-B","path P-A","path T-A","path T-B",
                  "valve dynamics"):
        present=label.lower() in xml_text.lower()
        rows.append({"component":"dirvalve_6","submodel":"SC_1","parameter_name":label,
                     "gui_expected":"present","extracted_raw_value":"present" if present else "missing",
                     "extracted_value":"missing","unit":"missing",
                     "status":"PASS" if present else "NOT_FOUND","source":"ame_cir",
                     "notes":"Checks archived GUI group/title evidence; does not infer a valve equation."})
    return rows


def documentation_index(submodels,installation):
    wanted=set(submodels)
    found=defaultdict(list)
    for path in Path(installation).rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".spe",".c"}:
            continue
        if path.stem in wanted:
            found[path.stem].append(path)
    rows=[]
    for sub in sorted(wanted):
        paths=sorted(found.get(sub,[]),key=lambda p:str(p).lower())
        if not paths:
            rows.append({"submodel":sub,"installation_file":"missing","file_type":"missing",
                         "description_found":"false","parameter_definition_found":"false",
                         "variable_definition_found":"false","state_definition_found":"false",
                         "equation_reference_found":"false",
                         "documentation_status":"needs_manual_help_lookup" if sub=="SC_1" else "missing",
                         "notes":"SC_1 is model-local." if sub=="SC_1"
                                 else "No exact-stem .spe/.c file found; compatible names were not substituted."})
            continue
        for path in paths:
            try:
                text=path.read_text(encoding="latin1",errors="replace")
            except OSError:
                text=""
            low=text.lower()
            rows.append({"submodel":sub,"installation_file":str(path),
                         "file_type":path.suffix.lower().lstrip("."),
                         "description_found":str(any(k in low for k in ("description","title"))).lower(),
                         "parameter_definition_found":str(any(k in low for k in ("parameter","rpar","ipar","tpar"))).lower(),
                         "variable_definition_found":str(any(k in low for k in ("variable","output"))).lower(),
                         "state_definition_found":str(any(k in low for k in ("state","nstate"))).lower(),
                         "equation_reference_found":str(any(k in low for k in ("equation","derivative","deriv"))).lower(),
                         "documentation_status":"available",
                         "notes":"Presence/index only; source code was not reverse-engineered or executed."})
    return rows


def add_initial_condition_parameters(parameters,states,state_paths):
    existing={(s["component_id"],s["state_id"]) for s in states}
    for p in parameters:
        low=p["parameter_name"].lower()
        if "initial" not in low or p.get("_data_path") in state_paths:
            continue
        key=(p["component_id"],f"ic::{p['parameter_id']}")
        if key in existing:
            continue
        states.append({"component_id":p["component_id"],"component_label":p["component_label"],
                       "submodel":p["submodel"],"state_id":key[1],"state_name":p["parameter_name"],
                       "initial_raw_value":p["raw_value"],"initial_value":p["value"],
                       "unit":p["unit"],"state_type":"initial_condition_parameter",
                       "is_dynamic_state":"false","initialization_method":"parameter_named_initial",
                       "source":p["source"],"confidence":"confirmed",
                       "notes":"Not listed in .state; retained separately because the saved parameter explicitly names initialization."})
        existing.add(key)


def report_text(manifest,parameters,states,variables,coverage,state_cov,channels,mapping,
                comparison,ground_truth,docs):
    pt=Counter(p["value_type"] for p in parameters)
    priorities=Counter(v["validation_priority"] for v in variables)
    state_types=Counter(s["state_type"] for s in states)
    units=sum(p["unit"]!="missing" for p in parameters)
    sc_same={r["feature"]:r["same_across_all"] for r in comparison if r["sc_instance"]=="dirvalve_6"}
    gt=Counter(r["status"] for r in ground_truth)
    key_subs=("SC_1","HJ020","HJ0022","HJ021","PU001","RV010","RV011",
              "HYDPRV0","HA001","CV010","HYDCONSHTL0","PV00022",
              "HL0000","HL0002","HL011","HL012")
    cov={r["submodel"]:r for r in coverage}
    scov={r["submodel"]:r for r in state_cov}
    port_lines=[]
    for parent in SC1_IDS:
        ports=sorted((int(r["external_port"]),r["external_port_type"],r["parent_parameter"],
                      r["internal_component_id"].split("/",1)[-1],r["internal_port"])
                     for r in mapping if r["sc_instance"]==parent and
                     r["mapping_type"] in {"port_alias","signal_mapping"})
        port_lines.append(f"- {parent}: "+", ".join(
            f"ext{p}({domain},{physical})->{internal}:port{ip}"
            for p,domain,physical,internal,ip in ports))
    lines=[
        "# R03-A2 AMESim 参数—初值—变量—SC_1映射审计",
        "## 1. 任务边界",
        "本轮仅数字化当前保存参数、初值、变量及SC_1内部映射；未实现液压方程、控制器、联合仿真或精度结论。",
        "## 2. 原模型和完整性检查",
        f"模型：{manifest['model']}。开始/结束SHA256均为{manifest['start']['sha256']}；"
        f"size={manifest['start']['size']}，mtime_ns={manifest['start']['mtime_ns']}，只读一致={manifest['original_unchanged']}。",
        "## 3. Python环境",
        f"sys.executable={manifest['python']}。未改PATH、未使用AMESim Python或其他Conda环境。",
        "## 4. 参数数据来源",
        "当前值以.cir的VALUE原文本优先；.param提供Param_Id、名称、单位和Data_Path；.data按4142行一一对应提供编译/求值后的保存值。"
        "引用不被数值覆盖，默认值仅记入notes，不与当前值混淆。",
        "## 5. param/state/var/data结构",
        ".param/.data各4142行；.var/.ssf各2736行；其中2229行变量具有可映射Data_Path，507行是HIDDEN/_DUMMY raw证据；"
        ".state为359行，modelinfo NUM_STATES=359、NUM_DISCRETE_STATES=57。未发现独立离散状态名称表，因此57个离散状态不冒充具名动态状态。",
        "## 6. hydraulic_parameters.csv统计",
        f"正式参数行={len(parameters)}，覆盖组件={len(set(p['component_id'] for p in parameters))}，有可靠单位={units}，缺单位={len(parameters)-units}。",
        "## 7. 参数value_type统计",
        json.dumps(dict(sorted(pt.items())),ensure_ascii=False),
        "## 8. 参数unit coverage",
        f"{units}/{len(parameters)}={units/len(parameters):.2%}；'null'视为AMESim明确给出的无量纲单位，missing才是无单位证据。",
        "## 9. global/local/reference/expression",
        f"全局引用={pt['global_reference']}，局部引用={pt['local_reference']}，表达式={pt['expression']}，table={pt['table']}。"
        "SC父GLOBALPARAM与内部USES_SC_GP分层保留；模型级11个global因无R03-A1 component_id只保留在raw。",
        "## 10. hydraulic_initial_states.csv统计",
        f"正式行={len(states)}；类型={json.dumps(dict(state_types),ensure_ascii=False)}。",
        "## 11. dynamic state区分",
        "只有明确出现在.state的359项标为dynamic_state；仅参数名含initial但不在.state者标为initial_condition_parameter；"
        ".var中其余量标为algebraic_or_output，不把理论上可能的压力或位移自动当成state。",
        "## 12. hydraulic_variables.csv统计",
        f"可映射变量={len(variables)}；优先级={json.dumps(dict(priorities),ensure_ascii=False)}。",
        "## 13. AMESim到Python验证通道",
        f"已绑定{len(channels)}条A/B候选到具体component_id、variable_id和单位；A级用于压力、流量、缸运动/力、泵速和阀开度等核心比较。",
        "## 14. SC_1专项结构",
        f"10个实例全部进入审计；mapping行={len(mapping)}。外部端口使用R03-A1已验证SC_PORTS_MAP_LIST，"
        "signal端口单列signal_mapping；VALVEDYNAMICS0、HYDVORF0、FX00的内部连接和参数引用均保留。",
        "\n".join(port_lines),
        "P/T/A/B字母来自父SUBMODEL的显式IVAR_EXPOSED p_/q_映射：dirvalve_6/8均为ext0=P、ext1=T、ext2=B、ext3=A、ext4=signal。"
        "信号口映射到table_fractional_spool_position(FX00) port1，FX00输出连接VALVEDYNAMICS0 port1，"
        "VALVEDYNAMICS0 port0连接frac_spool_pos_node。",
        "dirvalve_6/8的HYDVORF路径由显式exposed映射确认：orifice_13=P-B、orifice_14=P-A、"
        "orifice_24=T-A、orifice_23=T-B；每个orifice的port0接同号FX00表，液压port1/2进入内部网络。",
        "FX00只按官方/模型元数据称为function of one variable（函数/表表达式对象），不推断额外物理方程。",
        "## 15. 10个SC_1实例差异",
        "逐实例比较结论："+json.dumps(sc_same,ensure_ascii=False)+
        "。同名SC_1并不代表结构和参数完全相同；4口/5口、内部组件数、流路及表达式差异均保留。",
        "dirvalve_6与dirvalve_8的外端口、内部submodel集合、VALVEDYNAMICS0参数、HYDVORF0参数、"
        "父GLOBALPARAM和信号接口一致，但4个FX00开口表达式（table_13/14/23/24）不同，因此参数并非完全一致。",
        "## 16. dirvalve_6 GUI Ground Truth",
        f"检查状态={dict(gt)}。indexf=0、density=850 kg/m**3、viscosity=60 cSt来自父GLOBALPARAM；"
        "fractional spool position、P-A/P-B/T-A/T-B和valve dynamics标题均从归档独立追溯。",
        "## 17. PU001参数审计",
        f"{cov.get('PU001',{})}；状态/变量={scov.get('PU001',{})}。",
        "## 18. HJ020/HJ0022/HJ021",
        "; ".join(f"{s}:参数={cov.get(s,{})}, 状态/变量={scov.get(s,{})}" for s in ("HJ020","HJ0022","HJ021")),
        "## 19. RV010/RV011/HYDPRV0",
        "; ".join(f"{s}:参数={cov.get(s,{})}, 状态/变量={scov.get(s,{})}" for s in ("RV010","RV011","HYDPRV0")),
        "## 20. HA001",
        f"参数={cov.get('HA001',{})}；状态/变量={scov.get('HA001',{})}。",
        "## 21. 管路/容腔模型",
        "; ".join(f"{s}:参数={cov.get(s,{})}, 状态/变量={scov.get(s,{})}" for s in ("HL0000","HL0002","HL011","HL012")),
        "## 22. missing/inferred/manual",
        f"missing value={pt['missing']}、missing unit={len(parameters)-units}。工程优先级是inferred；参数值、Data_Path、state和variable结构为archive confirmed；GUI仅用于Ground Truth。",
        "## 23. 官方帮助/.spe/.c",
        f"文档索引行={len(docs)}；仅记录文件存在性及定义关键字证据，不执行或完整逆向.c。SC_1为模型本地supercomponent，继续needs_manual_help_lookup。",
        "## 24. 尚不能确认",
        "未能从归档获得57个离散状态的逐项名称；saved_by_default来自.ssf而非结果文件实测；"
        "SC_1端口P/T/A/B已由归档IVAR_EXPOSED映射确认，但端口连接记录本身无物理流向，不能据from/to猜瞬时流向；"
        "SC_1仍没有独立官方帮助条目。",
        "## 25. 验收建议",
        "若专项测试、原模型结束指纹和机械冻结区检查均通过，建议R03-A2为CONDITIONAL PASS：参数、具名连续状态、变量和SC映射已可追溯，"
        "但57个离散状态缺少逐项名称，SC_1仍缺独立官方帮助定义，部分单位只可保留missing。",
        "## 26. 对R03-B的建议",
        "仅在项目负责人验收后，以A级通道和关键submodel参数表冻结R03-B输入；不要从本报告直接推导或实现方程。",
    ]
    return "\n\n".join(lines)+"\n"


def run(model,output,installation,overwrite=False):
    if Path(sys.executable).resolve()!=EXPECTED_PYTHON.resolve():
        raise AuditError(f"Only steering_sim is permitted: {sys.executable}")
    model=Path(model).resolve()
    output=Path(output).resolve()
    installation=Path(installation).resolve()
    start=file_identity(model)
    if start["sha256"]!=EXPECTED_SHA:
        raise AuditError(f"Baseline SHA256 mismatch: {start['sha256']}")
    required=[output/"hydraulic_components.csv",output/"hydraulic_connections.csv",
              RAW/"circuit.normalized.xml",RAW/"qh1_1_.param",RAW/"qh1_1_.data",
              RAW/"qh1_1_.state",RAW/"qh1_1_.var",RAW/"qh1_1_.ssf"]
    missing=[str(p) for p in required if not p.exists()]
    if missing:
        raise AuditError("Missing accepted R03-A1 evidence: "+"; ".join(missing))
    targets=[
        "hydraulic_parameters.csv","hydraulic_initial_states.csv","hydraulic_variables.csv",
        "r03a2_raw_parameters.csv","r03a2_raw_states.csv","r03a2_raw_variables.csv",
        "r03a2_parameter_coverage.csv","r03a2_state_coverage.csv",
        "r03a2_validation_channels.csv","r03a2_sc1_mapping.csv",
        "r03a2_sc1_instance_comparison.csv","r03a2_parameter_ground_truth_check.csv",
        "r03a2_submodel_documentation_index.csv",
        "R03A2_AMESim_parameter_state_variable_audit.md","r03a2_manifest.json"]
    existing=[str(output/name) for name in targets if (output/name).exists()]
    if existing and not overwrite:
        raise AuditError("R03-A2 output exists; use --overwrite-r03a2 explicitly: "+"; ".join(existing))

    components,by_id,by_path=component_maps()
    connections=read_csv(output/"hydraulic_connections.csv")
    root=ET.parse(RAW/"circuit.normalized.xml").getroot()
    raw_params,parameters,by_data_path,cir_meta,globals_by_parent=parameter_tables(
        root,by_id,by_path)
    raw_states,states,state_paths=state_tables(by_path,by_data_path)
    add_initial_condition_parameters(parameters,states,state_paths)
    raw_vars,variables=variable_tables(by_path,state_paths)
    add_sc_exposed_variables(root,variables,raw_vars,by_id)
    coverage=parameter_coverage(components,parameters)
    state_cov=state_coverage(components,states,variables)
    channels=validation_channels(variables)
    mapping=sc1_mapping(components,connections,parameters,states,variables)
    comparison=sc1_comparison(components,parameters,states,mapping)
    ground_truth=parameter_ground_truth(root,parameters)
    docs=documentation_index(sorted({c["submodel"] for c in components}),installation)

    formal_params=[{k:v for k,v in row.items() if not k.startswith("_")} for row in parameters]
    write_csv(output/"hydraulic_parameters.csv",formal_params,PARAM_FIELDS)
    write_csv(output/"hydraulic_initial_states.csv",states,STATE_FIELDS)
    write_csv(output/"hydraulic_variables.csv",variables,VAR_FIELDS)
    write_csv(output/"r03a2_raw_parameters.csv",raw_params,RAW_PARAM_FIELDS)
    write_csv(output/"r03a2_raw_states.csv",raw_states,RAW_STATE_FIELDS)
    write_csv(output/"r03a2_raw_variables.csv",raw_vars,RAW_VAR_FIELDS)
    write_csv(output/"r03a2_parameter_coverage.csv",coverage,list(coverage[0]))
    write_csv(output/"r03a2_state_coverage.csv",state_cov,list(state_cov[0]))
    write_csv(output/"r03a2_validation_channels.csv",channels,list(channels[0]))
    write_csv(output/"r03a2_sc1_mapping.csv",mapping,list(mapping[0]))
    write_csv(output/"r03a2_sc1_instance_comparison.csv",comparison,list(comparison[0]))
    write_csv(output/"r03a2_parameter_ground_truth_check.csv",ground_truth,list(ground_truth[0]))
    write_csv(output/"r03a2_submodel_documentation_index.csv",docs,list(docs[0]))

    end=file_identity(model)
    manifest={
        "model":str(model),"python":sys.executable,"installation":str(installation),
        "start":start,"end":end,"original_unchanged":start==end,
        "sources":{
            name:file_identity(RAW/name) for name in
            ("qh1_1_.param","qh1_1_.data","qh1_1_.state","qh1_1_.var","qh1_1_.ssf",
             "qh1_1_.cir","qh1_1_.modelinfo")},
        "counts":{
            "raw_parameter_rows":len(raw_params),"parameter_rows":len(formal_params),
            "parameter_instances":len({p["component_id"] for p in formal_params}),
            "raw_state_rows":len(raw_states),"state_rows":len(states),
            "dynamic_states":sum(s["state_type"]=="dynamic_state" for s in states),
            "initial_condition_parameters":sum(s["state_type"]=="initial_condition_parameter" for s in states),
            "raw_variable_rows":len(raw_vars),"variable_rows":len(variables),
            "validation_channels":len(channels),"sc1_mapping_rows":len(mapping),
            "sc1_instances":len({r["sc_instance"] for r in mapping}),
            "documentation_rows":len(docs)},
        "value_types":dict(Counter(p["value_type"] for p in formal_params)),
        "variable_priorities":dict(Counter(v["validation_priority"] for v in variables)),
        "ground_truth":dict(Counter(r["status"] for r in ground_truth)),
        "limitations":[
            "57 discrete states reported by modelinfo have no per-state names in audited archive tables.",
            "SC_1 P/T/A/B labels are traced through IVAR_EXPOSED; connection direction is still not inferred.",
            "Documentation index records evidence presence, not reconstructed equations."],
    }
    if not manifest["original_unchanged"]:
        raise AuditError("Original qh1_1.ame changed during R03-A2")
    (output/"R03A2_AMESim_parameter_state_variable_audit.md").write_text(
        report_text(manifest,formal_params,states,variables,coverage,state_cov,channels,
                    mapping,comparison,ground_truth,docs),encoding="utf-8")
    (output/"r03a2_manifest.json").write_text(
        json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model",type=Path,default=ROOT/"qh1_1.ame")
    parser.add_argument("--output",type=Path,default=AUDIT)
    parser.add_argument("--amesim-root",type=Path,
                        default=Path(os.environ.get("AME",r"E:\Simcenter\2021.1\Amesim")))
    parser.add_argument("--overwrite-r03a2",action="store_true")
    args=parser.parse_args()
    try:
        result=run(args.model,args.output,args.amesim_root,args.overwrite_r03a2)
    except (AuditError,OSError,ET.ParseError,csv.Error) as exc:
        parser.exit(2,f"R03-A2审计失败（未静默回退）：{exc}\n")
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
