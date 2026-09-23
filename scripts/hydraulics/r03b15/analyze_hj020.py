"""Analyze HJ020/FP04 prescribed-flow and prescribed-motion experiments."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from common import BAR_TO_PA, LPM_TO_M3PS, ExperimentDataError, assert_split_integrity, error_metrics, estimate_linear_slope, load_json, require_columns


RESULT_COLUMNS = ["test_id", "time_s", "x_m", "velocity_mps", "q1_lpm", "q2_lpm", "p1_bar_g", "p2_bar_g"]
ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = ROOT / "configs" / "hydraulics" / "r03b1" / "actuator001_hj020.json"


def _geometry(config_path: Path) -> dict[str, float]:
    config = load_json(config_path)
    piston_diameter_m = float(config["piston_diameter_mm"]) * 1.0e-3
    rod_diameter_m = float(config["rod_diameter_mm"]) * 1.0e-3
    piston_area = np.pi * piston_diameter_m**2 / 4.0
    rod_area = np.pi * rod_diameter_m**2 / 4.0
    return {
        "piston_area_m2": float(piston_area),
        "annular_area_m2": float(piston_area - rod_area),
        "stroke_m": float(config["stroke_m"]),
        "dead_volume_1_m3": float(config["dead_volume_1_cm3"]) * 1.0e-6,
        "dead_volume_2_m3": float(config["dead_volume_2_cm3"]) * 1.0e-6,
    }


def _volumes(x_m: float, geometry: dict[str, float]) -> tuple[float, float]:
    stroke = geometry["stroke_m"]
    if not 0 <= x_m <= stroke:
        raise ExperimentDataError(f"x={x_m} m outside frozen [0, {stroke}] m stroke")
    return (
        geometry["dead_volume_1_m3"] + geometry["piston_area_m2"] * x_m,
        geometry["dead_volume_2_m3"] + geometry["annular_area_m2"] * (stroke - x_m),
    )


def _nearest_value(points: pd.DataFrame, *, pressure: float, volume: float, value: str) -> float:
    valid = points[np.isfinite(points[value])]
    if valid.empty:
        raise ExperimentDataError(f"no identification points available for {value}")
    pscale = max(float(valid.pressure_bar_g.max() - valid.pressure_bar_g.min()), 1.0)
    vscale = max(float(valid.volume_m3.max() - valid.volume_m3.min()), 1.0e-9)
    distance = ((valid.pressure_bar_g - pressure) / pscale) ** 2 + ((valid.volume_m3 - volume) / vscale) ** 2
    return float(valid.loc[distance.idxmin(), value])


def analyze(matrix_path: Path, results_path: Path, output_dir: Path, config_path: Path = DEFAULT_CONFIG) -> dict:
    geometry = _geometry(config_path)
    matrix = pd.read_csv(matrix_path)
    results = pd.read_csv(results_path)
    require_columns(matrix, ["test_id", "set_role", "subtest", "derivative_window_start_s", "derivative_window_end_s"], label="HJ020 matrix")
    require_columns(results, RESULT_COLUMNS, label="HJ020 results")
    assert_split_integrity(matrix)
    if set(results.test_id) != set(matrix.test_id):
        missing = sorted(set(matrix.test_id) - set(results.test_id))
        extra = sorted(set(results.test_id) - set(matrix.test_id))
        raise ExperimentDataError(f"result/matrix test_id mismatch; missing={missing[:5]}, extra={extra[:5]}")

    summaries = []
    for test_id, signal in results.groupby("test_id", sort=False):
        spec = matrix.loc[matrix.test_id == test_id]
        if len(spec) != 1:
            raise ExperimentDataError(f"matrix must contain exactly one row for {test_id}")
        spec = spec.iloc[0]
        start, end = float(spec.derivative_window_start_s), float(spec.derivative_window_end_s)
        dp1 = estimate_linear_slope(signal.time_s, signal.p1_bar_g * BAR_TO_PA, start_s=start, end_s=end)
        dp2 = estimate_linear_slope(signal.time_s, signal.p2_bar_g * BAR_TO_PA, start_s=start, end_s=end)
        window = signal[(signal.time_s >= start) & (signal.time_s <= end)]
        x = float(window.x_m.mean()); v = float(window.velocity_mps.mean())
        q1 = float(window.q1_lpm.mean()) * LPM_TO_M3PS; q2 = float(window.q2_lpm.mean()) * LPM_TO_M3PS
        p1 = float(window.p1_bar_g.mean()); p2 = float(window.p2_bar_g.mean())
        vol1, vol2 = _volumes(x, geometry)
        summaries.append({
            "test_id": test_id, "set_role": spec.set_role, "subtest": spec.subtest,
            "x_m": x, "velocity_mps": v, "volume1_m3": vol1, "volume2_m3": vol2,
            "q1_m3_s": q1, "q2_m3_s": q2, "p1_bar_g": p1, "p2_bar_g": p2,
            "dp1_dt_pa_s": dp1, "dp2_dt_pa_s": dp2,
        })
    summary = pd.DataFrame(summaries)
    for column in ["compliance1_m3_pa", "compliance2_m3_pa", "beta_eff1_pa", "beta_eff2_pa", "swept_flow1_m3_s", "swept_flow2_m3_s"]:
        summary[column] = np.nan

    b1 = (summary.subtest == "B1_fixed_piston_prescribed_flow") & (summary.set_role == "identification")
    nz1 = b1 & (summary.q1_m3_s != 0) & (summary.dp1_dt_pa_s != 0)
    nz2 = b1 & (summary.q2_m3_s != 0) & (summary.dp2_dt_pa_s != 0)
    summary.loc[nz1, "compliance1_m3_pa"] = summary.loc[nz1, "q1_m3_s"] / summary.loc[nz1, "dp1_dt_pa_s"]
    summary.loc[nz2, "compliance2_m3_pa"] = summary.loc[nz2, "q2_m3_s"] / summary.loc[nz2, "dp2_dt_pa_s"]
    summary.loc[nz1, "beta_eff1_pa"] = summary.loc[nz1, "volume1_m3"] / summary.loc[nz1, "compliance1_m3_pa"]
    summary.loc[nz2, "beta_eff2_pa"] = summary.loc[nz2, "volume2_m3"] / summary.loc[nz2, "compliance2_m3_pa"]

    points1 = summary.loc[nz1, ["p1_bar_g", "volume1_m3", "compliance1_m3_pa"]].rename(columns={"p1_bar_g": "pressure_bar_g", "volume1_m3": "volume_m3"})
    points2 = summary.loc[nz2, ["p2_bar_g", "volume2_m3", "compliance2_m3_pa"]].rename(columns={"p2_bar_g": "pressure_bar_g", "volume2_m3": "volume_m3"})
    b2 = summary.subtest == "B2_zero_flow_prescribed_motion"
    for idx in summary.index[b2]:
        c1 = _nearest_value(points1, pressure=summary.at[idx, "p1_bar_g"], volume=summary.at[idx, "volume1_m3"], value="compliance1_m3_pa")
        c2 = _nearest_value(points2, pressure=summary.at[idx, "p2_bar_g"], volume=summary.at[idx, "volume2_m3"], value="compliance2_m3_pa")
        summary.at[idx, "swept_flow1_m3_s"] = c1 * summary.at[idx, "dp1_dt_pa_s"]
        summary.at[idx, "swept_flow2_m3_s"] = c2 * summary.at[idx, "dp2_dt_pa_s"]

    id_b2 = summary[b2 & (summary.set_role == "identification") & (summary.velocity_mps != 0)]
    ratio1 = float(np.median(id_b2.swept_flow1_m3_s / (geometry["piston_area_m2"] * id_b2.velocity_mps)))
    ratio2 = float(np.median(id_b2.swept_flow2_m3_s / (geometry["annular_area_m2"] * id_b2.velocity_mps)))

    validations = []
    for idx, row in summary[summary.set_role == "validation"].iterrows():
        c1 = _nearest_value(points1, pressure=row.p1_bar_g, volume=row.volume1_m3, value="compliance1_m3_pa")
        c2 = _nearest_value(points2, pressure=row.p2_bar_g, volume=row.volume2_m3, value="compliance2_m3_pa")
        pred1 = (row.q1_m3_s + ratio1 * geometry["piston_area_m2"] * row.velocity_mps) / c1
        pred2 = (row.q2_m3_s + ratio2 * geometry["annular_area_m2"] * row.velocity_mps) / c2
        validations.append({
            "test_id": row.test_id, "subtest": row.subtest,
            "observed_dp1_dt_pa_s": row.dp1_dt_pa_s, "predicted_dp1_dt_pa_s": pred1,
            "observed_dp2_dt_pa_s": row.dp2_dt_pa_s, "predicted_dp2_dt_pa_s": pred2,
            "error1_pa_s": pred1 - row.dp1_dt_pa_s, "error2_pa_s": pred2 - row.dp2_dt_pa_s,
            "within_identified_range": True,
            "notes": "nearest identified compliance plus B2 median swept-flow ratio; diagnostic candidate only",
        })
    validation = pd.DataFrame(validations)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary.to_csv(output_dir / "r03b15_hj020_identification.csv", index=False, encoding="utf-8-sig")
    validation.to_csv(output_dir / "r03b15_hj020_validation.csv", index=False, encoding="utf-8-sig")
    metrics1 = error_metrics(validation.observed_dp1_dt_pa_s, validation.predicted_dp1_dt_pa_s, relative_floor=1.0e3)
    metrics2 = error_metrics(validation.observed_dp2_dt_pa_s, validation.predicted_dp2_dt_pa_s, relative_floor=1.0e3)
    metrics = {"chamber1": metrics1, "chamber2": metrics2, "swept_ratio1": ratio1, "swept_ratio2": ratio2, "candidate_status": "DIAGNOSTIC_ONLY_NOT_APPROVED_FOR_R03B1"}
    (output_dir / "r03b15_hj020_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    plot_specs = [
        ("pressure_time", results, "time_s", ["p1_bar_g", "p2_bar_g"]),
        ("dpdt_vs_q", summary, "q1_m3_s", ["dp1_dt_pa_s"]),
        ("beta_vs_pressure", summary, "p1_bar_g", ["beta_eff1_pa"]),
        ("swept_vs_area_velocity", summary[b2], "velocity_mps", ["swept_flow1_m3_s", "swept_flow2_m3_s"]),
        ("predicted_vs_amesim", validation, "observed_dp1_dt_pa_s", ["predicted_dp1_dt_pa_s"]),
        ("residual_vs_pressure_position", validation.merge(summary[["test_id", "p1_bar_g"]], on="test_id"), "p1_bar_g", ["error1_pa_s", "error2_pa_s"]),
    ]
    for name, frame, xcol, ycols in plot_specs:
        fig, ax = plt.subplots(figsize=(8, 5), constrained_layout=True)
        for ycol in ycols: ax.scatter(frame[xcol], frame[ycol], s=10, label=ycol)
        ax.set_xlabel(xcol); ax.grid(True, alpha=0.3); ax.legend(); fig.savefig(output_dir / f"{name}.png", dpi=180); plt.close(fig)
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("results", type=Path)
    parser.add_argument("--matrix", type=Path, default=Path("amesim_experiments/r03b15/r03b15_hj020_experiment_matrix.csv"))
    parser.add_argument("--output", type=Path, default=Path("outputs/r03b15/hj020"))
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()
    print(json.dumps(analyze(args.matrix, args.results, args.output, args.config), indent=2))


if __name__ == "__main__":
    main()
