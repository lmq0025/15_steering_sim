# PHASE J0-R1 交付包

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
$py = 'E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe'
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
