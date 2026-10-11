# PHASE J0-DEMO 交付包 — 电液转向系统联合仿真平台

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
