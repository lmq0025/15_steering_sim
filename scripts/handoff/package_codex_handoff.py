"""PHASE HANDOFF 打包器 → ``handoff_to_chatgpt/CODEX_HANDOFF_20261012.zip``。

只打包**交接资料**：主文档、接口映射、参数快照、最小源码索引，以及下一阶段
要直接扩展的液压工程模块源码。**不打包** Amesim 原始文件、Conda 环境、
历史输出与上一阶段已经交付过的结果 CSV。

**不会删除任何快照目录**：只重建 ``handoff_to_chatgpt/CODEX_HANDOFF_20261012/``
这一个由本脚本生成的目标目录。
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs" / "handoff"
DEST = ROOT / "handoff_to_chatgpt" / "CODEX_HANDOFF_20261012"
ZIP = ROOT / "handoff_to_chatgpt" / "CODEX_HANDOFF_20261012.zip"
MAIN_DOC = "CODEX_HANDOFF_20261012.md"

#: 交接资料（相对 docs/handoff）。
DOCUMENTS = (
    MAIN_DOC,
    "README.md",
    "REPRODUCE.md",
    "codex_interface_map.json",
    "codex_handoff_baseline.json",
    "degradation_interface_audit.csv",
    "degradation_feature_sources.csv",
    "CONFIG_SNAPSHOT.json",
)

#: 下一阶段要直接扩展的模块：随包附上源码（很小，便于离线对照）。
SOURCE_EXCERPTS = (
    "src/steering_sim/hydraulics_engineering/__init__.py",
    "src/steering_sim/hydraulics_engineering/parameters.py",
    "src/steering_sim/hydraulics_engineering/model.py",
    "src/steering_sim/hydraulics_engineering/authority.py",
    "src/steering_sim/demo/degradation.py",
)

#: 最小源码索引里要列出的关键文件（不打包内容，只给出定位与校验）。
SOURCE_INDEX = (
    ("机械模型（正/逆运动学入口）", "src/steering_sim/engineering/model.py"),
    ("机械传动内核（闭式机构求解）", "src/steering_sim/engineering/mechanism.py"),
    ("液压参数类（退化接口所在）", "src/steering_sim/hydraulics_engineering/parameters.py"),
    ("液压模型（22 状态、两条供油轨）", "src/steering_sim/hydraulics_engineering/model.py"),
    ("阀极性/力窗口探针", "src/steering_sim/hydraulics_engineering/authority.py"),
    ("联合仿真运行器（多速率闭环）", "src/steering_sim/j0_coupling/runner.py"),
    ("行程↔机构坐标映射", "src/steering_sim/j0_coupling/geometry.py"),
    ("道路载荷与附着", "src/steering_sim/j0_coupling/road_load.py"),
    ("配置装载与校验", "src/steering_sim/j0_coupling/config.py"),
    ("控制器（PID + 前馈 + 饱和诊断）", "src/steering_sim/control/pid.py"),
    ("控制器契约", "src/steering_sim/control/base.py"),
    ("演示服务层（唯一计算入口）", "src/steering_sim/demo/service.py"),
    ("工况定义与预设", "src/steering_sim/demo/scenario.py"),
    ("批量与 CSV/XLSX 导入导出", "src/steering_sim/demo/batch.py"),
    ("运行前检查与一致性校验", "src/steering_sim/demo/assessment.py"),
    ("结果绘图", "src/steering_sim/demo/plots.py"),
    ("中文界面（迁移 PySide6 时唯一需要重写的文件）", "src/steering_sim/demo/ui.py"),
    ("命令行入口", "src/steering_sim/demo/cli.py"),
    ("过时的退化占位模块（需先处理）", "src/steering_sim/demo/degradation.py"),
    ("一键启动脚本", "scripts/j0_demo/start_demo.py"),
    ("一键启动 BAT", "start_steering_demo.bat"),
    ("机械机构设计参数", "configs/j1/engineering_mechanism.json"),
    ("机械模型配置（含包络）", "configs/j1/engineering_config.json"),
    ("工程液压参数（退化落点）", "configs/j1r2/engineering_hydraulics.json"),
    ("联合仿真配置（步长/控制/验收门限）", "configs/j0/j0_config.json"),
    ("客户原始几何（不得修改）", "mechanical_model_input_spec_v1.0.yaml"),
    ("液压工程模型测试", "tests/hydraulics_engineering/test_engineering_hydraulics.py"),
    ("界面与批量测试", "tests/demo/test_j1r2_ui_and_batch.py"),
    ("J0 集成层测试", "tests/j0_coupling/test_j0_load_and_authority.py"),
    ("机械模型测试", "tests/engineering/test_j1_model.py"),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_source_index(dest: Path) -> Path:
    lines = ["类别,相对路径,行数,字节数,sha256,是否随包附带源码"]
    excerpted = set(SOURCE_EXCERPTS)
    for purpose, relative in SOURCE_INDEX:
        path = ROOT / relative
        if not path.exists():
            lines.append(f"{purpose},{relative},MISSING,,,")
            continue
        text = path.read_bytes()
        try:
            count = len(path.read_text(encoding="utf-8").splitlines())
        except UnicodeDecodeError:
            count = ""
        lines.append(f"{purpose},{relative},{count},{len(text)},"
                     f"{_sha256(path)},{'是' if relative in excerpted else '否'}")
    target = dest / "SOURCE_INDEX.csv"
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dest", default=str(DEST))
    parser.add_argument("--zip", default=str(ZIP))
    parser.add_argument("--docs", default=str(DOCS))
    args = parser.parse_args()
    dest = Path(args.dest)
    archive = Path(args.zip)
    docs = Path(args.docs)

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
    for name in DOCUMENTS:
        source = docs / name
        if not source.exists():
            missing.append(str(source.relative_to(ROOT)))
            continue
        shutil.copy2(source, dest / name)

    for relative in SOURCE_EXCERPTS:
        source = ROOT / relative
        if not source.exists():
            missing.append(relative)
            continue
        target = dest / "key_sources" / Path(relative).relative_to("src/steering_sim")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    _write_source_index(dest)
    shutil.copy2(ROOT / "scripts" / "handoff" / "build_handoff_pack.py",
                 dest / "build_handoff_pack.py")
    shutil.copy2(ROOT / "scripts" / "handoff" / "package_codex_handoff.py",
                 dest / "package_codex_handoff.py")

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
