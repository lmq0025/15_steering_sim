"""PHASE J1 交付打包器。

**不会删除任何快照目录，也不会删除整个交付目录**：只重建
``handoff_to_chatgpt/phase_J1/`` 这一个由本脚本生成的目标目录，
任何 ``baseline_*`` / ``snapshot_*`` 子目录一律保留。
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / "handoff_to_chatgpt" / "phase_J1"
ZIP = ROOT / "handoff_to_chatgpt" / "phase_J1.zip"

FILES = (
    ("src/steering_sim/engineering/__init__.py", "source/steering_sim/engineering/__init__.py"),
    ("src/steering_sim/engineering/mechanism.py", "source/steering_sim/engineering/mechanism.py"),
    ("src/steering_sim/engineering/model.py", "source/steering_sim/engineering/model.py"),
    ("configs/j1/engineering_mechanism.json", "configs/j1/engineering_mechanism.json"),
    ("configs/j1/engineering_config.json", "configs/j1/engineering_config.json"),
    ("configs/j1/hydraulic_design.json", "configs/j1/hydraulic_design.json"),
    ("configs/j0/j0_config.json", "configs/j0/j0_config.json"),
    ("src/steering_sim/j0_coupling/mechanism.py", "source/steering_sim/j0_coupling/mechanism.py"),
    ("src/steering_sim/j0_coupling/geometry.py", "source/steering_sim/j0_coupling/geometry.py"),
    ("src/steering_sim/j0_coupling/runner.py", "source/steering_sim/j0_coupling/runner.py"),
    ("src/steering_sim/j0_coupling/road_load.py", "source/steering_sim/j0_coupling/road_load.py"),
    ("src/steering_sim/j0_coupling/config.py", "source/steering_sim/j0_coupling/config.py"),
    ("src/steering_sim/j0_coupling/authority.py", "source/steering_sim/j0_coupling/authority.py"),
    ("src/steering_sim/control/pid.py", "source/steering_sim/control/pid.py"),
    ("src/steering_sim/control/base.py", "source/steering_sim/control/base.py"),
    ("src/steering_sim/demo/service.py", "source/steering_sim/demo/service.py"),
    ("src/steering_sim/demo/ui.py", "source/steering_sim/demo/ui.py"),
    ("src/steering_sim/demo/plots.py", "source/steering_sim/demo/plots.py"),
    ("src/steering_sim/demo/assessment.py", "source/steering_sim/demo/assessment.py"),
    ("src/steering_sim/demo/scenario.py", "source/steering_sim/demo/scenario.py"),
    ("scripts/j1/design_engineering_mechanism.py", "source/scripts/j1/design_engineering_mechanism.py"),
    ("scripts/j1/build_engineering_config.py", "source/scripts/j1/build_engineering_config.py"),
    ("scripts/j1/check_gate1_geometry.py", "source/scripts/j1/check_gate1_geometry.py"),
    ("scripts/j1/hydraulic_sizing.py", "source/scripts/j1/hydraulic_sizing.py"),
    ("scripts/j1/run_j1_batch.py", "source/scripts/j1/run_j1_batch.py"),
    ("scripts/j1/run_j1_dynamic.py", "source/scripts/j1/run_j1_dynamic.py"),
    ("scripts/j1/write_j1_report.py", "source/scripts/j1/write_j1_report.py"),
    ("scripts/j1/package_phase_j1.py", "source/scripts/j1/package_phase_j1.py"),
    ("tests/engineering/test_j1_model.py", "source/tests/engineering/test_j1_model.py"),
    ("tests/demo/test_m3_mode_switch.py", "source/tests/demo/test_m3_mode_switch.py"),
    ("tests/j0_coupling/test_j0_load_and_authority.py", "source/tests/j0_coupling/test_j0_load_and_authority.py"),
    ("outputs/j1/j1_status_block.txt", "status_block.txt"),
    ("docs/integration/phase_J1_unified_model_report.md", "docs/phase_J1_unified_model_report.md"),
    ("docs/mechanics/phase_M2_report.md", "docs/phase_M2_report.md"),
    ("docs/mechanics/phase_M3_report.md", "docs/phase_M3_report.md"),
    ("outputs/j1/gate1_angle_table.csv", "data/gate1_angle_table.csv"),
    ("outputs/j1/gate1_summary.json", "data/gate1_summary.json"),
    ("outputs/j1/hydraulic_sizing.csv", "data/hydraulic_sizing.csv"),
    ("outputs/j1/j1_full_cases.csv", "data/j1_full_cases.csv"),
    ("outputs/j1/j1_full_cases.xlsx", "data/j1_full_cases.xlsx"),
    ("outputs/j1/j1_batch_summary.json", "data/j1_batch_summary.json"),
    ("outputs/j1/dynamic/j1_dynamic.json", "data/j1_dynamic.json"),
)

DISCLAIMER = """# PHASE J1 交付包

