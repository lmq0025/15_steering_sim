# 复现命令（PHASE HANDOFF）

唯一 Python：`E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe`
工作目录：`E:
_project`

本阶段**不需要安装任何依赖**：`numpy / scipy / pandas / openpyxl / matplotlib /
pytest / Pillow` 全部已装（见 `pyproject.toml` 的 `[project] dependencies` 与
`[project.optional-dependencies]`）。PySide6 未安装，安装需甲方授权。

## 1. 环境核验

```
E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe -c "import sys,numpy,scipy,pandas,openpyxl,matplotlib;print(sys.version);print(numpy.__version__,scipy.__version__,pandas.__version__,openpyxl.__version__,matplotlib.__version__)"
```

## 2. 全仓测试（基线 576 passed，约 17 分钟）

```
E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe -m pytest -q
```

只跑工程模型相关：

```
E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe -m pytest tests/hydraulics_engineering tests/engineering tests/j0_coupling -q
```

## 3. 单工况

```
E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe -m steering_sim.demo.cli run --angle 30 --speed 10 --duration 3.75
E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe -m steering_sim.demo.cli assess --angle 30 --speed 10
```

## 4. 中文界面

```
start_steering_demo.bat
```

## 5. 3111 批量工况（约 30 s）

```
E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe scripts/j1r2/run_j1r2_batch.py
E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe scripts/j1r2/run_j1r2_batch.py --cases 我的工况.xlsx
```

## 6. 代表工况真实动态积分（约 10 分钟）

```
E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe scripts/j1r2/run_j1r2_dynamic.py
E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe scripts/j1r2/run_j1r2_dynamic.py --sequence-only   # 只重跑多段连续指令工况
```

## 7. 从零重建设计与配置（改机械/液压设计时才需要）

```
python scripts/j1r2/retune_front_follower.py --scale 1.39
python scripts/j1/build_engineering_config.py
python scripts/j1/check_gate1_geometry.py
python scripts/j1r2/design_engineering_hydraulics.py --report
python scripts/j1r2/check_step_convergence.py
python scripts/j1r2/run_j1r2_dynamic.py
python scripts/j1r2/run_j1r2_batch.py
python scripts/j1r2/make_j1r2_figures.py
python scripts/j1r2/capture_ui_screenshot.py
python scripts/j1r2/write_j1r2_report.py
python scripts/j1r2/finalize_status.py --tests <测试数>
python scripts/j1r2/package_phase_j1r2.py
```

## 8. 本交接包附加资料重建

```
python scripts/handoff/build_handoff_pack.py
python scripts/handoff/package_codex_handoff.py
```

## 9. 主要结果路径

| 内容 | 路径 |
|---|---|
| J1-R2 报告 | `docs/integration/phase_J1_R2_report.md` |
| 61 角覆盖 | `outputs/j1/gate1_angle_table.csv` |
| 液压选型 | `outputs/j1r2/hydraulic_sizing.json` |
| 3111 结果 | `outputs/j1r2/j1r2_full_cases.csv` / `.xlsx` |
| 18 工况动态 | `outputs/j1r2/dynamic/j1r2_dynamic.json` |
| 时间序列 | `outputs/j1r2/dynamic/<工况>_timeseries.csv` |
| 步长收敛 | `outputs/j1r2/step_convergence.json` |
| 状态块 | `outputs/j1r2/j1r2_status_block.txt` |
