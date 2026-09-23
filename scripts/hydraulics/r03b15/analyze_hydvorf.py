"""Analyze manually exported HYDVORF0 characterization results.

No constitutive relationship is assumed before data are loaded.  The fitted
signed power law is emitted only as a diagnostic candidate for review; it is
not an approved R03-B1 implementation.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from common import ExperimentDataError, assert_split_integrity, assert_unique, error_metrics, require_columns


RESULT_COLUMNS = [
    "test_id", "opening_input", "upstream_pressure_bar_g", "downstream_pressure_bar_g",
    "pressure_drop_bar", "flow_lpm",
]


def _fit_by_opening(identification: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for opening, group in identification.groupby("opening_input"):
        usable = group[(group["pressure_drop_bar"].abs() > 0) & (group["flow_lpm"].abs() > 0)]
        if len(usable) < 4:
            continue
        x = np.log(usable["pressure_drop_bar"].abs().to_numpy(float))
        y = np.log(usable["flow_lpm"].abs().to_numpy(float))
        exponent, log_gain = np.polyfit(x, y, 1)
        rows.append({"opening_input": opening, "gain_lpm_per_bar_power": float(np.exp(log_gain)), "pressure_exponent": float(exponent), "point_count": len(usable)})
    if not rows:
        raise ExperimentDataError("no opening has enough non-zero identification points")
    return pd.DataFrame(rows).sort_values("opening_input")


def _predict(frame: pd.DataFrame, fits: pd.DataFrame) -> np.ndarray:
    opening_axis = fits["opening_input"].to_numpy(float)
    gains = fits["gain_lpm_per_bar_power"].to_numpy(float)
    exponents = fits["pressure_exponent"].to_numpy(float)
    opening = frame["opening_input"].to_numpy(float)
    dp = frame["pressure_drop_bar"].to_numpy(float)
    gain = np.interp(opening, opening_axis, gains)
    exponent = np.interp(opening, opening_axis, exponents)
    return np.sign(dp) * gain * np.power(np.abs(dp), exponent)


def _local_exponent(frame: pd.DataFrame) -> pd.Series:
    result = pd.Series(np.nan, index=frame.index, dtype=float)
    for (_, sign), group in frame[frame["pressure_drop_bar"] != 0].groupby([
        "opening_input", np.sign(frame.loc[frame["pressure_drop_bar"] != 0, "pressure_drop_bar"])
    ]):
        usable = group[group["flow_lpm"].abs() > 0].sort_values("pressure_drop_bar", key=lambda s: s.abs())
        if len(usable) >= 3:
            x = np.log(usable["pressure_drop_bar"].abs().to_numpy(float))
            y = np.log(usable["flow_lpm"].abs().to_numpy(float))
            result.loc[usable.index] = np.gradient(y, x)
    return result


def analyze(matrix_path: Path, results_path: Path, output_dir: Path) -> dict:
    matrix = pd.read_csv(matrix_path)
    results = pd.read_csv(results_path)
    require_columns(matrix, ["test_id", "set_role", "opening_input", "pressure_drop_bar"], label="HYDVORF0 matrix")
    require_columns(results, RESULT_COLUMNS, label="HYDVORF0 results")
    assert_unique(matrix, "test_id", label="HYDVORF0 matrix")
    assert_unique(results, "test_id", label="HYDVORF0 static results")
    assert_split_integrity(matrix)
    unknown = sorted(set(results.test_id) - set(matrix.test_id))
    if unknown:
        raise ExperimentDataError(f"results contain test_id not present in matrix: {unknown[:5]}")
    if set(results.test_id) != set(matrix.test_id):
        missing = sorted(set(matrix.test_id) - set(results.test_id))
        raise ExperimentDataError(f"results incomplete; missing {len(missing)} test_ids, first: {missing[:5]}")

    observed = matrix[["test_id", "set_role"]].merge(results, on="test_id", validate="one_to_one")
    observed["sign_consistent"] = (np.sign(observed.flow_lpm) == np.sign(observed.pressure_drop_bar)) | ((observed.flow_lpm == 0) & (observed.pressure_drop_bar == 0))
    observed["local_exponent"] = _local_exponent(observed)
    identification = observed[observed.set_role == "identification"].copy()
    validation = observed[observed.set_role == "validation"].copy()
    fits = _fit_by_opening(identification)
    observed["candidate_flow_lpm"] = _predict(observed, fits)
    observed["residual_lpm"] = observed.candidate_flow_lpm - observed.flow_lpm

    output_dir.mkdir(parents=True, exist_ok=True)
    observed.to_csv(output_dir / "r03b15_hydvorf_identification.csv", index=False, encoding="utf-8-sig")
    fits.to_csv(output_dir / "r03b15_hydvorf_candidate_parameters.csv", index=False, encoding="utf-8-sig")
    metrics = error_metrics(
        validation.flow_lpm,
        observed.loc[validation.index, "candidate_flow_lpm"],
        relative_floor=max(1.0e-6, 0.01 * observed.flow_lpm.abs().max()),
    )
    characteristic = observed[(observed.opening_input == 100) & np.isclose(observed.pressure_drop_bar, 1.0)]
    metrics.update({
        "identification_count": int(len(identification)), "validation_count": int(len(validation)),
        "sign_mismatch_count": int((~observed.sign_consistent).sum()),
        "zero_dp_max_abs_flow_lpm": float(observed.loc[observed.pressure_drop_bar == 0, "flow_lpm"].abs().max()),
        "zero_opening_max_abs_flow_lpm": float(observed.loc[observed.opening_input == 0, "flow_lpm"].abs().max()),
        "characteristic_point_flow_lpm": float(characteristic.flow_lpm.iloc[0]) if len(characteristic) == 1 else None,
        "candidate_status": "DIAGNOSTIC_ONLY_NOT_APPROVED_FOR_R03B1",
    })
    (output_dir / "r03b15_hydvorf_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    nonzero = observed[(observed.pressure_drop_bar != 0) & (observed.flow_lpm != 0)]
    plots = [
        ("q_vs_dp", "pressure_drop_bar", "flow_lpm", False, False),
        ("abs_q_vs_abs_dp_loglog", "abs_dp", "abs_q", True, True),
        ("local_exponent_vs_abs_dp", "abs_dp", "local_exponent", True, False),
        ("q_vs_opening", "opening_input", "flow_lpm", False, False),
        ("candidate_residual", "pressure_drop_bar", "residual_lpm", False, False),
    ]
    plot_frame = observed.assign(abs_dp=observed.pressure_drop_bar.abs(), abs_q=observed.flow_lpm.abs())
    for name, xcol, ycol, logx, logy in plots:
        data = plot_frame if "abs" not in name and "exponent" not in name else nonzero.assign(abs_dp=nonzero.pressure_drop_bar.abs(), abs_q=nonzero.flow_lpm.abs())
        fig, ax = plt.subplots(figsize=(8, 5), constrained_layout=True)
        for opening, group in data.groupby("opening_input"):
            ax.scatter(group[xcol], group[ycol], s=12, label=f"opening={opening:g}")
        if logx: ax.set_xscale("log")
        if logy: ax.set_yscale("log")
        ax.set_xlabel(xcol); ax.set_ylabel(ycol); ax.grid(True, alpha=0.3)
        if data.opening_input.nunique() <= 10: ax.legend(fontsize=7, ncol=2)
        fig.savefig(output_dir / f"{name}.png", dpi=180)
        plt.close(fig)
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("results", type=Path)
    parser.add_argument("--matrix", type=Path, default=Path("amesim_experiments/r03b15/r03b15_hydvorf_experiment_matrix.csv"))
    parser.add_argument("--output", type=Path, default=Path("outputs/r03b15/hydvorf"))
    args = parser.parse_args()
    metrics = analyze(args.matrix, args.results, args.output)
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()

