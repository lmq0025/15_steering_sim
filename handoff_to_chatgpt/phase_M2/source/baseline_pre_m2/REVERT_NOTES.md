# 撤销记录（M1 两个文件的重建依据）

`model.py` 的三处改动：
1. `GeometryResult` 新增 `geometry_class: str = "OK"` 字段与 `outer_target_reached` 属性；
2. `solve_geometry` 中把 `flags` 循环改为五类状态分类，并新增
   `<dof>:ACKERMANN_TARGET_MISMATCH` 与 `<dof>:LEFT_RIGHT_OPPOSITE` 两个标记；
3. `GeometryResult(...)` 构造调用新增 `geometry_class=geometry_class`。

`config.json` 的两处改动：
1. `geometry.q_envelopes_rad` 按连续延拓结果扩大为
   `q_front ±0.572 / q4 ±0.80 / q5 ±0.164 / q6 ±0.112`；
2. 新增 `geometry.q_solvable_envelope_rad` 与 `geometry.q_envelope_m2_evidence`，
   并改写 `q_envelope_source`。

回退方法（在项目根目录执行）：

```powershell
Copy-Item handoff_to_chatgpt/phase_M2/source/baseline_pre_m2/model.py   mechanics_ackermann_v2/model.py   -Force
Copy-Item handoff_to_chatgpt/phase_M2/source/baseline_pre_m2/config.json mechanics_ackermann_v2/config.json -Force
Copy-Item handoff_to_chatgpt/phase_M2/source/baseline_pre_m2/plots.py   src/steering_sim/demo/plots.py    -Force
Copy-Item handoff_to_chatgpt/phase_M2/source/baseline_pre_m2/ui.py      src/steering_sim/demo/ui.py       -Force
Copy-Item handoff_to_chatgpt/phase_M2/source/baseline_pre_m2/assessment.py src/steering_sim/demo/assessment.py -Force
Copy-Item handoff_to_chatgpt/phase_M2/source/baseline_pre_m2/runner.py  src/steering_sim/j0_coupling/runner.py -Force
```
