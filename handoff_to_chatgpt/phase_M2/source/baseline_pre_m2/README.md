# PHASE M2 修改前的代码快照

本目录保存 PHASE M2 改动**之前**的版本，供随时回退。

| 文件 | 来源 | 说明 |
|---|---|---|
| `model.py` | 由当前版本逆向撤销 M2 全部改动得到 | 撤销内容：`geometry_class` 字段与属性、五类状态 flags 循环、构造参数。撤销过程记录在 `REVERT_NOTES.md`，结果的 diff 恰好是 M2 的全部改动 |
| `config.json` | 同上逆向撤销 | 机构坐标包络恢复为 `q_front ±0.55 / q4 ±0.65 / q5 ±0.15 / q6 ±0.10`，并移除 M2 新增的证据字段 |
| `plots.py` / `ui.py` / `assessment.py` | 取自 `handoff_to_chatgpt/phase_J0_Demo/source/demo/` | PHASE J0-DEMO 交付版本，即 M2 之前的真实文件 |
| `runner.py` | 取自 `handoff_to_chatgpt/phase_J0_Demo/source/j0_coupling/` | 同上 |

**说明**：M2 开始时曾在 `handoff_to_chatgpt/phase_M2/baseline_pre_m2/` 保存过一份快照，
但该目录在第一次运行 `scripts/m2/package_phase_m2.py` 时被打包器的清理步骤删除。
演示层与 J0 层的文件已从 J0-DEMO 交付包完整取回；M1 的两个文件按上表方式重建，
重建结果已通过语法编译检查，且与当前版本的 diff 恰好等于 M2 的全部改动。
