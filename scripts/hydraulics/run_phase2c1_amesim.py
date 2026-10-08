from __future__ import print_function

import argparse
import json
import os
import sys
import time
import traceback

import ame_apy


ROOT = r"E:\15_project"
MODEL = os.path.join(ROOT, "qh1_1_MCP_AUDIT.ame")
REQUEST = os.path.join(ROOT, "hydraulic_audit", "20_amesim_request.json")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    with open(REQUEST, "r") as stream:
        request = json.load(stream)
    payload = {"success": False, "duration_s": args.duration, "model": MODEL, "saved": [], "failed_save": {}, "series": {}, "infos": {}, "failed_extract": {}, "closed_without_save": False}
    opened = False
    original = {}
    try:
        ame_apy.AMEInitAPI(False)
        ame_apy.AMEOpenAmeFile(MODEL)
        opened = True
        for name in ("start_time_s", "stop_time_s", "interval_s", "simulation_mode", "integ_method", "tolerance"):
            try:
                original[name] = ame_apy.AMEGetRunParameter(name)
            except Exception:
                pass
        for path in request["paths"]:
            try:
                ame_apy.AMESaveVariable(path, True)
                payload["saved"].append(path)
            except Exception as exc:
                payload["failed_save"][path] = str(exc)
        ame_apy.AMESetRunParameter("start_time_s", "0")
        ame_apy.AMESetRunParameter("stop_time_s", str(args.duration))
        ame_apy.AMESetRunParameter("interval_s", str(min(0.001, args.duration / 100.0)))
        ame_apy.AMESetRunParameter("simulation_mode", "2")
        started = time.time()
        ame_apy.AMERunSimulation()
        payload["wall_time_s"] = time.time() - started
        for path in request["paths"]:
            try:
                payload["series"][path] = [list(item) for item in ame_apy.AMEGetVariableValues(path)]
                payload["infos"][path] = list(ame_apy.AMEGetVariableInfos(path))
            except Exception as exc:
                payload["failed_extract"][path] = str(exc)
        payload["run_parameters"] = {name: ame_apy.AMEGetRunParameter(name) for name in original}
        payload["success"] = True
    except Exception:
        payload["error"] = traceback.format_exc()
    finally:
        if opened:
            try:
                for name, value in original.items():
                    ame_apy.AMESetRunParameter(name, value)
            except Exception:
                pass
            try:
                ame_apy.AMECloseCircuit(False)
                payload["closed_without_save"] = True
            except Exception:
                payload["close_error"] = traceback.format_exc()
        try:
            ame_apy.AMECloseAPI()
        except Exception:
            pass
    with open(args.output, "w") as stream:
        json.dump(payload, stream)
    return 0 if payload["success"] and payload["closed_without_save"] else 1


if __name__ == "__main__":
    sys.exit(main())
