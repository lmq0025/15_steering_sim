"""组装并校验 PHASE J0-R1 交付包（精简版，按任务书第 11 节）。

只包含七类内容：报告、结果 JSON、四工况图、四通道行程图、压力/力/负载图、
修改过的源码与测试、工程假设与剩余问题说明。不再生成大量审计 CSV。
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / "handoff_to_chatgpt" / "phase_J0_R1"
ZIP = ROOT / "handoff_to_chatgpt" / "phase_J0_R1.zip"

FILES = [
    ("outputs/j0_r1/phase_J0_R1_results.json", "phase_J0_R1_results.json"),
    ("docs/integration/phase_J0_R1_report.md", "phase_J0_R1_report.md"),
    ("docs/integration/phase_J0_R1_assumptions.md", "phase_J0_R1_assumptions.md"),
    ("docs/handoff/J0_claude/05_J0_PLANT_DEFECT_AND_KNOWN_RISKS.md",
     "05_J0_PLANT_DEFECT_AND_KNOWN_RISKS.md"),
    ("configs/j0/j0_config.json", "configs/j0_config.json"),
]

# 修改过的液压源码与对应的修改前备份
SOURCE = [
    "src/steering_sim/hydraulics_lumped/actuator.py",
    "src/steering_sim/hydraulics_lumped/model.py",
    "src/steering_sim/hydraulics_lumped/parameters.py",
    "src/steering_sim/hydraulics_lumped/supply.py",
    "src/steering_sim/hydraulics_lumped/working_point.py",
    "src/steering_sim/hydraulics_lumped/__init__.py",
]
J0_SOURCE = [
    "src/steering_sim/j0_coupling/authority.py",
    "src/steering_sim/j0_coupling/runner.py",
    "src/steering_sim/j0_coupling/diagnostics.py",
    "src/steering_sim/j0_coupling/reporting.py",
]
TESTS = [
    "tests/hydraulics_lumped/test_j0r1_actuator_signs.py",
    "tests/hydraulics_lumped/test_j0r1_front_actuation.py",
    "tests/hydraulics_lumped/test_actuator_force.py",
    "tests/hydraulics_lumped/test_l1_fast_regulated_supply.py",
    "tests/hydraulics_lumped/test_r1_validation.py",
    "tests/j0_coupling/test_j0_load_and_authority.py",
    "tests/j0_coupling/test_j0_loop.py",
    "tests/j0_coupling/test_j0_report_and_outputs.py",
]
SCRIPTS = [
    "scripts/j0/run_j0.py",
    "scripts/j0/run_j0_diagnostics.py",
    "scripts/j0/build_j0r1_results.py",
]

README = """# PHASE J0-R1 交付包

**任务：修复液压模型缺陷 F1（力/容积符号不一致）与 F2（前桥无有效静态驱动力），
恢复控制—液压—机械联合仿真。**

先读：`phase_J0_R1_report.md`
再读：`phase_J0_R1_assumptions.md`（工程假设与剩余问题）

## 修复摘要

| 缺陷 | 根因 | 改动 | 结果 |
|---|---|---|---|
| **F1** | `actuator.py` 的力方向与 `chamber_volumes` 的容积约定相反，液压刚度和阻尼同时取发散符号 | `F_hyd = A_b*p_b - A_a*p_a` | 四通道 `dF/dv < 0`、`dF/dx < 0` |
| **F2** | `model.py` 对 `dirvalve_6` 硬置零 A 腔流量；`parameters.py` 前阀工作口未按 IR V3 换位；`actuator002` 被写入人工内泄漏 | 三处一并修正 | 前桥静态力窗口 ±33 N → **±6.2 kN**，双向 |
| **F3** | 冗余阀在恒压边界下零流量 | 未处理 | **DEFERRED** |

修复前源码完整备份在 `baseline_pre_fix/`（含 `SHA256SUMS.txt`），可逐字节还原。

## 复现

