from __future__ import print_function

import json
import os
import sys
import traceback

import ame_apy


MODEL = r"E:\15_project\qh1_1_MCP_AUDIT.ame"


def main():
    opened = False
    try:
        ame_apy.AMEInitAPI(False)
        ame_apy.AMEOpenAmeFile(MODEL)
        opened = True
        names = sorted(name for name in dir(ame_apy) if "RunParameter" in name or "Simulation" in name or "Variable" in name)
        payload = {"model_exists": os.path.isfile(MODEL), "api_names": names, "queries": {}}
        for name in ("start_time_s", "stop_time_s", "interval_s", "simulation_mode", "integ_method", "tolerance"):
            try:
                payload["queries"][name] = ame_apy.AMEGetRunParameter(name)
            except Exception as exc:
                payload["queries"][name] = "ERROR: %s" % exc
        for path in ("qout@pump01", "pin@pump01", "pout@pump01", "speed@pump01", "torque@pump01", "press@tank01"):
            try:
                payload["queries"][path] = {"info": ame_apy.AMEGetVariableInfos(path), "values_head": list(ame_apy.AMEGetVariableValues(path))[:3]}
            except Exception as exc:
                payload["queries"][path] = "ERROR: %s" % exc
        text = json.dumps(payload, indent=2, default=str)
        with open(r"E:\15_project\hydraulic_audit\20_probe_amesim.json", "w") as stream:
            stream.write(text)
        print(text)
    except Exception:
        with open(r"E:\15_project\hydraulic_audit\20_probe_amesim_error.txt", "w") as stream:
            traceback.print_exc(file=stream)
        return 1
    finally:
        if opened:
            ame_apy.AMECloseCircuit(False)
        try:
            ame_apy.AMECloseAPI()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
