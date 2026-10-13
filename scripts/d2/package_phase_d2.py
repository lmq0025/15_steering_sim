"""Create the auditable PHASE D2 handoff archive."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[2]
DESTINATION = ROOT / "handoff_to_chatgpt" / "phase_D2.zip"

INCLUDE = (
    "CLAUDE.md",
    "src/steering_sim/degradation",
    "src/steering_sim/quality_assessment",
    "src/steering_sim/hydraulics_engineering",
    "src/steering_sim/j0_coupling/runner.py",
    "src/steering_sim/demo/assessment.py",
    "src/steering_sim/demo/degradation.py",
    "configs/degradation",
    "configs/j0/j0_config.json",
    "configs/j1r2/engineering_hydraulics.json",
    "configs/j1/engineering_mechanism.json",
    "configs/j1/engineering_config.json",
    "mechanical_model_input_spec_v1.0.yaml",
    "mechanics_ackermann_v2/config.json",
    "mechanics_ackermann_redesigned/config.json",
    "data/degradation",
    "scripts/d1",
    "scripts/d2",
    "tests/degradation",
    "tests/quality_assessment",
    "tests/hydraulics_engineering",
    "tests/j0_coupling",
    "tests/demo/test_j1r2_ui_and_batch.py",
    "outputs/degradation/phase_D1",
    "outputs/degradation/phase_D2",
    "docs/degradation/phase_D1_report.md",
    "docs/degradation/phase_D2_report.md",
    "docs/handoff/CODEX_HANDOFF_20261012.md",
    "docs/handoff/codex_interface_map.json",
    "docs/handoff/degradation_interface_audit.csv",
    "docs/handoff/degradation_feature_sources.csv",
    "docs/handoff/codex_handoff_baseline.json",
)


def files() -> list[Path]:
    result: list[Path] = []
    for relative in INCLUDE:
        item = ROOT / relative
        if not item.exists():
            raise FileNotFoundError(item)
        candidates = item.rglob("*") if item.is_dir() else (item,)
        result.extend(path for path in candidates if path.is_file()
                      and "__pycache__" not in path.parts
                      and path.suffix not in (".pyc", ".pyo"))
    return sorted(set(result), key=lambda path: path.as_posix())


def main() -> int:
    selected = files()
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    manifest = []
    with zipfile.ZipFile(DESTINATION, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9) as archive:
        for source in selected:
            relative = source.relative_to(ROOT).as_posix()
            data = source.read_bytes()
            archive.writestr(relative, data)
            manifest.append({
                "path": relative, "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest()})
        archive.writestr(
            "MANIFEST.json",
            json.dumps({
                "phase": "D2",
                "file_count_excluding_manifest": len(manifest),
                "files": manifest,
            }, ensure_ascii=False, indent=2).encode("utf-8"))
    print(json.dumps({
        "archive": str(DESTINATION),
        "size": DESTINATION.stat().st_size,
        "sha256": hashlib.sha256(DESTINATION.read_bytes()).hexdigest(),
        "files": len(manifest) + 1,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