**唯一正式机械模型：`ENGINEERING_STEERING_MODEL`**

* 甲方已确认的原始铰点坐标、车轮中心、轴距与轮距**全部保留未改**。
* 中间传动机构（齿条 + 转向梯形）与甲方未提供的尺寸按工程物理原则重新设计，
  逐条标记为 `ENGINEERING_DESIGN_ASSUMPTION`。
* 历史机构源码保留在仓库里，但不再是正式计算分支，界面也没有模式切换。

## 目录

* `source/` —— 修改后的**实际源代码**（含机械模型、J0 集成层、PID、界面）
* `configs/` —— 机械设计参数、模型配置、液压选型建议
* `docs/` —— PHASE J1 报告与 M2/M3 对照报告
* `data/` —— 61 转角全范围校核表、液压选型表、3111 工况结果、动态工况结果与时间序列

## 复现

```
python scripts/j1/design_engineering_mechanism.py --scan
python scripts/j1/build_engineering_config.py
python scripts/j1/check_gate1_geometry.py
python scripts/j1/hydraulic_sizing.py
python scripts/j1/run_j1_batch.py
python scripts/j1/run_j1_dynamic.py
python scripts/j1/write_j1_report.py
python scripts/j1/package_phase_j1.py
```

`SHA256SUMS.txt` 列出包内每个文件的 sha256；**zip 自身的 sha256 无法写进包内**，
由外部交付说明给出。
"""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dest", default=str(DEST))
    parser.add_argument("--zip", default=str(ZIP))
    args = parser.parse_args()
    dest = Path(args.dest)
    archive = Path(args.zip)

    if dest.exists():
        for child in dest.iterdir():
            if child.name.startswith(("baseline", "snapshot")):
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    dest.mkdir(parents=True, exist_ok=True)

    missing: list[str] = []
    for source_name, target_name in FILES:
        source = ROOT / source_name
        if not source.exists():
            missing.append(source_name)
            continue
        target = dest / target_name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    dynamic = ROOT / "outputs" / "j1" / "dynamic"
    if dynamic.exists():
        for item in sorted(dynamic.glob("*_timeseries.csv")):
            target = dest / "data" / "dynamic" / item.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)

    (dest / "交付说明.md").write_text(DISCLAIMER, encoding="utf-8")

    lines = []
    for path in sorted(dest.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS.txt":
            lines.append(f"{_sha256(path)}  {path.relative_to(dest).as_posix()}")
    (dest / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(dest.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(dest.parent).as_posix())
    with zipfile.ZipFile(archive) as zf:
        bad = zf.testzip()
        members = zf.namelist()
    report = {"dest": str(dest), "zip": str(archive), "members": len(members),
              "missing_sources": missing, "zip_size_bytes": archive.stat().st_size,
              "zip_sha256": _sha256(archive), "crc_ok": bad is None}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if bad is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
