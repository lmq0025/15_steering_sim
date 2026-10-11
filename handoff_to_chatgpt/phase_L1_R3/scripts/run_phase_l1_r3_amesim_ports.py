from __future__ import print_function

import hashlib
import importlib.util
import json
import os
import sys

ROOT = r"E:\15_project"
BASE_PATH = os.path.join(ROOT, "scripts", "hydraulics", "run_phase_l1_r2_amesim.py")
spec = importlib.util.spec_from_file_location("r2amesim", BASE_PATH)
r2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r2)
r2.WORK_ROOT = os.path.join(ROOT, "hydraulic_audit_lumped", "amesim_r3_ports_isolated")


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main():
    output = os.path.join(ROOT, "hydraulic_audit_lumped", "33_amesim_sc1_ports_raw.json")
    original = os.path.join(ROOT, "qh1_1.ame")
    audit = os.path.join(ROOT, "qh1_1_MCP_AUDIT.ame")
    before = {original: digest(original), audit: digest(audit)}
    paths = []
    for alias in ("dirvalve_1", "dirvalve_2", "dirvalve_6", "dirvalve_8",
                  "dirvalve_9", "dirvalve_11", "dirvalve_12"):
        paths.extend([
            "signal_input@%s" % alias, "frac_spool_position@%s" % alias,
            "p_P@%s" % alias, "p_T@%s" % alias,
            "p_A@%s" % alias, "p_B@%s" % alias,
            "q_P@%s" % alias, "q_T@%s" % alias,
            "q_A@%s" % alias, "q_B@%s" % alias,
        ])
        for suffix in ("13", "14", "23", "24"):
            paths.extend(["q2@%s.orifice_%s" % (alias, suffix),
                          "marea@%s.orifice_%s" % (alias, suffix)])
    for alias in ("presscontrol01", "presscontrol01_1", "presscontrol01_3"):
        paths.extend(["p1@%s" % alias, "p2@%s" % alias, "q2@%s" % alias])
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
