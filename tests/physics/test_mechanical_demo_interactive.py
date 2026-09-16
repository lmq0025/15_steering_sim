import csv
import importlib.util
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

import pytest

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "examples"))
spec = importlib.util.spec_from_file_location(
    "mechanical_demo_entry", ROOT / "examples/run_mechanical_demo_interactive.py"
)
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)


@pytest.fixture(scope="module")
def demo():
    if not (ROOT / "mechanical_model_input_spec_v1.0.yaml").exists():
        pytest.skip("CUSTOMER frozen geometry supplied outside Git")
    return entry.run_case()


def test_interactive_left_sign():
    assert entry.signed_command(1.5, "left") == 1.5


def test_interactive_right_sign():
    assert entry.signed_command(1.5, "right") == -1.5


def test_interactive_customer_hint_1p5(demo):
    _, result = demo
    assert result.preset == "CUSTOMER_HINT_BASELINE"
    assert result.target_axle1_mean_angle_deg == 1.5
    assert result.mechanical_output.valid
    assert result.feasible
    assert len(result.mechanical_output.wheel_angles_rad) == 12
    for axle, item in result.axles.items():
        mean = sum(result.mechanical_output.wheel_angles_rad[f"axle{axle}_{s}"]
                   for s in ("POS_Y", "NEG_Y")) / 2
        assert item.actual_mean_rad == pytest.approx(mean, abs=1e-12)
    for name, q in result.q_target_rad.items():
        assert result.mechanical_output.generalized_coordinates[name] == pytest.approx(q, abs=1e-10)


def test_nine_actuator_output(demo):
    _, result = demo
    positions = entry.actuator_positions(result)
    assert len(positions) == 9
    for axle in range(3, 7):
        for side in ("A", "B"):
            assert positions[f"axle{axle}_{side}_stroke_mm"] == pytest.approx(
                getattr(result.actuator_input, f"axle{axle}_{side}").value_m * 1000
            )


def test_axle2_no_actuator(demo):
    assert not any("axle2" in k for k in entry.actuator_positions(demo[1]))


def test_interactive_infeasible_message(demo, capsys):
    coordinator, _ = demo
    coordinator.reset()
    _, result = entry.run_case(angle=2, coordinator=coordinator)
    assert not result.feasible
    entry.print_result(result, "left")
    text = capsys.readouterr().out
    assert "这不是客户机械极限" in text
    assert "建议可展示目标" in text
    assert "largest_feasible_scale" in text
    assert "baseline_mismatch" in text


@pytest.fixture
def saved_directory():
    parent = ROOT / "outputs" / "test_tmp"
    parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="r02e1_", dir=parent) as directory:
        yield Path(directory)


def test_saved_json_schema(demo, saved_directory):
    coordinator, result = demo
    payload = entry.make_payload(result, coordinator, "customer-hint", 1.5, "left")
    jp, cp = saved_directory / "demo.json", saved_directory / "demo.csv"
    entry.save_results(payload, jp, cp)
    saved = json.loads(jp.read_text(encoding="utf-8"))
    assert saved["schema_version"] == "1.0"
    assert saved["signed_command_deg"] == 1.5
    assert len(saved["actual_wheel_angles_deg"]) == 12
    assert len(saved["ideal_wheel_angles_deg"]) == 12
    assert len(saved["actual_axle_mean_angles_deg"]) == 6
    assert len(saved["actuator_positions_mm"]) == 9
    assert len(saved["q_rad"]) == 5
    assert saved["disclaimer"] == "NOT CUSTOMER CALIBRATED"
    assert len(saved["configs"]["coordination"]["sha256"]) == 64
    with cp.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 6
    assert rows[1]["front_mapped_position_mm"] == ""
    assert rows[1]["actuator_A_stroke_mm"] == ""
    assert rows[1]["actuator_B_stroke_mm"] == ""


def test_interactive_prompt_defaults_and_validation(monkeypatch, capsys):
    answers = iter(["bad", "", "-1", "nan", "1.5°", "bad", "左"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert entry.prompt_inputs() == ("customer-hint", 1.5, "left")
    assert "有限的非负数" in capsys.readouterr().out


def test_invalid_command_rejected():
    for invalid in (-1, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            entry.signed_command(invalid, "left")
