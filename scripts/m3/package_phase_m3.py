"""PHASE M3 交付打包器。

**不会删除任何快照目录**（PHASE M2 曾因打包器的 rmtree 误删快照，本轮已修正）：
本脚本只删除并重建 ``handoff_to_chatgpt/phase_M3/`` 这一个目标目录，且该目录
完全由本脚本生成；任何 ``baseline_*`` / ``snapshot_*`` 子目录都会被保留。
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
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

DEST = ROOT / "handoff_to_chatgpt" / "phase_M3"
ZIP = ROOT / "handoff_to_chatgpt" / "phase_M3.zip"

FILES = (
    ("mechanics_ackermann_redesigned/model.py", "source/mechanics_ackermann_redesigned/model.py"),
    ("mechanics_ackermann_redesigned/config.json", "source/mechanics_ackermann_redesigned/config.json"),
    ("mechanics_ackermann_redesigned/design_parameters.json", "source/mechanics_ackermann_redesigned/design_parameters.json"),
    ("mechanics_ackermann_redesigned/README.md", "source/mechanics_ackermann_redesigned/README.md"),
    ("src/steering_sim/ackermann/planar.py", "source/steering_sim/ackermann/planar.py"),
    ("src/steering_sim/ackermann/redesign.py", "source/steering_sim/ackermann/redesign.py"),
    ("src/steering_sim/ackermann/state.py", "source/steering_sim/ackermann/state.py"),
    ("src/steering_sim/ackermann/transmission.py", "source/steering_sim/ackermann/transmission.py"),
    ("src/steering_sim/ackermann/cases_m3.py", "source/steering_sim/ackermann/cases_m3.py"),
    ("src/steering_sim/ackermann/ideal.py", "source/steering_sim/ackermann/ideal.py"),
    ("src/steering_sim/ackermann/assessment.py", "source/steering_sim/ackermann/assessment.py"),
    ("src/steering_sim/ackermann/cases.py", "source/steering_sim/ackermann/cases.py"),
    ("src/steering_sim/ackermann/linkage.py", "source/steering_sim/ackermann/linkage.py"),
    ("src/steering_sim/ackermann/equivalent.py", "source/steering_sim/ackermann/equivalent.py"),
    ("src/steering_sim/j0_coupling/mechanism.py", "source/steering_sim/j0_coupling/mechanism.py"),
    ("src/steering_sim/j0_coupling/geometry.py", "source/steering_sim/j0_coupling/geometry.py"),
    ("src/steering_sim/j0_coupling/runner.py", "source/steering_sim/j0_coupling/runner.py"),
    ("src/steering_sim/j0_coupling/road_load.py", "source/steering_sim/j0_coupling/road_load.py"),
    ("src/steering_sim/j0_coupling/config.py", "source/steering_sim/j0_coupling/config.py"),
    ("src/steering_sim/demo/service.py", "source/steering_sim/demo/service.py"),
    ("src/steering_sim/demo/ui.py", "source/steering_sim/demo/ui.py"),
    ("src/steering_sim/demo/plots.py", "source/steering_sim/demo/plots.py"),
    ("src/steering_sim/demo/assessment.py", "source/steering_sim/demo/assessment.py"),
    ("src/steering_sim/demo/scenario.py", "source/steering_sim/demo/scenario.py"),
    ("mechanics_ackermann_v2/model.py", "source/mechanics_ackermann_v2/model.py"),
    ("mechanics_ackermann_v2/config.json", "source/mechanics_ackermann_v2/config.json"),
    ("scripts/m3/design_synthesis.py", "source/scripts/m3/design_synthesis.py"),
    ("scripts/m3/finalize_redesign_config.py", "source/scripts/m3/finalize_redesign_config.py"),
    ("scripts/m3/build_m3_tables.py", "source/scripts/m3/build_m3_tables.py"),
    ("scripts/m3/run_m3_dynamic.py", "source/scripts/m3/run_m3_dynamic.py"),
    ("scripts/m3/package_phase_m3.py", "source/scripts/m3/package_phase_m3.py"),
    ("scripts/m3/plot_mechanism.py", "source/scripts/m3/plot_mechanism.py"),
    ("scripts/m3/write_m3_report.py", "source/scripts/m3/write_m3_report.py"),
    ("scripts/m3/finalize_status.py", "source/scripts/m3/finalize_status.py"),
    ("tests/demo/test_m3_mode_switch.py", "source/tests/demo/test_m3_mode_switch.py"),
    ("tests/ackermann/test_m3_redesign.py", "source/tests/ackermann/test_m3_redesign.py"),
    ("tests/ackermann/test_m2_ackermann.py", "source/tests/ackermann/test_m2_ackermann.py"),
    ("configs/j0/j0_config.json", "source/configs/j0/j0_config.json"),
    ("docs/mechanics/phase_M3_report.md", "docs/phase_M3_report.md"),
    ("docs/mechanics/phase_M2_report.md", "docs/phase_M2_report.md"),
    ("outputs/m3/m3_angle_coverage.csv", "data/m3_angle_coverage.csv"),
    ("outputs/m3/m3_angle_coverage.xlsx", "data/m3_angle_coverage.xlsx"),
    ("outputs/m3/m3_full_cases.xlsx", "data/m3_full_cases.xlsx"),
    ("outputs/m3/m3_case_template.csv", "data/m3_case_template.csv"),
    ("outputs/m3/m3_case_template.xlsx", "data/m3_case_template.xlsx"),
    ("outputs/m3/m3_as_built_vs_redesigned.csv", "data/m3_as_built_vs_redesigned.csv"),
    ("outputs/m3/m3_full_cases.csv", "data/m3_full_cases.csv"),
    ("outputs/m3/m3_batch_summary.json", "data/m3_batch_summary.json"),
    ("outputs/m3/dynamic/m3_dynamic_representative.json", "data/m3_dynamic_representative.json"),
    ("outputs/m3/dynamic/m3_dynamic_as_built.json", "data/m3_dynamic_as_built.json"),
)

DYNAMIC_FIGURES = ("outputs/m3/dynamic", "data/dynamic")
EXTRA_GLOBS = (
    ("outputs/m3/figures", "figures"),
)


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

    # 只清理本脚本自己的目标目录；绝不动任何快照 / baseline 目录。
    if dest.exists():
        for child in dest.iterdir():
            if child.name.startswith(("baseline", "snapshot")):
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    dest.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []
    missing: list[str] = []
    for source_name, target_name in FILES:
        source = ROOT / source_name
        if not source.exists():
            missing.append(source_name)
            continue
        target = dest / target_name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.append(target_name)

    for source_dir, target_dir in EXTRA_GLOBS:
        source = ROOT / source_dir
        if not source.exists():
            continue
        for item in sorted(source.rglob("*")):
            if item.is_file():
                target = dest / target_dir / item.relative_to(source)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
                copied.append(str(target.relative_to(dest)))

    dynamic_dir = ROOT / "outputs" / "m3" / "dynamic"
    if dynamic_dir.exists():
        for item in sorted(dynamic_dir.glob("*_timeseries.csv")):
            target = dest / "data" / "dynamic" / item.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
            copied.append(str(target.relative_to(dest)))

    # 校验和清单
    lines = []
    for path in sorted(dest.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS.txt":
            lines.append(f"{_sha256(path)}  {path.relative_to(dest).as_posix()}")
    (dest / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    readme = dest / "交付说明.md"
    readme.write_text(
        "# PHASE M3 交付包\n\n"
        "**模型来源标记：`ENGINEERING_REDESIGN_PROPOSAL`**\n\n"
        "该机构为基于甲方硬点与工程假设提出的优化设计方案，尚未通过实车验证。\n"
        "甲方原始铰点坐标、杆长与液压缸安装点**未被修改**。\n\n"
        "## 目录\n\n"
        "* `source/` —— 修改后的**实际源代码**（不是只放报告和数据）\n"
        "* `docs/` —— PHASE M3 设计报告与 PHASE M2 对照报告\n"
        "* `data/` —— 61 转角覆盖表、原始/优化机构对照表、3111 工况表、"
        "代表性动态工况结果与时间序列\n\n"
        "## 复现\n\n"
        "```\n"
        "E:\\ProgramData\\condaData\\envs_dirs\\steering_sim\\python.exe scripts/m3/design_synthesis.py --axles front,4,5,6\n"
        "E:\\ProgramData\\condaData\\envs_dirs\\steering_sim\\python.exe scripts/m3/finalize_redesign_config.py\n"
        "E:\\ProgramData\\condaData\\envs_dirs\\steering_sim\\python.exe scripts/m3/build_m3_tables.py\n"
        "E:\\ProgramData\\condaData\\envs_dirs\\steering_sim\\python.exe scripts/m3/run_m3_dynamic.py\n"
        "```\n\n"
        "## 完整性\n\n"
        "`SHA256SUMS.txt` 列出包内每个文件的 sha256。**zip 自身的 sha256 无法写进包内**，"
        "由外部交付说明给出。\n",
        encoding="utf-8")
    copied.append("交付说明.md")

    # 打包
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(dest.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(dest.parent).as_posix())
    with zipfile.ZipFile(archive) as zf:
        bad = zf.testzip()
        members = zf.namelist()
    report = {
        "dest": str(dest), "zip": str(archive),
        "members": len(members), "missing_sources": missing,
        "zip_size_bytes": archive.stat().st_size,
        "zip_sha256": _sha256(archive),
        "crc_ok": bad is None,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if bad is not None:
        print("CRC 校验失败：", bad)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
