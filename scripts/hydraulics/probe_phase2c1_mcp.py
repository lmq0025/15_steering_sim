from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MCP = ROOT / "tools" / "Simcenter-Amesim-MCP"
sys.path.insert(0, str(MCP))

from amesim_mcp.amesim_api import AmesimConnection


def main() -> None:
    connection = AmesimConnection()
    try:
        print(connection.connect("2021.1", 18862))
        code = r'''
import json
payload = {}
opened = False
try:
    ame_apy.AMEOpenAmeFile(r"E:\15_project\qh1_1_MCP_AUDIT.ame")
    opened = True
    payload["api_names"] = sorted([name for name in dir(ame_apy) if "RunParameter" in name or "Simulation" in name or "Variable" in name])
    payload["queries"] = {}
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
finally:
    if opened:
        ame_apy.AMECloseCircuit(False)
print(json.dumps(payload, default=str))
'''
        raw = connection.execute_python(code)
        (ROOT / "hydraulic_audit" / "20_probe_amesim.json").write_text(raw, encoding="utf-8")
        print(raw)
    finally:
        print(connection.disconnect())


if __name__ == "__main__":
    main()
