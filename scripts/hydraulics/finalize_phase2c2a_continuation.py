from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "hydraulic_audit"


def read_csv(name: str) -> list[dict[str, str]]:
    with (AUDIT/name).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(name: str, rows: list[dict[str, str]]) -> None:
    with (AUDIT/name).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def main() -> None:
    # The source-geometry line mapping and the capped HL012 trial were not
    # accepted: the former was unstable and the latter regressed comparison
    # counts. Preserve their evidence in 21P/Q/R, but keep C2A-3 as runtime.
    write_csv("21U_final_pressure_path_timeseries.csv", read_csv("21L_post_pressure_control_timeseries.csv"))
    write_csv("21V_final_comparison_metrics.csv", read_csv("21M_post_pressure_control_metrics.csv"))
    write_csv("21W_final_error_attribution.csv", read_csv("21N_post_pressure_control_error_attribution.csv"))
    c2a = json.loads((AUDIT/"21O_phase2C2A_results.json").read_text(encoding="utf-8"))
    stages = read_csv("21R_line_calibration_steps.csv")
    trial = next(row for row in stages if row["stage"] == "C2A-5D_HL012")
    hashes = {name: hashlib.sha256((AUDIT/name).read_bytes()).hexdigest() for name in (
        "17A_bondgraph_elements_v3.csv", "17B_bondgraph_ports_v3.csv", "17C_bondgraph_junctions_v3.csv",
        "17D_physical_line_registry.csv", "17F_BONDGRAPH_IR_FREEZE_V3.md")}
    payload = {
        "pytest": "pending final full-suite rerun",
        "fast_states": 109, "fast_line_states": 67, "ir_v3_changed": False, "ir_v3_hashes": hashes,
        "pressure_reference_fix": "PASS", "tank_exact_boundary": "PASS", "cv010_si_law": "PASS", "rv010_si_law": "PASS",
        "amesim_max_pump_pressure_pa": c2a["baseline"]["amesim_max_pump_pressure_pa"],
        "python_before_pa": c2a["baseline"]["python_max_pump_pressure_pa"],
        "python_final_accepted_pa": c2a["after"]["python_max_pump_pressure_pa"],
        "pressure_ratio": c2a["after"]["pressure_ratio_to_amesim"],
        "line_interface": {
            "audit": "PASS", "extra_artificial_drop_found": True, "largest_family": "HL012",
            "calibration": "FAIL_REJECTED",
            "stable_capped_trial_peak_pa": float(trial["max_pump_pressure_pa"]),
            "stable_capped_trial_comparison": {"good": int(trial["good"]), "acceptable": int(trial["acceptable"]), "poor": int(trial["poor"])},
            "rejection_reason": "source-equivalent mapping unstable; stable cap reduced peak only 5.5% and regressed GOOD/POOR counts",
        },
        "hydort0": {"status": "FAIL_REJECTED", "reason": "isolated table law passes 0.1 s but 1 s produces NaN/Inf in HA001 coupling"},
        "hydorf0": {"status": "NOT_RUN", "reason": "HYDORT0 stability gate failed"},
        "opening": c2a["opening"], "comparison": c2a["comparison"],
        "pump_flow_regression": c2a["regression"]["pump_flow_still_good"],
        "algebraic_failures_accepted": c2a["algebraic_failures"],
        "topology_issue": False, "sign_issue": False, "remaining_unit_issue": False,
        "ready_for_sc1_calibration": False,
        "stop_condition": "Source-equivalent line/path resistance caused structural HA001-coupled instability without changing IR/states; capped substitute failed accuracy regression",
    }
    (AUDIT/"21X_phase2C2A_final_results.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
