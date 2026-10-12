"""PHASE J1-R2 交付打包器 → ``handoff_to_chatgpt/phase_J1_R2.zip``。

**不会删除任何快照目录，也不会删除整个交付目录**：只重建
``handoff_to_chatgpt/phase_J1_R2/`` 这一个由本脚本生成的目标目录，
任何 ``baseline_*`` / ``snapshot_*`` 子目录一律保留。
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / "handoff_to_chatgpt" / "phase_J1_R2"
ZIP = ROOT / "handoff_to_chatgpt" / "phase_J1_R2.zip"

SOURCES = (
    "src/steering_sim/hydraulics_engineering/__init__.py",
    "src/steering_sim/hydraulics_engineering/parameters.py",
    "src/steering_sim/hydraulics_engineering/model.py",
    "src/steering_sim/hydraulics_engineering/authority.py",
    "src/steering_sim/engineering/mechanism.py",
    "src/steering_sim/engineering/model.py",
    "src/steering_sim/j0_coupling/runner.py",
    "src/steering_sim/j0_coupling/geometry.py",
    "src/steering_sim/j0_coupling/road_load.py",
    "src/steering_sim/j0_coupling/config.py",
    "src/steering_sim/j0_coupling/mechanism.py",
    "src/steering_sim/j0_coupling/authority.py",
    "src/steering_sim/control/pid.py",
    "src/steering_sim/control/base.py",
    "src/steering_sim/demo/service.py",
    "src/steering_sim/demo/ui.py",
    "src/steering_sim/demo/plots.py",
    "src/steering_sim/demo/assessment.py",
    "src/steering_sim/demo/scenario.py",
    "src/steering_sim/demo/batch.py",
)

CONFIGS = (
    "configs/j1r2/engineering_hydraulics.json",
    "configs/j1/engineering_config.json",
    "configs/j1/engineering_mechanism.json",
    "configs/j0/j0_config.json",
)

SCRIPTS = (
    "scripts/j1r2/retune_front_follower.py",
    "scripts/j1r2/design_engineering_hydraulics.py",
    "scripts/j1r2/run_j1r2_dynamic.py",
    "scripts/j1r2/run_j1r2_batch.py",
    "scripts/j1r2/check_step_convergence.py",
    "scripts/j1r2/make_j1r2_figures.py",
    "scripts/j1r2/capture_ui_screenshot.py",
    "scripts/j1r2/write_j1r2_report.py",
    "scripts/j1r2/finalize_status.py",
    "scripts/j1r2/package_phase_j1r2.py",
    "scripts/j1/build_engineering_config.py",
    "scripts/j1/check_gate1_geometry.py",
    "start_steering_demo.bat",
)

TESTS = (
    "tests/hydraulics_engineering/test_engineering_hydraulics.py",
    "tests/hydraulics_engineering/conftest.py",
    "tests/demo/test_j1r2_ui_and_batch.py",
    "tests/demo/test_m3_mode_switch.py",
    "tests/j0_coupling/test_j0_load_and_authority.py",
    "tests/engineering/test_j1_model.py",
)

DATA = (
    ("outputs/j1r2/hydraulic_sizing.json", "data/hydraulic_sizing.json"),
    ("outputs/j1/gate1_angle_table.csv", "data/gate1_angle_table.csv"),
    ("outputs/j1/gate1_summary.json", "data/gate1_summary.json"),
    ("outputs/j1r2/j1r2_full_cases.csv", "data/j1r2_full_cases.csv"),
    ("outputs/j1r2/j1r2_full_cases.xlsx", "data/j1r2_full_cases.xlsx"),
    ("outputs/j1r2/j1r2_full_cases_summary.json", "data/j1r2_full_cases_summary.json"),
    ("outputs/j1r2/step_convergence.json", "data/step_convergence.json"),
    ("outputs/j1r2/dynamic/j1r2_dynamic.json", "data/j1r2_dynamic.json"),
)

FIGURES = (
    "fig_r2_1_strokes_command_pressure.png",
    "fig_r2_2_forces_velocity.png",
    "fig_r2_3_wheel_tracking.png",
    "fig_r2_4_dynamic_summary.png",
    "fig_r2_5_gate1_full_range.png",
    "fig_r2_6_batch_status_map.png",
    "fig_r2_7_ui_overall.png",
    "fig_r2_8_ui_wheel_table.png",
)

DISCLAIMER = """# PHASE J1-R2 交付包

