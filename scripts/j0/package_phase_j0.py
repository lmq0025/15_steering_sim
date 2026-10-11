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

README = """# PHASE J0 交付包

**结论：J0 联合仿真层已建成、可运行、有测试；四通道闭环被交付的 L1-Fast V1
液压模型缺陷阻断，与本层实现无关。**

先读：`handoff/05_J0_PLANT_DEFECT_AND_KNOWN_RISKS.md`
再读：`report/phase_J0_report.md`

## 阻断级缺陷

| ID | 缺陷 | 证据 |
|---|---|---|
| **F1** | 四个通道全部 `dF_hyd/dv > 0` 且 `dF_hyd/dx > 0`（液压负阻尼 + 负刚度） | `report/j0_diagnostics.json` 的 `plant_characterisation` 段、`report/plant_characterisation.png` |
| **F2** | `channel_front` 全命令范围静态作动力仅约 33 N，而前端组需要约 6.2 kN | 同上；另见 `data/J0-02_+2deg_5kmh_timeseries.csv`（前缸行程全程 0.0000 mm） |

两者都**无法用 PID 补偿**：见 `report/gain_study_J0-02.csv`
（20 组增益中 19 组在 0.03–0.18 s 内发散；唯一"跑满"的是 `kp=ki=kd=0`，
即完全不动作的平凡解）。

## 四工况实测结果

| 工况 | 目标 | 车速 | 结果 |
|---|---|---:|---|
| J0-01 | 0° | 0 km/h | **PASS**（严格不动点，残差 0） |
| J0-02 | +2° | 5 km/h | FAIL，0.080 s 停机 |
| J0-03 | −2° | 5 km/h | FAIL，0.082 s 停机 |
| J0-04 | +5° | 10 km/h | FAIL，0.075 s 停机 |

## 复现命令

```powershell
$py = 'E:\\ProgramData\\condaData\\envs_dirs\\steering_sim\\python.exe'
& $py scripts/j0/run_j0.py                 --output outputs/j0
& $py scripts/j0/run_j0_diagnostics.py     --output outputs/j0/diagnostics
& $py scripts/j0/run_j0_gain_study.py      --output outputs/j0/gain_study
& $py scripts/j0/run_j0.py --output outputs/j0_diag --diagnostic-damping 1.5e6 --duration 6.0
& $py -m pytest -q tests/j0_coupling -p no:cacheprovider
```

`--diagnostic-damping` 会在液压外载上叠加一个人为的机械阻尼，用于把 J0 流水线与
液压缺陷分开验证。该产物**不是**工况结果，也**从不**被记为 PASS。

## 目录结构

```
handoff/          缺陷正式登记
report/           J0 结论报告、摘要 JSON、被控对象诊断、增益研究、图
source/           J0 联调层源码、J0 配置、入口脚本、测试
data/             四工况逐步 CSV 与图（J0-01 … J0-04）
data/diagnostic/  人为阻尼诊断运行（仅用于结构验证）
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
