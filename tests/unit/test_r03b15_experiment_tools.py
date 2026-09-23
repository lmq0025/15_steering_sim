from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "scripts" / "hydraulics" / "r03b15"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from common import (  # noqa: E402
    BASELINE_SHA256,
    ExperimentDataError,
    assert_split_integrity,
    ensure_within,
    error_metrics,
    estimate_linear_slope,
    sha256,
)


EXPERIMENTS = ROOT / "amesim_experiments" / "r03b15"


def test_original_qh1_checksum_is_unchanged() -> None:
    assert sha256(ROOT / "qh1_1.ame") == BASELINE_SHA256


def test_hydvorf_matrix_schema_split_and_ranges() -> None:
    frame = pd.read_csv(EXPERIMENTS / "r03b15_hydvorf_experiment_matrix.csv")
    required = {
        "test_id", "set_role", "source_component", "source_submodel", "method",
        "opening_input", "opening_fraction", "pressure_drop_bar",
        "characteristic_flow_lpm", "characteristic_pressure_drop_bar",
        "critical_flow_number", "measurement_density_kg_m3",
        "measurement_kinematic_viscosity_cst", "provenance",
    }
    assert required <= set(frame.columns)
    assert len(frame) == 346
    assert frame.test_id.is_unique
    assert_split_integrity(frame)
    assert set(frame.set_role) == {"identification", "validation"}
    assert frame.opening_input.between(0, 100).all()
    assert frame.opening_fraction.between(0, 1).all()
    assert (frame.upstream_pressure_bar_g >= 5).all()
    assert (frame.downstream_pressure_bar_g >= 5).all()
    assert (frame.source_submodel == "HYDVORF0").all()
    assert frame.provenance.str.contains("r03a25_resolved_key_parameters.csv", regex=False).all()


def test_hj020_matrix_schema_split_and_orthogonal_subtests() -> None:
    frame = pd.read_csv(EXPERIMENTS / "r03b15_hj020_experiment_matrix.csv")
    required = {
        "test_id", "set_role", "subtest", "x_initial_m", "velocity_mps",
        "q1_lpm", "q2_lpm", "p1_initial_bar_g", "p2_initial_bar_g",
        "duration_s", "output_interval_s", "derivative_window_start_s",
        "derivative_window_end_s", "solver", "relative_tolerance", "provenance",
    }
    assert required <= set(frame.columns)
    assert len(frame) == 186
    assert frame.test_id.is_unique
    assert_split_integrity(frame)
    assert set(frame.subtest) == {
        "B1_fixed_piston_prescribed_flow",
        "B2_zero_flow_prescribed_motion",
        "B3_combined_validation",
    }
    assert (frame.loc[frame.subtest == "B3_combined_validation", "set_role"] == "validation").all()
    assert frame.x_initial_m.between(0, 0.13).all()
    assert frame.provenance.str.contains("r03a25_resolved_key_parameters.csv", regex=False).all()


def test_no_identification_validation_leakage() -> None:
    leaking = pd.DataFrame({"test_id": ["X", "X"], "set_role": ["identification", "validation"]})
    with pytest.raises(ExperimentDataError, match="leakage"):
        assert_split_integrity(leaking)


def test_derivative_estimation_uses_regression() -> None:
    time = np.linspace(0, 0.01, 101)
    pressure = 2.5e7 * time + 3.0e5
    slope = estimate_linear_slope(time, pressure, start_s=0.002, end_s=0.008)
    assert slope == pytest.approx(2.5e7, rel=1.0e-12)
    with pytest.raises(ExperimentDataError):
        estimate_linear_slope([0, 1], [0, 1], start_s=0, end_s=1)


def test_result_template_schemas_are_empty_not_fabricated_results() -> None:
    template_dir = EXPERIMENTS / "results_templates"
    expected = {
        "r03b15_hydvorf_results.csv": {"test_id", "pressure_drop_bar", "flow_lpm"},
        "r03b15_hydvorf_identification.csv": {"test_id", "local_exponent", "residual_lpm"},
        "r03b15_hj020_results.csv": {"test_id", "time_s", "p1_bar_g", "p2_bar_g"},
        "r03b15_hj020_identification.csv": {"test_id", "dp1_dt_pa_s", "beta_eff1_pa"},
        "r03b15_hj020_validation.csv": {"test_id", "predicted_dp1_dt_pa_s", "error1_pa_s"},
    }
    for name, columns in expected.items():
        frame = pd.read_csv(template_dir / name)
        assert columns <= set(frame.columns)
        assert frame.empty


def test_unit_conversion_constants_for_import_boundary() -> None:
    from common import BAR_TO_PA, LPM_TO_M3PS

    assert 1.0 * BAR_TO_PA == pytest.approx(100_000.0)
    assert 60.0 * LPM_TO_M3PS == pytest.approx(1.0e-3)


def test_candidate_metric_evaluation_and_near_zero_relative_guard() -> None:
    metrics = error_metrics([0.0, 1.0, 2.0], [0.01, 1.01, 1.98], relative_floor=0.1)
    assert metrics["mae"] == pytest.approx((0.01 + 0.01 + 0.02) / 3)
    assert metrics["max_relative_error"] == pytest.approx(0.01)


def test_range_guard_rejects_outside_experiment_domain() -> None:
    ensure_within(0.5, 0.0, 1.0, name="opening_fraction")
    with pytest.raises(ExperimentDataError, match="outside frozen range"):
        ensure_within(1.1, 0.0, 1.0, name="opening_fraction")


def test_config_provenance_is_frozen_a25_audit() -> None:
    for name in ["dirvalve_6_sc1.json", "actuator001_hj020.json", "fluid_fp04.json"]:
        payload = json.loads((ROOT / "configs" / "hydraulics" / "r03b1" / name).read_text(encoding="utf-8"))
        assert payload["provenance"]["audit_file"].endswith("r03a25_resolved_key_parameters.csv")


def test_variable_export_list_covers_both_experiments() -> None:
    frame = pd.read_csv(EXPERIMENTS / "r03b15_amesim_variable_export_list.csv")
    assert {"experiment", "variable", "unit", "required", "purpose"} <= set(frame.columns)
    assert set(frame.experiment) == {"HYDVORF0", "HJ020"}
    assert (frame.required == "YES").any()