**唯一正式机械模型：`ENGINEERING_STEERING_MODEL`**
**唯一正式液压模型：`ENGINEERING_HYDRAULIC_V1`**（`src/steering_sim/hydraulics_engineering/`）

* 甲方已确认的原始铰点坐标、车轮中心、轴距与轮距**全部保留未改**。
* 中间传动机构沿用 J1 的齿条—转向梯形方案；液压部分（缸径、面积、行程、
  容积、阻尼、摩擦、阀口面积、泵排量、溢流压力、控制器增益）按工程物理原则
  **重新设计**，逐条标记 `ENGINEERING_DESIGN_ASSUMPTION`。
* 旧 Amesim / L1-Fast 参数原样存档在 `configs/j1/hydraulic_design.json`，
  不再作为正式运行模型。

## 目录

* `source/` —— 修改后的**实际源代码**（工程液压模型、机械模型、J0 集成层、
  PID、演示服务层、中文界面、批量模块）
* `configs/` —— 工程液压参数、机械设计参数、J0 配置
* `docs/` —— PHASE J1-R2 报告
* `data/` —— 液压选型核算、61 角全范围表、3111 工况结果、动态工况结果与
  每条代表工况的完整时间序列
* `figures/` —— 代表性曲线与中文界面验收截图
* `tests/` —— 本阶段新增/更新的测试
* `scripts/` —— 复现用脚本与一键启动 BAT

## 复现

```
python scripts/j1r2/retune_front_follower.py --scale 1.39
python scripts/j1/build_engineering_config.py
python scripts/j1/check_gate1_geometry.py
python scripts/j1r2/design_engineering_hydraulics.py
python scripts/j1r2/check_step_convergence.py
python scripts/j1r2/run_j1r2_dynamic.py
python scripts/j1r2/run_j1r2_batch.py
python scripts/j1r2/make_j1r2_figures.py
python scripts/j1r2/make_j1r2_figures.py
python scripts/j1r2/capture_ui_screenshot.py
python scripts/j1r2/write_j1r2_report.py
python scripts/j1r2/finalize_status.py
python scripts/j1r2/package_phase_j1r2.py
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


def _copy(source: Path, target: Path, missing: list[str]) -> None:
    if not source.exists():
        missing.append(str(source.relative_to(ROOT)))
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


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
    for name in SOURCES:
        _copy(ROOT / name, dest / "source" / Path(name).relative_to("src/steering_sim"),
              missing)
    for name in CONFIGS:
        _copy(ROOT / name, dest / "configs" / Path(name).relative_to("configs"), missing)
    for name in SCRIPTS:
        # 保留仓库内的相对路径（scripts/j1/…、scripts/j1r2/…），根目录的 .bat 平铺。
        relative = Path(name).name if name.endswith(".bat") else name
        _copy(ROOT / name, dest / relative, missing)
    for name in TESTS:
        _copy(ROOT / name, dest / "tests" / Path(name).relative_to("tests"), missing)
    for name, target_name in DATA:
        _copy(ROOT / name, dest / target_name, missing)
    for name in FIGURES:
        _copy(ROOT / "outputs" / "j1r2" / name, dest / "figures" / name, missing)

    dynamic = ROOT / "outputs" / "j1r2" / "dynamic"
    if dynamic.exists():
        (dest / "data" / "dynamic").mkdir(parents=True, exist_ok=True)
        for item in sorted(dynamic.glob("*_timeseries.csv")):
            shutil.copy2(item, dest / "data" / "dynamic" / item.name)

    _copy(ROOT / "docs" / "integration" / "phase_J1_R2_report.md",
          dest / "docs" / "phase_J1_R2_report.md", missing)
    _copy(ROOT / "docs" / "integration" / "phase_J1_unified_model_report.md",
          dest / "docs" / "phase_J1_unified_model_report.md", missing)

    (dest / "交付说明.md").write_text(DISCLAIMER, encoding="utf-8")

    lines = []
    for path in sorted(dest.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS.txt":
            lines.append(f"{_sha256(path)}  {path.relative_to(dest).as_posix()}")
    (dest / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as handle:
        for path in sorted(dest.rglob("*")):
            if path.is_file():
                handle.write(path, path.relative_to(dest.parent).as_posix())
    with zipfile.ZipFile(archive) as handle:
        bad = handle.testzip()
        members = handle.namelist()
    report = {"dest": str(dest), "zip": str(archive), "members": len(members),
              "missing_sources": missing, "zip_size_bytes": archive.stat().st_size,
              "zip_sha256": _sha256(archive), "crc_ok": bad is None}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if bad is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
