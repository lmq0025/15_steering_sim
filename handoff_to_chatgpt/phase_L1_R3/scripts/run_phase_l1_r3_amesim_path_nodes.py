from __future__ import print_function

import hashlib
import importlib.util
import json
import os
import sys


ROOT = r"E:\15_project"
BASE_PATH = os.path.join(ROOT, "scripts", "hydraulics", "run_phase_l1_r2_amesim.py")
spec = importlib.util.spec_from_file_location("r2amesim_path", BASE_PATH)
r2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r2)
r2.WORK_ROOT = os.path.join(ROOT, "hydraulic_audit_lumped", "amesim_r3_path_isolated")


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main():
    output = os.path.join(ROOT, "hydraulic_audit_lumped", "33_amesim_path_nodes_raw.json")
    original = os.path.join(ROOT, "qh1_1.ame")
    audit = os.path.join(ROOT, "qh1_1_MCP_AUDIT.ame")
    before = {original: digest(original), audit: digest(audit)}
    paths = []
    for alias in ("pprv_1", "pprv_2", "pprv_3"):
        for name in ("p1", "p2", "p3", "q1", "q2", "q3"):
            paths.append("%s@%s" % (name, alias))
    for alias in ("variableorifice", "variableorifice_1", "variableorifice_2",
                  "variableorifice_9", "variableorifice_10",
                  "variableorifice_11", "variableorifice_12"):
        for name in ("input", "p2", "p3", "q2", "q3"):
            paths.append("%s@%s" % (name, alias))
    scenarios = {}
    if not os.path.isdir(r2.WORK_ROOT):
        os.makedirs(r2.WORK_ROOT)
    for scenario in ("S0", "S1", "S2"):
        scenarios[scenario] = r2.run_scenario(scenario, paths)
    after = {original: digest(original), audit: digest(audit)}
    payload = {
        "success": all(v.get("success") for v in scenarios.values()),
        "protected_hash_before": before,
        "protected_hash_after": after,
        "protected_unchanged": before == after,
        "scenarios": scenarios,
    }
    with open(output, "w") as stream:
        json.dump(payload, stream)
    print(json.dumps({"success": payload["success"],
                      "protected_unchanged": payload["protected_unchanged"],
                      "output": output}))
    return 0 if payload["success"] and payload["protected_unchanged"] else 1


if __name__ == "__main__":
    sys.exit(main())
