"""组装并校验 PHASE M2 交付包（任务书第十三节，精简）。

只包含六类内容：修订后的机械模型与接口、工况输入模板、十二轮数值表、
改进的机械转向图、物理正确性报告、必要测试与运行结果。
不生成大量审计文件，不打包历史 Amesim 文件。
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / "handoff_to_chatgpt" / "phase_M2"
ZIP = ROOT / "handoff_to_chatgpt" / "phase_M2.zip"

FIGURE_NAMES = ("fig1_plan_view.png", "fig2_wheel_angles.png", "fig7_wheel_table.png")

PACKAGE_FILES = [
    ("docs/mechanics/phase_M2_report.md", "phase_M2_report.md"),
    ("outputs/m2/ideal_ackermann_check.json", "results/ideal_ackermann_check.json"),
    ("outputs/m2/envelope_check.json", "results/envelope_check.json"),
    ("outputs/m2/linkage_audit.json", "results/linkage_audit.json"),
    ("outputs/m2/m2_summary.json", "results/m2_summary.json"),
    ("outputs/m2/full_cases.csv", "results/full_cases.csv"),
    ("outputs/m2/full_cases.xlsx", "results/full_cases.xlsx"),
    ("outputs/m2/case_template.csv", "templates/case_template.csv"),
    ("outputs/m2/case_template.xlsx", "templates/case_template.xlsx"),
]

MODEL = [
    "mechanics_ackermann_v2/model.py",
    "mechanics_ackermann_v2/config.json",
    "mechanics_ackermann_v2/batch.py",
]
MODULES = [
    "src/steering_sim/ackermann/__init__.py",
    "src/steering_sim/ackermann/ideal.py",
    "src/steering_sim/ackermann/linkage.py",
    "src/steering_sim/ackermann/equivalent.py",
    "src/steering_sim/ackermann/assessment.py",
    "src/steering_sim/ackermann/cases.py",
]
DEMO = [
    ("src/steering_sim/demo/plots.py", "demo/plots.py"),
    ("src/steering_sim/demo/ui.py", "demo/ui.py"),
    ("src/steering_sim/demo/assessment.py", "demo/assessment.py"),
    ("src/steering_sim/j0_coupling/runner.py", "j0_coupling/runner.py"),
]
SCRIPTS = [
    "scripts/m2/audit_axle_linkage.py",
    "scripts/m2/run_m2_batch.py",
    "scripts/m2/package_phase_m2.py",
]
TESTS = [
    "tests/ackermann/conftest.py",
    "tests/ackermann/test_m2_ackermann.py",
    "tests/demo/test_demo_service_and_ui.py",
]

README = """# PHASE M2 交付包 — 六桥阿克曼转向纠偏与全工况覆盖

## 先读

1. `phase_M2_report.md` —— 物理正确性报告（含五、六桥反号的完整归因）
2. `results/ideal_ackermann_check.json` —— ±30° 理想阿克曼角独立校核
3. `results/linkage_audit.json` —— 四杆装配分支与可解范围审计

## 三条必须记住的结论

1. **理想阿克曼角在 ±30° 内全部可算**，本包内独立实现与 M1 的最大差
   1.865e-14°；公式与推导见报告 §1。
2. **五、六桥同桥左右轮反号不是转录错误**：甲方 Word 表 7 个点逐点核对一致，
   拓扑与两张手绘结构图一致，几何左右严格镜像。真正原因是这两桥的
   "摆臂—边拉杆—车轮"四杆机构距死点只有 9.7°/6.6°（一、二、四桥为 76~85°），
   导致单侧车轮角**只能单向偏转**。详见报告 §3。
3. **工程等效模式只在真实机构确实做不到的地方启用**（五、六桥），
   四桥仍用真实闭链；等效角一律标记 `ENGINEERING_EQUIVALENT_ACKERMANN`，
   与 `CUSTOMER_LINKAGE_GEOMETRY` 分开保存。详见报告 §4。

## 目录

