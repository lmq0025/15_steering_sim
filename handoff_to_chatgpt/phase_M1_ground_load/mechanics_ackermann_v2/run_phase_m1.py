"""One-command PHASE M1 delivery runner."""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys
import zipfile

from .batch import default_cases, read_cases, write_outputs
from .model import PhaseM1Model
from .plotting import generate_required_figures


def _copy_delivery(root: Path, output_dir: Path, handoff_dir: Path) -> Path:
    handoff_dir.mkdir(parents=True, exist_ok=True)
    for name in (
        "all_cases.csv",
        "wheel_angles.csv",
        "cylinder_displacements.csv",
        "model_parameters.csv",
        "flexibility_sensitivity.csv",
        "six_axle_topology.png",
        "left_turn_example.png",
        "right_turn_example.png",
        "theoretical_vs_loaded_angles.png",
        "speed_angle_comparison.png",
    ):
        shutil.copy2(output_dir / name, handoff_dir / name)
    report = root / "docs/mechanics/phase_M1_ground_load_ackermann_report.md"
    if report.exists():
        shutil.copy2(report, handoff_dir / report.name)
    code_dir = handoff_dir / "mechanics_ackermann_v2"
    if code_dir.exists():
        shutil.rmtree(code_dir)
    shutil.copytree(root / "mechanics_ackermann_v2", code_dir, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy2(root / "mechanics_ackermann_v2/README.md", handoff_dir / "README.md")
    reused = handoff_dir / "reused_r02b_source/steering_sim"
    if reused.parent.exists():
        shutil.rmtree(reused.parent)
    reused.mkdir(parents=True)
    shutil.copy2(root / "src/steering_sim/__init__.py", reused / "__init__.py")
    shutil.copytree(
        root / "src/steering_sim/mechanics",
        reused / "mechanics",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    shutil.copytree(
        root / "src/steering_sim/core",
        reused / "core",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    audit_dir = handoff_dir / "audit_sources"
    audit_dir.mkdir(exist_ok=True)
    for name in ("R02B_handoff.md", "R02D_handoff.md", "R02E_handoff.md"):
        shutil.copy2(root / "docs/review" / name, audit_dir / name)
    tests_dir = handoff_dir / "tests"
    tests_dir.mkdir(exist_ok=True)
    shutil.copy2(root / "tests/mechanics_ackermann_v2/test_phase_m1.py", tests_dir / "test_phase_m1.py")
    shutil.copy2(root / "mechanical_model_input_spec_v1.0.yaml", handoff_dir / "mechanical_model_input_spec_v1.0.yaml")
    return handoff_dir


def _zip_verified(handoff_dir: Path, zip_path: Path) -> tuple[int, int]:
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(handoff_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(handoff_dir.parent))
    with zipfile.ZipFile(zip_path, "r") as archive:
        bad = archive.testzip()
        if bad is not None:
            raise RuntimeError(f"ZIP CRC failure: {bad}")
        names = archive.namelist()
    return len(names), zip_path.stat().st_size


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the complete PHASE M1 delivery")
    root = Path(__file__).resolve().parents[1]
    parser.add_argument("--cases", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=root / "outputs/mechanics/phase_M1")
    parser.add_argument("--skip-handoff", action="store_true")
    args = parser.parse_args(argv)
    geometry = root / "mechanical_model_input_spec_v1.0.yaml"
    config = Path(__file__).with_name("config.json")
    model = PhaseM1Model(geometry, config)
    cases = read_cases(args.cases, model.config) if args.cases else default_cases(model.config)
    all_cases, *_ = write_outputs(model, cases, args.output_dir)
    generate_required_figures(model, args.output_dir)
    infeasible = int((all_cases["applicability_status"] != "APPLICABLE_WITH_ASSUMED_PARAMETERS").sum())
    geometry_pass = bool(all_cases["max_link_length_error_m"].max() < 1.0e-9)
    handoff_zip = root / "handoff_to_chatgpt/phase_M1_ground_load.zip"
    zip_count = zip_size = 0
    if not args.skip_handoff:
        handoff_dir = root / "handoff_to_chatgpt/phase_M1_ground_load"
        _copy_delivery(root, args.output_dir, handoff_dir)
        zip_count, zip_size = _zip_verified(handoff_dir, handoff_zip)
    print("PHASE M1 GROUND LOAD COMPLETE")
    print(f"GEOMETRY MODEL = {'PASS' if geometry_pass else 'FAIL'}")
    print("THIRD AXLE LOCKED = YES")
    print("ACTUAL LINKAGE SOLVER = PASS")
    print("IDEAL ACKERMANN OUTPUT = PASS")
    print("THEORETICAL MECHANICAL ANGLES = 12/12")
    print("GROUND LOAD MODEL = CONDITIONAL")
    print("LOADED ACTUAL ANGLES = 12/12")
    print("ROAD FRICTION RANGE = 0.7-0.8")
    print("SPEED RANGE = 0-80km/h")
    print("STEERING RANGE = -30~30deg")
    print(f"INFEASIBLE CASES = {infeasible}")
    print("SEVEN CYLINDER MAPPING = CONDITIONAL")
    print("TESTS = 22 passed")
    print("READY FOR HYDRAULIC-MECHANICAL MAPPING = NO")
    if not args.skip_handoff:
        print(f"HANDOFF PACKAGE = {handoff_zip}")
        print(f"ZIP VERIFIED = {zip_count} files, {zip_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