```powershell
$py = 'E:\\ProgramData\\condaData\\envs_dirs\\steering_sim\\python.exe'
& $py scripts/j0/run_j0.py --output outputs/j0_r1                      # 四工况，含 M1 地面负载
& $py scripts/j0/run_j0.py --output outputs/j0_r1_noload --no-road-load --duration 3.0
& $py scripts/j0/run_j0_diagnostics.py --output outputs/j0/diagnostics
& $py -m pytest -q tests/hydraulics_lumped tests/j0_coupling -p no:cacheprovider
& $py scripts/j0/build_j0r1_results.py
```

**正式工况一律不使用任何人造阻尼**（`--diagnostic-damping` 默认 0，本轮未使用）。

## 目录结构

```
phase_J0_R1_report.md          结论报告
phase_J0_R1_results.json       结构化结果
phase_J0_R1_assumptions.md     工程假设与剩余问题
05_J0_PLANT_DEFECT_AND_KNOWN_RISKS.md   缺陷登记（含 J0-R1 修复状态）
figures/                       四工况图（含 M1 地面负载，5 s 横轴）
figures_no_road_load/          第 7 节测试 3 的对照图（关闭地面负载，3 s），
                               文件名带 NOLOAD_ 前缀，杜绝与正式工况图混淆
source/                        修改过的液压源码、J0 层源码、入口脚本
tests/                         修改过与新增的测试
baseline_pre_fix/              F1/F2 修复前的原始文件与校验和
configs/                       J0 配置
```

`phase_J0_R1_results.json` 的单位约定：字段名以 `_mm` 结尾的一律为毫米，
以 `_m` 结尾的一律为米。`final_stroke_mm` 是**末值**行程，
`stroke_range_mm` 是**行程区间** `[min, max]`。
"""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _copy(relative: str, target_dir: Path, copied: list[Path],
          strip: str | None = None) -> None:
    """复制文件并保留其模块归属（例如 ``hydraulics_lumped/actuator.py``）。"""
    source = ROOT / relative
    if not source.exists():
        raise SystemExit(f"缺少交付文件: {source}")
    name = Path(relative[len(strip):]) if strip and relative.startswith(strip) \
        else Path(source.name)
    target = target_dir / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    copied.append(target)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-zip", action="store_true")
    args = parser.parse_args()

    # 保留 baseline_pre_fix/，只清掉上一次生成的其余内容
    baseline = DEST / "baseline_pre_fix"
    stash = None
    if baseline.exists():
        stash = DEST.parent / "_j0r1_baseline_stash"
        if stash.exists():
            shutil.rmtree(stash)
        shutil.move(str(baseline), str(stash))
    if DEST.exists():
        shutil.rmtree(DEST)
    DEST.mkdir(parents=True)
    if stash is not None:
        shutil.move(str(stash), str(baseline))

    copied: list[Path] = list(baseline.glob("*")) if baseline.exists() else []
    for relative, name in FILES:
        source = ROOT / relative
        if not source.exists():
            raise SystemExit(f"缺少交付文件: {source}")
        target = DEST / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.append(target)
    for relative in SOURCE:
        _copy(relative, DEST / "source", copied, strip="src/steering_sim/")
    for relative in J0_SOURCE:
        _copy(relative, DEST / "source", copied, strip="src/steering_sim/")
    for relative in SCRIPTS:
        _copy(relative, DEST / "source", copied, strip="scripts/")
    for relative in TESTS:
        _copy(relative, DEST / "tests", copied, strip="tests/")
    # J0-DEMO 修正：两组图必须**分目录**存放。旧版本把无地面负载（3 s）与
    # 含地面负载（5 s）的图放进同一个 figures/，同名文件互相覆盖，导致交付的
    # 图只有 3 s 横轴，而报告引用的是 5 s 结果。现在按来源分开，并显式标注。
    figure_sets = (("outputs/j0_r1/J0-0*_fig*.png", "figures", ""),
                   ("outputs/j0_r1_noload/J0-0*_fig*.png",
                    "figures_no_road_load", "NOLOAD_"))
    for pattern, folder, prefix in figure_sets:
        for source in sorted(ROOT.glob(pattern)):
            target = DEST / folder / f"{prefix}{source.name}"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
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