```
phase_M2_report.md                物理正确性报告
results/ideal_ackermann_check.json  ±30° 理想阿克曼角校核
results/envelope_check.json        机构坐标连续延拓包络与停止原因
results/linkage_audit.json         四杆装配分支、可达范围、距死点
results/m2_summary.json            全工况表汇总
results/full_cases.csv             3111 组全工况表（66 列）
results/full_cases.xlsx            同上（XLSX）
templates/case_template.csv/.xlsx  甲方工况输入模板
source/mechanics_ackermann_v2/     修订后的机械模型与配置
source/ackermann/                  PHASE M2 新增模块
source/demo/                       演示软件改动（数值表、旧结果标注）
source/scripts/                    审计、批算与打包脚本
source/baseline_pre_m2/            M2 修改前的快照与校验和
tests/                             新增与扩充的测试
figures/<工况>/                    改进后的机械转向图与十二轮数值表
```

## 复现

```powershell
$py = 'E:\\ProgramData\\condaData\\envs_dirs\\steering_sim\\python.exe'
& $py scripts/m2/audit_axle_linkage.py
& $py scripts/m2/run_m2_batch.py --xlsx-all
& $py -m pytest -q tests/ackermann tests/demo
```
"""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _copy(relative: str, target: Path, copied: list[Path]) -> None:
    source = ROOT / relative
    if not source.exists():
        raise SystemExit(f"缺少交付文件: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target)
        copied.extend(path for path in target.rglob("*") if path.is_file())
        return
    shutil.copy2(source, target)
    copied.append(target)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-zip", action="store_true")
    args = parser.parse_args()

    for required in ("outputs/m2/full_cases.csv", "outputs/m2/linkage_audit.json"):
        if not (ROOT / required).exists():
            raise SystemExit(f"请先运行 scripts/m2/run_m2_batch.py（缺少 {required}）")

    baseline = DEST / "source" / "baseline_pre_m2"
    stash = None
    if baseline.exists():
        stash = ROOT / "handoff_to_chatgpt" / "_m2_baseline_stash"
        if stash.exists():
            shutil.rmtree(stash)
        shutil.move(str(baseline), str(stash))
    if DEST.exists():
        shutil.rmtree(DEST)
    DEST.mkdir(parents=True)
    if stash is not None:
        stash.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(stash), str(baseline))

    copied: list[Path] = [path for path in baseline.rglob("*") if path.is_file()] \
        if baseline.exists() else []
    for relative, name in PACKAGE_FILES:
        _copy(relative, DEST / name, copied)
    for relative in MODEL:
        _copy(relative, DEST / "source" / "mechanics_ackermann_v2" / Path(relative).name,
              copied)
    for relative in MODULES:
        _copy(relative, DEST / "source" / "ackermann" / Path(relative).name, copied)
    for relative, name in DEMO:
        _copy(relative, DEST / "source" / name, copied)
    for relative in SCRIPTS:
        _copy(relative, DEST / "source" / "scripts" / Path(relative).name, copied)
    for relative in TESTS:
        _copy(relative, DEST / "tests" / Path(relative).name, copied)

    cache = ROOT / "outputs" / "j0_demo" / "preset_cache"
    for key in ("J0-01", "J0-02", "J0-03", "J0-04"):
        for name in FIGURE_NAMES:
            source = cache / name
            if source.exists():
                _copy(f"outputs/j0_demo/preset_cache/{name}",
                      DEST / "figures" / key / name, copied)

    (DEST / "README.md").write_text(README, encoding="utf-8")
    copied.append(DEST / "README.md")
    (DEST / "SHA256SUMS.txt").write_text(
        "\n".join(f"{_sha256(path)}  {path.relative_to(DEST).as_posix()}"
                  for path in sorted(copied) if path.is_file()) + "\n",
        encoding="utf-8")
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
            raise SystemExit(f"CRC 校验失败: {bad}")
        names = archive.namelist()
        total = sum(item.file_size for item in archive.infolist())
    print(f"zip: {ZIP}")
    print(f"members: {len(names)}  uncompressed: {total/1e6:.2f} MB  "
          f"zip size: {ZIP.stat().st_size/1e6:.2f} MB")
    print(f"sha256: {_sha256(ZIP)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
