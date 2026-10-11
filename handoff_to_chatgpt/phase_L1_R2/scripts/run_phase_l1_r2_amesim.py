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
WORK_ROOT = os.path.join(ROOT, "hydraulic_audit_lumped", "amesim_r2_isolated")
MODEL_NAME = "qh1_1_MCP_AUDIT.ame"  # preserve embedded Amesim system name
SOURCE = "dirvalve_1_piecewiselinear_5"
STEP_SOURCE = "step"
SINE_SOURCE = "sinewave_1"


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def setv(alias, name, value):
    ame_apy.AMESetParameterValue("%s@%s" % (name, alias), str(value))


def configure(scenario):
    if scenario == "S0":
        return
    if scenario == "S1":
        # Existing STEP0 source; scalar edits do not change model structure.
        setv(STEP_SOURCE, "out0", 0.0)
        setv(STEP_SOURCE, "out1", -0.10)
        setv(STEP_SOURCE, "t0", 0.05)
        setv(STEP_SOURCE, "td", 0.001)
        return
    elif scenario == "S2":
        # Existing SIN0 source; Python will replay the measured downstream
        # valve input, so intermediate signal-chain gains remain observable.
        setv(SINE_SOURCE, "a", 0.10)
        setv(SINE_SOURCE, "f", 1.0)
        setv(SINE_SOURCE, "level0", 0.0)
        setv(SINE_SOURCE, "phi", 0.0)
        return
    else:
        raise ValueError(scenario)


def collect_logs(folder):
    result = {}
    for base, _, files in os.walk(folder):
        for name in files:
            path = os.path.join(base, name)
            ext = os.path.splitext(name)[1].lower()
            if ext not in (".log", ".err", ".out", ".txt"):
                continue
            try:
                if os.path.getsize(path) > 2 * 1024 * 1024:
                    continue
                with open(path, "r") as stream:
                    result[os.path.relpath(path, folder)] = stream.read()
            except Exception as exc:
                result[os.path.relpath(path, folder)] = "LOG_READ_ERROR: %s" % exc
    return result


def run_scenario(scenario, paths):
    folder = os.path.join(WORK_ROOT, scenario)
    if os.path.isdir(folder):
        shutil.rmtree(folder)
    os.makedirs(folder)
    model = os.path.join(folder, MODEL_NAME)
    shutil.copy2(AUDIT_MODEL, model)
    opened = False
    started = time.time()
    record = {"success": False, "scenario": scenario, "work_dir": folder,
              "model_copy": model, "model_copy_hash_before": digest(model)}
    cwd = os.getcwd()
    try:
        os.chdir(folder)
        ame_apy.AMEInitAPI(False)
        ame_apy.AMESubscribeToLogFile(os.path.join(folder, "ame_api.log"), False)
        ame_apy.AMEOpenAmeFile(model)
        opened = True
        configure(scenario)
        if scenario != "S0":
            # Persist only the isolated copy.  Generated simulation artifacts
            # otherwise continue to reference the pre-change parameter set.
            ame_apy.AMESaveCircuit()
            ame_apy.AMEGenerateCode()
        for path in paths:
            try:
                ame_apy.AMESaveVariable(path, True)
            except Exception:
                pass
        ame_apy.AMESetRunParameter("start_time_s", "0")
        ame_apy.AMESetRunParameter("stop_time_s", "1")
        ame_apy.AMESetRunParameter("interval_s", "0.001")
        ame_apy.AMESetRunParameter("simulation_mode", "2")
        simulation_started = time.time()
        ame_apy.AMERunSimulation()
        record["simulation_wall_time_s"] = time.time() - simulation_started
        series, infos, failed = {}, {}, {}
        for path in paths:
            try:
                series[path] = [list(item) for item in ame_apy.AMEGetVariableValues(path)]
                infos[path] = list(ame_apy.AMEGetVariableInfos(path))
            except Exception:
                failed[path] = traceback.format_exc()
        record.update({"success": True, "series": series, "infos": infos,
                       "failed_variables": failed})
    except Exception as exc:
        record.update({"exception_type": type(exc).__name__, "error": str(exc),
                       "stack_trace": traceback.format_exc()})
    finally:
        if opened:
            try:
                ame_apy.AMECloseCircuit(False)
                record["closed_without_save"] = True
            except Exception:
                record["close_error"] = traceback.format_exc()
        try:
            ame_apy.AMECloseAPI()
        except Exception:
            record["api_close_error"] = traceback.format_exc()
        os.chdir(cwd)
        record["wall_time_s"] = time.time() - started
        record["logs"] = collect_logs(folder)
        record["generated_files"] = sorted(
            os.path.relpath(os.path.join(base, name), folder)
            for base, _, files in os.walk(folder) for name in files)
        record["model_copy_hash_after"] = digest(model) if os.path.exists(model) else None
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if not os.path.isdir(WORK_ROOT):
        os.makedirs(WORK_ROOT)
    original_hash = digest(AUDIT_MODEL)
    paths = [
        "output@%s" % SOURCE, "signal_input@dirvalve_6", "frac_spool_position@dirvalve_6",
        "out@%s" % STEP_SOURCE, "output@%s" % SINE_SOURCE,
        "speed@pump01", "qout@pump01", "pin@pump01", "pout@pump01", "torque@pump01",
        "speed@pump01_1", "qout@pump01_1", "pin@pump01_1", "pout@pump01_1",
        "p1@actuator002", "p2@actuator002", "frod@actuator002", "x@actuator002", "v@actuator002",
        "q2@dirvalve_6.orifice_13", "q2@dirvalve_6.orifice_14",
        "q2@dirvalve_6.orifice_23", "q2@dirvalve_6.orifice_24",
        "q2@presscontrol01", "q2@presscontrol01_1", "press@tank01",
    ]
    for alias in ("dirvalve_1", "dirvalve_2", "dirvalve_8", "dirvalve_9",
                  "dirvalve_11", "dirvalve_12"):
        paths.extend(("signal_input@%s" % alias, "frac_spool_position@%s" % alias))
    for alias in ("actuator001", "actuator001_1", "actuator001_2"):
        paths.extend(("p1@%s" % alias, "p2@%s" % alias, "frod@%s" % alias,
                      "x@%s" % alias, "v@%s" % alias))
    for alias in ("pump01_2", "pump01_3"):
        paths.extend(("speed@%s" % alias, "qout@%s" % alias, "pout@%s" % alias))
    scenarios = {}
    for scenario in ("S0", "S1", "S2"):
        scenarios[scenario] = run_scenario(scenario, paths)
    final_hash = digest(AUDIT_MODEL)
    payload = {
        "success": all(v.get("success") for v in scenarios.values()),
        "exit_status": 0 if all(v.get("success") for v in scenarios.values()) else 1,
        "audit_model": AUDIT_MODEL,
        "audit_hash_before": original_hash,
        "audit_hash_after": final_hash,
        "audit_unchanged": original_hash == final_hash,
        "scenarios": scenarios,
    }
    with open(args.output, "w") as stream:
        json.dump(payload, stream)
    return payload["exit_status"]


if __name__ == "__main__":
    sys.exit(main())
