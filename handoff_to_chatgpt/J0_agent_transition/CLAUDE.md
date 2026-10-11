# CLAUDE.md — 15所电液转向项目

## 首先阅读

进入 `E:\15_project` 后，先读：

1. `docs/handoff/J0_claude/01_PROJECT_HANDOFF.md`
2. `docs/handoff/J0_claude/02_CODE_MAP_AND_RUNBOOK.md`
3. `docs/handoff/J0_claude/03_J0_IMPLEMENTATION_BRIEF.md`
4. `docs/handoff/J0_claude/04_INTERFACES_AND_RISKS.md`

## 项目与阶段

项目目标：离线 Windows 上实现不依赖 Amesim 的电液转向系统模型，最终覆盖机械、液压、控制、退化和质量预测。

当前阶段仅为 **PHASE J0：控制—液压—机械首次联合调试**。不要提前开发退化、寿命或质量评价。

项目 Python（唯一指定环境）：

```text
E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe
```

PowerShell 从 `E:\15_project` 运行并使用绝对 Python 路径；不要自动安装/升级依赖。

## 当前正式模型

- 液压 L1-Fast：`src/steering_sim/hydraulics_lumped`
  - `LumpedHydraulicSystem.fast_engineering()`
  - `evaluate_hydraulic(..., HydraulicInput)`
  - 4 通道、16 状态、0 管路动态状态、0.5 ms 固定步长。
- 机械 M1：`mechanics_ackermann_v2`
  - `PhaseM1Model`
  - `mechanical_model_input_spec_v1.0.yaml`
  - 4 DOF：`q_front,q4,q5,q6`；12 轮；三桥固定；7 个物理缸几何接口。

旧 `src/steering_sim/hydraulics` 109-state 模型仅是历史证据库，J0 禁止使用。旧 R02B/R02D/R02E 的活动 q3 拓扑也不是 M1/J0 入口。

## J0 不可违反的规则

- 七个物理缸不等于七个独立液压通道；只存在四个动态通道/机构组。
- 暂定映射：front→q_front；rear_1→q4；rear_2→q5；rear_3→q6。后三项为 ASSUMED，不能写成已确认事实。
- 前组 `x=0.25*q_front` 是缺硬点条件下的工程占位，不是甲方标定值。
- 轮角必须由实际液压 x 反求 q，再经真实闭链得到；禁止复制目标角。
- 二桥只随 `q_front`；三桥始终 0°；固定硬点和杆长不能改变。
- 液压积分 x/v；机械 q 为代数量。禁止重复积分机械自由度。
- J0 用道路广义负载经行程雅可比反馈液压；禁止再使用 M1 `q_loaded` 静态柔度角，避免重复载荷。
- 不修改 L1-Fast 本构方程、Amesim 文件、现有机械几何、PID 以外控制、退化和质量评价模块。
- 阀极性、双缸等效力和后三通道桥号缺实物证据，必须配置化、测试并标 ASSUMED。
- 映射雅可比奇异、闭链不可达、腔容积非正、NaN/Inf 时显式失败，不能静默裁剪。

## J0 执行边界

控制周期 10 ms，液压步长 0.5 ms；先运行 2–3 s 的 0°/0 km/h、+2°/5 km/h、−2°/5 km/h、+5°/10 km/h。PID 增益可配置，带限幅和积分抗饱和。不要先扫 M1 全部 3111 工况。

当前 Git 分支 `r02-mechanical-demo-entry`，HEAD `31475626ab39f9737f4113bb8e550ff1d7fae4b0`，工作树原本 DIRTY。禁止 reset、clean、stash、自动 commit/push；保护 `qh1_1*.ame`、`source_materials`、冻结坐标及现有交付。

J0 完成后统一复制到 `handoff_to_chatgpt/phase_J0/`，生成并验证 `handoff_to_chatgpt/phase_J0.zip`，停止等待审核。
