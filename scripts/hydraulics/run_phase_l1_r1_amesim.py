from __future__ import print_function

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
import time
import traceback

import ame_apy

ROOT = r"E:\15_project"
AUDIT_MODEL = os.path.join(ROOT, "qh1_1_MCP_AUDIT.ame")
TEMP_MODEL = os.path.join(ROOT, "qh1_1_L1_R1_TEMP.ame")
SOURCE = "dirvalve_1_piecewiselinear_5"


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def setv(name, value):
    ame_apy.AMESetParameterValue("%s@%s" % (name, SOURCE), str(value))


def configure(scenario):
    if scenario == "S0":
        return
    if scenario == "S1":
        values = [(0.0, 0.0, 0.05), (0.10, 0.10, 0.95)]
    elif scenario == "S2":
        # Eight linear segments form an exactly documented 1 Hz polygonal sine.
        times = [i / 8.0 for i in range(9)]
        vals = [0.10 * math.sin(2.0 * math.pi * t) for t in times]
        values = [(vals[i], vals[i + 1], 0.125) for i in range(8)]
    else:
        raise ValueError(scenario)
    setv("tstart", 0)
    setv("nstages", len(values))
    setv("iscyclic", 0)
    for i, (start, end, duration) in enumerate(values, 1):
        setv("start%d" % i, start); setv("end%d" % i, end); setv("t%d" % i, duration)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    original_hash = digest(AUDIT_MODEL)
    shutil.copy2(AUDIT_MODEL, TEMP_MODEL)
    paths = [
        "output@%s" % SOURCE, "signal_input@dirvalve_6", "frac_spool_position@dirvalve_6",
        "speed@pump01", "qout@pump01", "pout@pump01", "speed@pump01_1", "qout@pump01_1", "pout@pump01_1",
        "p1@actuator002", "p2@actuator002", "frod@actuator002", "x@actuator002", "v@actuator002",
        "q2@dirvalve_6.orifice_13", "q2@dirvalve_6.orifice_14", "q2@dirvalve_6.orifice_23", "q2@dirvalve_6.orifice_24",
        "q2@presscontrol01", "q2@presscontrol01_1", "press@tank01",
    ]
    payload = {"success": False, "audit_hash_before": original_hash, "scenarios": {}, "closed_without_save": []}
    for scenario in ("S0", "S1", "S2"):
        opened = False
        try:
            ame_apy.AMEInitAPI(False); ame_apy.AMEOpenAmeFile(TEMP_MODEL); opened = True
            configure(scenario)
            if scenario != "S0":
                ame_apy.AMEGenerateCode()
            for path in paths:
                try: ame_apy.AMESaveVariable(path, True)
                except Exception: pass
            ame_apy.AMESetRunParameter("start_time_s", "0")
            ame_apy.AMESetRunParameter("stop_time_s", "1")
            ame_apy.AMESetRunParameter("interval_s", "0.001")
            ame_apy.AMESetRunParameter("simulation_mode", "2")
            started = time.time(); ame_apy.AMERunSimulation(); wall = time.time() - started
            series, infos, failed = {}, {}, {}
            for path in paths:
                try:
                    series[path] = [list(item) for item in ame_apy.AMEGetVariableValues(path)]
                    infos[path] = list(ame_apy.AMEGetVariableInfos(path))
                except Exception as exc: failed[path] = str(exc)
            payload["scenarios"][scenario] = {"success": True, "wall_time_s": wall, "series": series, "infos": infos, "failed": failed}
        except Exception:
            payload["scenarios"][scenario] = {"success": False, "error": traceback.format_exc()}
        finally:
            if opened:
                try:
                    ame_apy.AMECloseCircuit(False); payload["closed_without_save"].append(scenario)
                except Exception: payload.setdefault("close_errors", {})[scenario] = traceback.format_exc()
            try: ame_apy.AMECloseAPI()
            except Exception: pass
    payload["audit_hash_after"] = digest(AUDIT_MODEL)
    payload["audit_unchanged"] = payload["audit_hash_after"] == original_hash
    payload["success"] = all(x.get("success") for x in payload["scenarios"].values()) and payload["audit_unchanged"]
    with open(args.output, "w") as stream: json.dump(payload, stream)
    try: os.remove(TEMP_MODEL)
    except Exception: pass
    return 0 if payload["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
