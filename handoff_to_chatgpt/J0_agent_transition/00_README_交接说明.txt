15所电液转向项目：Codex → Claude Code（J0 前）

项目根目录：E:\15_project
当前任务：PHASE J0 控制—液压—机械首次联合调试

请先阅读同目录 CLAUDE.md，然后依次阅读 docs_handoff 中四份文档：
01_PROJECT_HANDOFF.md
02_CODE_MAP_AND_RUNBOOK.md
03_J0_IMPLEMENTATION_BRIEF.md
04_INTERFACES_AND_RISKS.md

本包仅是入口资料；Claude Code 与 Codex 共用 E:\15_project，正式源码不复制进本包。
液压正式路线：src\steering_sim\hydraulics_lumped（4 通道/16 状态）。
机械正式路线：mechanics_ackermann_v2（4 DOF/12 轮/7 个物理缸几何接口）。
旧 109-state 液压模型不得用于 J0；不得把 7 个物理缸说成 7 个独立液压动态通道。

建议接手后先只读核对源码和接口，简要汇报液压入口、机械入口、四通道映射、闭环方案和阻碍；随后严格按 03_J0_IMPLEMENTATION_BRIEF.md 实施。

交接生成时：分支 r02-mechanical-demo-entry；HEAD 31475626ab39f9737f4113bb8e550ff1d7fae4b0；工作树原本 DIRTY，禁止 reset/clean/stash。
本次交接没有修改液压、机械、控制、Amesim 或其他业务代码，也没有执行 J0。
