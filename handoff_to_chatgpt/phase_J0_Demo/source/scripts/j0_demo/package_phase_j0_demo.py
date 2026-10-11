"""组装并校验 PHASE J0-DEMO 交付包。

内容按任务书第十一节：中文演示界面、一键启动 BAT、四工况结果与图、
工程假设说明、用户使用说明、退化参数接口说明、修改代码与必要测试。

不打包任何历史 Amesim 文件、不打包 source_materials。
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / "handoff_to_chatgpt" / "phase_J0_Demo"
ZIP = ROOT / "handoff_to_chatgpt" / "phase_J0_Demo.zip"

DOCS = [
    ("docs/integration/phase_J0_DEMO_report.md", "phase_J0_DEMO_report.md"),
    ("docs/integration/phase_J0_DEMO_checks.md", "phase_J0_DEMO_checks.md"),
    ("docs/integration/phase_J0_DEMO_user_guide.md", "phase_J0_DEMO_user_guide.md"),
    ("docs/integration/phase_J0_DEMO_assumptions.md", "phase_J0_DEMO_assumptions.md"),
    ("docs/integration/phase_J0_DEMO_degradation_interfaces.md",
     "phase_J0_DEMO_degradation_interfaces.md"),
    # 风险登记册（第 9 节起为本轮新增的 F-D1…F-D6），是后续阶段的必读入口。
    ("docs/handoff/J0_claude/05_J0_PLANT_DEFECT_AND_KNOWN_RISKS.md",
     "05_J0_PLANT_DEFECT_AND_KNOWN_RISKS.md"),
    ("configs/j0/j0_config.json", "configs/j0_config.json"),
]

UI_FILES = [
    "src/steering_sim/demo/__init__.py",
    "src/steering_sim/demo/scenario.py",
    "src/steering_sim/demo/assessment.py",
    "src/steering_sim/demo/service.py",
    "src/steering_sim/demo/plots.py",
    "src/steering_sim/demo/ui.py",
    "src/steering_sim/demo/cli.py",
    "src/steering_sim/demo/degradation.py",
    "scripts/j0_demo/start_demo.py",
    "scripts/j0_demo/package_phase_j0_demo.py",
    "start_steering_demo.bat",
]

# 本轮为修复交付缺陷而修改的既有文件。
MODIFIED = [
    "src/steering_sim/j0_coupling/runner.py",
    "scripts/j0/build_j0r1_results.py",
    "scripts/j0/package_phase_j0_r1.py",
    "scripts/j0/check_wheel_sign_convention.py",
]

TESTS = [
    "tests/demo/conftest.py",
    "tests/demo/test_demo_scenario_and_assessment.py",
    "tests/demo/test_demo_service_and_ui.py",
]

RESULTS = [
    "outputs/j0_demo/demo_checks.json",
    "outputs/j0_r1/phase_J0_R1_results.json",
]

FIGURE_NAMES = ("fig1_plan_view.png", "fig2_wheel_angles.png", "fig3_strokes.png",
                "fig4_hydraulics.png", "fig5_control.png", "fig6_case_and_supply.png")

README = """# PHASE J0-DEMO 交付包 — 电液转向系统联合仿真平台

**本轮目标：在不新增模型开发的前提下，形成可在当前 Windows 电脑上向甲方展示的
完整电液转向系统工程原型软件。**

## 快速开始

双击项目根目录下的 `start_steering_demo.bat`（本包内也在根目录同名位置）。
界面离线运行，不依赖 Amesim，不需要联网。

若需先做环境自检（不打开界面）：

```bat
start_steering_demo.bat --check-only
```

## 包内容

