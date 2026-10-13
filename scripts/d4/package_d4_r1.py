"""Build the compact PHASE D4-R1 handoff without historical large datasets."""
from __future__ import annotations

from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "handoff_to_chatgpt" / "phase_D4_R1.zip"

EXACT = (
    "start_steering_desktop.bat",
    "requirements-desktop.txt",
    "configs/desktop/d4_r1_response_analysis.json",
    "src/steering_sim/j0_coupling/runner.py",
    "src/steering_sim/demo/service.py",
    "tests/j0_coupling/test_j0_loop.py",
    "docs/desktop/phase_D4_R1_report.md",
    "docs/deployment/OFFLINE_DEPLOYMENT_PLAN.md",
    "docs/deployment/TARGET_DEVICE_INFORMATION.xlsx",
    "outputs/desktop/r1/ramp_acceptance_summary.json",
    "outputs/desktop/r1/ramp_acceptance_summary.csv",
    "outputs/desktop/r1/ramp_timestep_validation.json",
    "outputs/desktop/r1/ramp_gui_acceptance.json",
    "outputs/desktop/r1/ramp_timeseries_0_to_2.csv",
)
TREES = (
    "src/steering_sim/desktop",
    "scripts/d4",
    "tests/desktop",
)
PATTERNS = (
    "outputs/desktop/r1/*.png",
    "outputs/desktop/r1/*response_times*.csv",
    "outputs/desktop/logs/*.log",
)


def members() -> list[Path]:
    paths = [ROOT / item for item in EXACT]
    for tree in TREES:
        paths.extend(path for path in (ROOT / tree).rglob("*") if path.is_file()
                     and "__pycache__" not in path.parts)
    for pattern in PATTERNS:
        paths.extend(ROOT.glob(pattern))
    return sorted({path.resolve() for path in paths if path.is_file()})


def main() -> None:
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    files = members()
    manifest = "\n".join(str(path.relative_to(ROOT)).replace("\\", "/") for path in files)
    with zipfile.ZipFile(TARGET, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=6) as archive:
        for path in files:
            archive.write(path, path.relative_to(ROOT))
        archive.writestr("D4_R1_MANIFEST.txt", manifest + "\n")
    with zipfile.ZipFile(TARGET) as archive:
        bad = archive.testzip()
        if bad is not None:
            raise RuntimeError(f"ZIP integrity failure: {bad}")
        print(f"{TARGET} files={len(archive.namelist())} bytes={TARGET.stat().st_size}")


if __name__ == "__main__":
    main()
