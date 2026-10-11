"""Assemble and verify the PHASE J0 handoff package.

Copies the report, the defect register, the J0 source/configuration/tests, and
the recorded evidence into ``handoff_to_chatgpt/phase_J0/`` and then produces
``handoff_to_chatgpt/phase_J0.zip`` with a CRC check on every member.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / "handoff_to_chatgpt" / "phase_J0"
ZIP = ROOT / "handoff_to_chatgpt" / "phase_J0.zip"

TREE = [
    ("docs/integration/phase_J0_report.md", "report/phase_J0_report.md"),
    ("docs/handoff/J0_claude/05_J0_PLANT_DEFECT_AND_KNOWN_RISKS.md",
     "handoff/05_J0_PLANT_DEFECT_AND_KNOWN_RISKS.md"),
    ("configs/j0/j0_config.json", "source/configs/j0/j0_config.json"),
    ("outputs/j0/j0_summary.json", "report/j0_summary.json"),
    ("outputs/j0/diagnostics/j0_diagnostics.json", "report/j0_diagnostics.json"),
    ("outputs/j0/diagnostics/plant_characterisation.png",
     "report/plant_characterisation.png"),
    ("outputs/j0/gain_study/gain_study_J0-02.json", "report/gain_study_J0-02.json"),
    ("outputs/j0/gain_study/gain_study_J0-02.csv", "report/gain_study_J0-02.csv"),
]

GLOBS = [
    ("src/steering_sim/j0_coupling/*.py", "source/src/steering_sim/j0_coupling"),
    ("scripts/j0/*.py", "source/scripts/j0"),
    ("tests/j0_coupling/*.py", "source/tests/j0_coupling"),
    ("outputs/j0/J0-0*_timeseries.csv", "data"),
    ("outputs/j0/J0-0*_fig*.png", "data"),
    ("outputs/j0_diag/J0-0*-DIAG_timeseries.csv", "data/diagnostic"),
    ("outputs/j0_diag/J0-0*_fig*.png", "data/diagnostic"),
]

README = """# PHASE J0 handoff package

**Verdict: the J0 joint-commissioning layer is built, runs, and is tested; the
four-channel closed loop is blocked by a defect in the delivered L1-Fast V1
hydraulic plant, not by anything in this layer.**

Read first: `handoff/05_J0_PLANT_DEFECT_AND_KNOWN_RISKS.md`
Then: `report/phase_J0_report.md`

## Blocking defects

| ID | Defect | Evidence |
|---|---|---|
| F1 | All four channels have `dF_hyd/dv > 0` and `dF_hyd/dx > 0` (negative hydraulic damping and stiffness) | `report/j0_diagnostics.json` -> `plant_characterisation`, `report/plant_characterisation.png` |
| F2 | `channel_front` static force authority is ~33 N over the whole command range; the front group needs ~6.2 kN | same, plus `data/J0-02_+2deg_5kmh_timeseries.csv` |

Neither can be compensated by PID: see `report/gain_study_J0-02.csv`
(19 of 20 tested gain sets diverge within 0.03-0.18 s; the only set that runs is
`kp=ki=kd=0`, which does nothing).

## Recorded case outcomes

| Case | Target | Speed | Status |
|---|---|---:|---|
| J0-01 | 0 deg | 0 km/h | **PASS** (exact fixed point, zero residuals) |
| J0-02 | +2 deg | 5 km/h | FAIL, stopped at 0.080 s |
| J0-03 | -2 deg | 5 km/h | FAIL, stopped at 0.082 s |
| J0-04 | +5 deg | 10 km/h | FAIL, stopped at 0.075 s |

## Reproduce

```powershell
$py = 'E:\\ProgramData\\condaData\\envs_dirs\\steering_sim\\python.exe'
& $py scripts/j0/run_j0.py                 --output outputs/j0
& $py scripts/j0/run_j0_diagnostics.py     --output outputs/j0/diagnostics
& $py scripts/j0/run_j0_gain_study.py      --output outputs/j0/gain_study
& $py scripts/j0/run_j0.py --output outputs/j0_diag --diagnostic-damping 1.5e6 --duration 6.0
& $py -m pytest -q tests/j0_coupling -p no:cacheprovider
```

`--diagnostic-damping` adds a fictitious mechanical damper so that the J0
pipeline can be exercised independently of the plant defect.  Those results are
**not** operating-case results and are never reported as a PASS.

## Layout

```
handoff/      defect register
report/       J0 conclusion report, summaries, diagnostics, gain study, figures
source/       J0 coupling source, J0 configuration, entry scripts, tests
data/         per-case time series CSV and figures (J0-01..J0-04)
data/diagnostic/  diagnostic-damped runs (structure verification only)
```
"""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-zip", action="store_true")
    args = parser.parse_args()

    if DEST.exists():
        shutil.rmtree(DEST)
    DEST.mkdir(parents=True)

    copied: list[Path] = []
    for source, relative in TREE:
        src = ROOT / source
        if not src.exists():
            raise SystemExit(f"missing required artefact: {src}")
        target = DEST / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
        copied.append(target)
    for pattern, relative in GLOBS:
        for src in sorted(ROOT.glob(pattern)):
            if src.is_dir() or "__pycache__" in src.parts:
                continue
            target = DEST / relative / src.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
            copied.append(target)
    (DEST / "README.md").write_text(README, encoding="utf-8")
    copied.append(DEST / "README.md")

    print(f"assembled {len(copied)} files into {DEST}")

    if args.skip_zip:
        return 0

    if ZIP.exists():
        ZIP.unlink()
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(DEST.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(DEST.parent))

    with zipfile.ZipFile(ZIP) as archive:
        bad = archive.testzip()
        if bad is not None:
            raise SystemExit(f"CRC check failed on {bad}")
        names = archive.namelist()
        total = sum(item.file_size for item in archive.infolist())
    print(f"zip: {ZIP}")
    print(f"members: {len(names)}  uncompressed: {total/1e6:.2f} MB  "
          f"zip size: {ZIP.stat().st_size/1e6:.2f} MB")
    print(f"sha256: {_sha256(ZIP)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