```
start_steering_demo.bat            一键启动（使用 steering_sim 环境，含中文错误提示）
source/demo/                       中文演示界面与检查逻辑（steering_sim.demo）
source/j0_coupling/runner.py       为结果一致性补上末值行程字段（已修改）
source/scripts/                    启动器、打包器、J0-R1 结果与打包修复脚本
tests/                             演示层回归测试（含界面构建与回放标注）
figures/<工况>/                    四个预设工况各 6 张图（与摘要同一次仿真）
configs/                           J0 配置
phase_J0_DEMO_report.md            总报告：三项检查结果与界面说明
phase_J0_DEMO_checks.md            三项演示前检查的完整证据
phase_J0_DEMO_user_guide.md        用户使用说明
phase_J0_DEMO_assumptions.md       工程假设与剩余问题
phase_J0_DEMO_degradation_interfaces.md   退化/质量评估接口预留说明
demo_checks.json                   三项检查的结构化结果
phase_J0_R1_results.json           J0-R1 结果（字段名与单位已修正）
```

## 两个必须记住的约定

1. **预设结果回放 ≠ 重新运行仿真。** 界面右上角始终显示当前结果来源；
   回放会同时显示缓存时间与代码版本。
2. **实际角 / 机构可达角 / 理想阿克曼角是三个不同的量。** 平台从不把它们
   合成一条曲线，也不把机构偏差记成控制跟踪误差。
"""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _copy(relative: str, target_dir: Path, copied: list[Path],
          strip: str | None = None, name: str | None = None) -> Path:
    source = ROOT / relative
    if not source.exists():
        raise SystemExit(f"缺少交付文件: {source}")
    if name:
        target = target_dir / name
    elif strip and relative.startswith(strip):
        target = target_dir / relative[len(strip):]
    else:
        target = target_dir / source.name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    copied.append(target)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-zip", action="store_true")
    parser.add_argument("--skip-figures", action="store_true",
                        help="暂不复制图像（调试打包脚本时用）")
    args = parser.parse_args()

    if not args.skip_figures:
        checks = ROOT / "outputs" / "j0_demo" / "demo_checks.json"
        if not checks.exists():
            raise SystemExit("请先运行 `python -m steering_sim.demo.cli checks` 生成演示检查结果")
        cache = ROOT / "outputs" / "j0_demo" / "preset_cache"
        if not cache.exists():
            raise SystemExit("请先运行 `python -m steering_sim.demo.cli build-cache` 生成预设缓存")

    if DEST.exists():
        shutil.rmtree(DEST)
    DEST.mkdir(parents=True)

    copied: list[Path] = []
    for relative, name in DOCS:
        _copy(relative, DEST, copied, name=name)
    for relative in UI_FILES:
        if relative.endswith(".bat"):
            _copy(relative, DEST, copied)
        elif relative.startswith("src/steering_sim/"):
            _copy(relative, DEST / "source" / "demo", copied,
                  strip="src/steering_sim/demo/")
        else:
            _copy(relative, DEST / "source" / "scripts", copied, strip="scripts/")
    for relative in MODIFIED:
        if relative.startswith("src/"):
            _copy(relative, DEST / "source" / "j0_coupling", copied,
                  strip="src/steering_sim/j0_coupling/")
        else:
            _copy(relative, DEST / "source" / "scripts", copied, strip="scripts/")
    for relative in TESTS:
        _copy(relative, DEST / "tests", copied, strip="tests/demo/")
    for relative in RESULTS:
        _copy(relative, DEST, copied, name=Path(relative).name)

    if not args.skip_figures:
        # 每个预设工况的图按 key 分开存放，避免不同工况的同名图像互相覆盖
        # （这正是 J0-R1 交付包里"图只有 3 s、摘要却是 5 s"的成因）。
        checks = json.loads((ROOT / "outputs" / "j0_demo" / "demo_checks.json")
                            .read_text(encoding="utf-8"))
        for item in checks.get("presets", []):
            folder = DEST / "figures" / item["key"]
            folder.mkdir(parents=True, exist_ok=True)
            for name in FIGURE_NAMES:
                source = (ROOT / "outputs" / "j0_demo" / item["scenario"] / name)
                if not source.exists():
                    raise SystemExit(f"缺少预设图像: {source}")
                shutil.copy2(source, folder / name)
                copied.append(folder / name)

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
