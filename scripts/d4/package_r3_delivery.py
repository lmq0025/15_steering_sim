"""Package verified D4-R3 increments; never turn an unfinished run into PASS.

Run with the engineering Python after the final report and frozen-source test
run have completed. This is an update for the existing project, not a standalone
application or a replacement for the repository's historical deliveries.
"""
from __future__ import annotations

from datetime import datetime
import csv
import hashlib
import json
from pathlib import Path
import shutil
import sys
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs/desktop/r3"
TARGET = ROOT / "handoff_to_chatgpt/phase_D4_R3.zip"
EXPECTED_PYTHON = Path(r"E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe")
RESULT_EXTENSIONS = {".json", ".csv", ".xlsx", ".npz", ".png", ".md", ".log", ".txt"}


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict:
    if not path.is_file():
        raise RuntimeError(f"Required acceptance record is missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def inside_project(path: str | Path) -> Path:
    value = Path(path).resolve()
    if not value.is_relative_to(ROOT.resolve()):
        raise RuntimeError(f"Delivery input is outside the project: {value}")
    return value


def checked_pass(path: Path) -> dict:
    value = read_json(path)
    if value.get("status") != "PASS":
        raise RuntimeError(f"Acceptance is not PASS: {path}")
    return value


def junit_counts(path: Path) -> dict:
    if not path.is_file():
        raise RuntimeError(f"Required JUnit evidence is missing: {path}")
    tree = ET.parse(path)
    cases = list(tree.getroot().iter("testcase"))
    counts = {"tests": len(cases), "passed": 0, "skipped": 0, "failed": 0, "errors": 0}
    for case in cases:
        if case.find("error") is not None:
            counts["errors"] += 1
        elif case.find("failure") is not None:
            counts["failed"] += 1
        elif case.find("skipped") is not None:
            counts["skipped"] += 1
        else:
            counts["passed"] += 1
    if not cases or counts["failed"] or counts["errors"]:
        raise RuntimeError(f"JUnit evidence has no cases or has failures/errors: {path}: {counts}")
    return counts


def main() -> None:
    if Path(sys.executable).resolve() != EXPECTED_PYTHON.resolve():
        raise RuntimeError(f"Use the engineering Python only; actual: {sys.executable}")

    full = checked_pass(OUT / "full_repository_run_status.json")
    if not full.get("source_hashes_unchanged") or full.get("returncode") != 0:
        raise RuntimeError("The final full-repository run was not successful on frozen sources")
    frozen = full.get("source_hashes_after", {})
    if not frozen or frozen != full.get("source_hashes_before"):
        raise RuntimeError("Missing or unequal before/after frozen source hashes")
    changed = [name for name, digest in frozen.items()
               if not (ROOT / name).is_file() or sha(ROOT / name) != digest]
    if changed:
        raise RuntimeError("Source changed after the final test run: " + ", ".join(changed))
    full_counts = junit_counts(OUT / "full_repository.xml")
    targeted_counts = junit_counts(OUT / "final_targeted.xml")

    gui = checked_pass(OUT / "gui/acceptance.json")
    checked_pass(OUT / "gui/final_views/evidence.json")
    live = checked_pass(OUT / "a_live/acceptance.json")
    bat = checked_pass(OUT / "formal_bat_acceptance.json")
    audit = checked_pass(OUT / "baseline_final_audit.json")
    checked_pass(OUT / "result_data_audit.json")
    baseline = read_json(OUT / "baseline.json")
    for name, digest in baseline["protected"].items():
        if sha(ROOT / name) != digest:
            raise RuntimeError(f"Protected baseline changed: {name}")
    audited_protected = audit.get("protected", {})
    if set(audited_protected) != set(baseline["protected"]) or not all(
            item.get("unchanged") for item in audited_protected.values()):
        raise RuntimeError("Protected baseline audit is incomplete or failed")
    core = {name: digest for name, digest in baseline["source_hashes"].items()
            if "/hydraulics_engineering/" in name or "/j0_coupling/" in name}
    if not core or not all(audit.get("hydraulic_and_coupling_source_unchanged", {}).get(name)
                           and sha(ROOT / name) == digest for name, digest in core.items()):
        raise RuntimeError("Hydraulic/coupling source audit is incomplete or failed")

    report = ROOT / "docs/desktop/phase_D4_R3_report.md"
    if not report.is_file() or not report.stat().st_size:
        raise RuntimeError("The final D4-R3 report has not been written")
    if '待最终填入' in report.read_text(encoding='utf-8'):
        raise RuntimeError('The R3 report is still a staged draft')
    if read_json(OUT/'progress.json').get('status')!='COMPLETE':
        raise RuntimeError('R3 progress has not been finalized from actual evidence')

    files: set[Path] = set()

    def add(path: str | Path, *, required: bool = False) -> None:
        value = inside_project(path)
        if not value.is_file():
            if required:
                raise RuntimeError(f"Required delivery file is missing: {value}")
            return
        if "__pycache__" in value.parts or value.suffix == ".pyc" or value.name == "failure.txt":
            return
        files.add(value)

    def tree(folder: str | Path, extensions: set[str]) -> None:
        folder = inside_project(folder)
        for path in folder.rglob("*"):
            if path.is_file() and path.suffix.lower() in extensions:
                add(path)

    # Include the R2 interfaces required by R3, without shipping old R2 results.
    for folder in ("src/steering_sim/desktop", "src/steering_sim/degradation",
                   "src/steering_sim/quality_assessment", "tests/desktop"):
        tree(ROOT / folder, {".py", ".svg"})
    tree(ROOT / "data/degradation/r2", {".csv", ".xlsx", ".json"})
    for relative in ("src/steering_sim/j0_coupling/runner.py",
                     "src/steering_sim/j0_coupling/angle_reference.py",
                     "src/steering_sim/demo/service.py", "scripts/d3/run_phase_d3.py",
                     "pyproject.toml", "requirements-desktop.txt", "start_steering_desktop.bat",
                     "configs/desktop/d4_r1_response_analysis.json",
                     "configs/desktop/d4_r2_response_analysis.json",
                     "tests/degradation/test_d3_rul.py",
                     "outputs/desktop/r3/baseline_r2/src/steering_sim/degradation/stochastic.py"):
        add(ROOT / relative, required=True)
    for relative in baseline["protected"]:
        add(ROOT / relative, required=True)
    for path in (ROOT / "scripts/d4").glob("*r3*.py"):
        add(path)
    for name in ("launch_desktop.py", "check_desktop_environment.py", "build_pyinstaller.ps1"):
        add(ROOT / "scripts/d4" / name, required=True)
    add(report, required=True)
    # Use per-run immutable mission_input snapshots below, not the global
    # working table which tests or a later unsaved edit may legitimately change.

    # Exact full-run/test records, not an aggregation of interrupted runs.
    for name in ("baseline.json", "baseline_final_audit.json", "formal_bat_acceptance.json",
                 "full_repository.xml", "full_repository.log", "full_repository_run_status.json",
                 "final_targeted.xml", "progress.json", "result_data_audit.json", "README.md", "bat_main.png", "bat_restart.png"):
        add(OUT / name, required=True)
    for name in ('a_existing_tests.xml','bc_tests.xml','r3_targeted.xml',
                 'subagent_light_tests_retry.xml','subagent_followup_retry.xml','isolated_tk.xml'):
        add(OUT/name)

    # One real 0.5-ms 2-degree run and its explicit saved-project record reference.
    if live.get("source") != "LIVE_QT_QTHREAD_FULL_22_STATE":
        raise RuntimeError("The live ramp record is not a full 22-state Qt calculation")
    live_csv = inside_project(live["csv_path"])
    add(live_csv, required=True)
    tree(OUT / "a_live", RESULT_EXTENSIONS)
    live_project_path = OUT / "a_live/实时两度斜坡.d4project.json"
    live_project = read_json(live_project_path)
    reference = live_project["page_inputs"]["simulation"]["record_reference"]
    if inside_project(reference["csv_path"]) != live_csv or sha(live_csv) != reference["csv_sha256"]:
        raise RuntimeError("The saved live project does not match the actual integration CSV")

    # Screenshots, Chinese reports, plots and tables from this acceptance only.
    for path in (OUT / "gui").iterdir():
        if path.is_file() and path.suffix.lower() in RESULT_EXTENSIONS:
            add(path)
    tree(OUT / "gui/final_views", RESULT_EXTENSIONS)
    for folder in (OUT / "gui").glob("*_images"):
        tree(folder, {".png"})
    for name in gui.get("screenshots", []):
        add(name, required=True)

    forecasts: dict[int, Path] = {}
    quality_outputs: list[Path] = []
    rul_outputs: list[Path] = []
    for task in gui.get("tasks", []):
        if not task.get("output_dir"):
            continue
        source = inside_project(task["output_dir"])
        if task["task"] == "degradation":
            metadata = read_json(source / "metadata.json")
            count = int(metadata["sample_count"])
            if task.get("sample_count") != count:
                raise RuntimeError("GUI forecast path count does not match generated metadata")
            forecasts[count] = source
        elif task["task"] == "quality":
            quality_outputs.append(source)
        elif task["task"] == "rul":
            rul_outputs.append(source)
    if not {128, 1000}.issubset(forecasts) or not quality_outputs or not rul_outputs:
        raise RuntimeError("Missing actual 128/1000-path, paired-quality or RUL GUI calculation")
    for count in (128, 1000):
        source = forecasts[count]
        for name in ("metadata.json", "twenty_mode_and_parameters.csv", "final_twenty_state.json",
                     "prediction_intervals.csv"):
            add(source / name, required=True)
        # The compact archive contains all actual 20-mode paths, not only representatives.
        archives = list(source.glob("*.npz"))
        if not archives:
            raise RuntimeError(f"Full stochastic path archive is missing: {source}")
        tree(source, RESULT_EXTENSIONS)
    for source in quality_outputs:
        for name in ("comparison_conditions.json", "paired_dynamic_raw.csv", "健康当前同工况指标.csv"):
            add(source / name, required=True)
        tree(source, RESULT_EXTENSIONS)

    import numpy as np
    rul_record_counts = []
    for source in rul_outputs:
        checkpoint_path = source / "monte_carlo_checkpoints.npz"
        add(checkpoint_path, required=True)
        with np.load(checkpoint_path, allow_pickle=False) as record:
            damage = record["damage"]
            if damage.ndim != 3 or damage.shape[2] != 20:
                raise RuntimeError("RUL archive does not contain the 20 independent mode states")
            count = damage.shape[1]
            if record["sample_ids"].tolist() != list(range(count)):
                raise RuntimeError("RUL archive sample IDs are incomplete")
        sample_path = source / "monte_carlo_rul_samples.csv"
        with sample_path.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        if len(rows) != count:
            raise RuntimeError("RUL checkpoint N and lifetime sample count disagree")
        rul_record_counts.append(count)
        tree(source, RESULT_EXTENSIONS)
    for launch in bat.get("launches", []):
        add(launch["log"], required=True)

    # No temp test trees, failed probes, old delivery ZIPs, Conda or Amesim files.
    entries = [{"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size,
                "sha256": sha(path)} for path in sorted(files)]
    manifest = {
        "delivery": "PHASE D4-R3", "incremental_package": True,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "python": sys.executable,
        "note": "用于当前本地D4-R2工程的源码与结果增量；不是独立EXE或跨平台二进制。",
        "test_results": {"full_repository": full_counts, "targeted": targeted_counts},
        "source_hashes_unchanged": True,
        "gui_acceptance": "outputs/desktop/r3/gui/acceptance.json",
        "rul_checkpoint_sample_counts": rul_record_counts,
        "excluded": ["pytest临时目录", "失败探测failure.txt", "中断的非完整全仓运行",
                     "重复历史结果及ZIP", "Conda环境", "Amesim文件"],
        "manifest_scope": "files列出全部载荷文件；manifest自身哈希另记在外置完整性记录，避免递归自哈希。",
        "files": entries,
    }
    manifest_path = OUT / "delivery_manifest.json"
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    manifest_path.write_bytes(manifest_bytes)
    add(manifest_path, required=True)
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    building = TARGET.with_suffix(".zip.building")
    if building.exists():
        raise RuntimeError(f"A prior incomplete build exists; inspect it before retrying: {building}")
    with zipfile.ZipFile(building, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(files):
            archive.write(path, path.relative_to(ROOT).as_posix())
    manifest_name = manifest_path.relative_to(ROOT).as_posix()
    with zipfile.ZipFile(building) as archive:
        bad = archive.testzip()
        if bad is not None:
            raise RuntimeError(f"ZIP CRC validation failed: {bad}")
        expected = {item["path"] for item in entries} | {manifest_name}
        if set(archive.namelist()) != expected or len(archive.namelist()) != len(expected):
            raise RuntimeError("ZIP member set differs from the manifest or has duplicate names")
        if archive.read(manifest_name) != manifest_bytes:
            raise RuntimeError("ZIP manifest does not match the written manifest")
        for item in entries:
            payload = archive.read(item["path"])
            if len(payload) != item["bytes"] or hashlib.sha256(payload).hexdigest() != item["sha256"]:
                raise RuntimeError(f"Archived payload does not match manifest: {item['path']}")
    if TARGET.exists():
        retained = TARGET.with_name(TARGET.stem + "_previous_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".zip")
        shutil.copy2(TARGET, retained)
        adjacent = TARGET.with_suffix(".zip.sha256")
        if adjacent.exists():
            shutil.copy2(adjacent, retained.with_suffix(".zip.sha256"))
    building.replace(TARGET)
    digest = sha(TARGET)
    TARGET.with_suffix(".zip.sha256").write_text(f"{digest}  {TARGET.name}\n", encoding="ascii")
    integrity = {
        "status": "PASS", "path": str(TARGET), "bytes": TARGET.stat().st_size,
        "file_count": len(files), "sha256": digest, "crc_testzip": "PASS",
        "archived_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "manifest_payload_sha256_check": "PASS", "payload_files_verified": len(entries),
        "full_repository_test_counts": full_counts, "targeted_test_counts": targeted_counts,
        "skips_preserved_as_skips": True,
    }
    (OUT / "delivery_integrity.json").write_text(json.dumps(integrity, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(integrity, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
