"""PHASE J0 closed-loop entry point.

Runs the four J0 operating cases (0 deg / 0 km/h, +2 deg / 5 km/h,
-2 deg / 5 km/h, +5 deg / 10 km/h) through the control -> L1-Fast hydraulic ->
M1 mechanical loop, writes per-case CSV, three figures, and a summary JSON.

The optional ``--diagnostic-damping`` flag adds a fictitious mechanical damper
to the hydraulic load so that the loop structure can be exercised in isolation
from the plant stability question.  Results produced with it are labelled
``J0-DIAG`` and are never reported as an operating-case PASS.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mechanics_ackermann_v2.model import PhaseM1Model  # noqa: E402
from steering_sim.j0_coupling.config import load_j0_config  # noqa: E402
from steering_sim.j0_coupling.reporting import (plot_case, write_samples_csv,  # noqa: E402
                                                write_summary_json)
from steering_sim.j0_coupling.runner import J0Runner  # noqa: E402

DEFAULT_SPEC = ROOT / "mechanical_model_input_spec_v1.0.yaml"
DEFAULT_M1_CONFIG = ROOT / "mechanics_ackermann_v2" / "config.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(ROOT / "configs" / "j0" / "j0_config.json"))
    parser.add_argument("--output", default=str(ROOT / "outputs" / "j0"))
    parser.add_argument("--spec", default=str(DEFAULT_SPEC))
    parser.add_argument("--m1-config", default=str(DEFAULT_M1_CONFIG))
    parser.add_argument("--diagnostic-damping", type=float, default=0.0,
                        help="artificial load damper [N/(m/s)]; labels the run J0-DIAG")
    parser.add_argument("--cases", nargs="*", default=None,
                        help="subset of case ids to run")
    parser.add_argument("--duration", type=float, default=None,
                        help="override the configured case duration [s]")
    args = parser.parse_args()

    config = load_j0_config(args.config)
    geometry_model = PhaseM1Model(args.spec, args.m1_config)
    runner = J0Runner(config, geometry_model)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    cases = [case for case in config.cases
             if args.cases is None or case.id in args.cases]
    if args.duration is not None:
        from steering_sim.j0_coupling.config import J0CaseConfig
        cases = [J0CaseConfig(case.id, case.target_outer_angle_deg, case.speed_kmh,
                              float(args.duration)) for case in cases]
    if not cases:
        raise SystemExit("no J0 cases selected")

    results = []
    for case in cases:
        result = runner.run_case(case, diagnostic_damping_n_s_per_m=args.diagnostic_damping)
        label = case.id if not args.diagnostic_damping else f"{case.id}-DIAG"
        figure_tag = (f"{case.id}_{case.target_outer_angle_deg:+.0f}deg_"
                      f"{case.speed_kmh:.0f}kmh"
                      + ("-DIAG" if args.diagnostic_damping else ""))
        write_samples_csv(result, output / f"{label}_timeseries.csv")
        plot_case(result, output, label=figure_tag)
        results.append(result)
        print(f"{label}: status={result.summary['status']} "
              f"completed={result.completed} "
              f"failure={result.summary.get('failure_reason')}")

    payload = {
        "config": str(config.path),
        "output_dir": str(output),
        "diagnostic_damping_n_s_per_m": args.diagnostic_damping,
        "table_quality": runner.geometry.table_quality(),
        "cases": [result.summary for result in results],
    }
    write_summary_json(payload, output / "j0_summary.json")
    print(json.dumps({"cases": [{"id": item.summary["case_id"],
                                 "status": item.summary["status"],
                                 "notes": item.summary["status_notes"]}
                                for item in results]},
                     indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
