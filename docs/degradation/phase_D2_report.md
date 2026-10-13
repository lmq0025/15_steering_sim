# PHASE D2 电液转向系统当前质量评估与退化性能反馈报告

日期：2026-10-13  
基线：PHASE D1（工作区 HEAD `4c4a6800431374920ea2c219aa8d8f5a396c8ab7`，D1/D2 变更未提交）  
正式模型：`ENGINEERING_STEERING_MODEL` + `ENGINEERING_HYDRAULIC_V1`

## 1. 结论

D2 已完成并停止于当前质量评估阶段，未进入 D3、Gamma Monte Carlo、RUL 或 GUI 重构。

本轮闭合了以下真实计算链：

`D1 顺序任务谱/指定退化状态 → 部件级物理参数 → 22 状态联合积分 → 轮角/缸位移/压力/流量/控制指标 → 部件健康等级 → 整车质量等级`

所有质量指标均来自 `J0Runner.run_case()` 的 22 状态动态结果。没有用损伤比例线性乘轮角误差，也没有在图表层制造退化效果。健康参数 JSON 只读，退化参数以不可变内存对象注入。

最终生产运行共执行 56 个完整动态工况（自然退化 36、指定敏感性 20），全部完成。30 天任务谱预测加质量检查点的核心计算耗时为 **55.15 s**；包含三项额外 D1 反馈证据和全部 CSV/PNG 导出的命令墙钟耗时为 **57.87 s**，满足 60 s 目标。

## 2. D1 载荷反馈补齐

### 2.1 实现

齿轮泵等效暴露不再只依赖固定参考供压和运行时间。每个任务段现在按当前目标角、前一目标角、车速、附着、六桥轴荷和当前退化状态计算：

- 正式机构行程变化及转向过渡时间；
- 各通道道路载荷、缸负载压力和动作体积；
- 每条供油轨的运动需求流量、阀泄漏流量、工作压力；
- 当前磨损参数下的供油平衡压力、可用泵流量、需求比和液压功率；
- 全段泵运行基础暴露，加实际转向动作期间的压力/流量负载附加暴露。

缓存键保留任务顺序相关的前后角、车速、附着、轴荷、泵状态、污染以及损伤刷新分箱。损伤跨过 `refresh_damage_interval=0.02` 后会以新的部件参数重算供油特征，而不是只改变缓存键。

### 2.2 独立证据

见 `d1_load_feedback_validation.csv`：

| 等时 60 s 工况 | 前轨负载压力 | 运动需求流量 | 前泵等效暴露 | 可用流量 | 需求比 |
|---|---:|---:|---:|---:|---:|
| 健康直行 | 24 Pa | 0 | 0.003436 | 0.000356 m³/s | 0 |
| 健康 30° | 2.679 MPa | 0.000176 m³/s | 0.003529 | 0.000356 m³/s | 0.4955 |
| 前泵损伤 0.8、同一 30° | 2.679 MPa | 0.000176 m³/s | 0.003383 | 0.000327 m³/s | 0.5398 |

因此等运行时长下负载会区分泵暴露；同一工况下磨损会真实降低可用供油并提高需求比。状态因子使损伤 0.8 工况的最终增量高于健康工况，即使供压平衡下降使其压力暴露略低。

D1 的解析非负累积、任务顺序、独立部件状态和健康参数不可变约束均保留。

## 3. D2 模块与接口

新增 `src/steering_sim/quality_assessment/`：

- `config.py`：只读加载并校验 D2 阈值、时间步长和工程假设标记；
- `assessment.py`：标准工况、真实动态指标提取、四级分级、部件健康表；
- `parameters_for_assessment()`：互斥支持直接传入工程液压参数对象，或把用户指定的 `DegradationState` 映射为参数对象；
- `QualityAssessor`：强制检查正式液压模型且状态数必须为 22。

自然退化从 D1 顺序预测记录重建第 0/10/20/30 天状态。指定敏感性包括前泵、后泵、单阀 `channel_rear_1`、单缸 `channel_rear_2`、泵阀缸联合五种模式，每种均运行健康、轻度、中度、重度四档。

D1 自然退化的缸泄漏映射保持原上限 `5×10⁻¹² m³/(s·Pa)`。D2 为了验证重度故障可辨识性，单独配置了指定故障包络 `2×10⁻¹¹ m³/(s·Pa)`；它只用于 D2 单缸/联合敏感性，不回写 D1 自然老化模型，并标记为 `ENGINEERING_DESIGN_ASSUMPTION`。

## 4. 标准工况与指标

自然检查点使用同一组 9 个标准工况：0°、低速 ±2°、±10°、停车 ±30°、10 km/h 连续 `0→+10→-10→0`、20 km/h 中速 +10°。反向回零沿用 J1-R2 已验收轨迹。

输出指标包括：

- 十二轮最大/RMS/稳态跟踪误差与整定延迟；
- 四通道真实缸位移误差；
- 最小可用泵流量、最小泵流量余量、泵需求比；
- 最小供压余量、峰值腔压及压力利用率；
- 阀命令饱和比例；
- 峰值液压力及作动能力利用率；
- 稳态压力纹波；
- 单独列出的机构阿克曼几何误差和目标轨迹附着风险。

连续反向工况的缸误差按每个采样点的真实 `x_ref_eff` 与 `x` 计算，不再把回零位置错误地与静态 +10° 最终目标比较。

## 5. 四级质量等级

实现 `HEALTHY / SUBHEALTHY / DEGRADED / DANGEROUS` 四级。每项指标的方向和三级边界集中在 `configs/degradation/d2_quality_thresholds.json`；越过第三边界或动态仿真未完成时为 `DANGEROUS`。输出 `grade_causes` 给出所有造成降级的指标、数值和等级。

整车等级由真实性能指标的最差等级决定，不用部件损伤百分比替代。部件损伤等级另行写入 `component_health_status.csv`。

反向回零是 J1-R2 已知的蓄能器补流应力诊断：健康模型瞬时泵需求比约 1.146、最小瞬时泵余量约 -5.04 L/min，但仍保持最大跟踪误差约 0.178°且零阀饱和。为避免把这个已验收瞬态供油特征误判为自然退化，时间线同时输出：

- `quality_grade`：8 个额定工况的整车等级；
- `stress_diagnostic_grade`：反向回零应力诊断的独立等级与原因。

附着不可行只写风险标志，未放入质量阈值，因而不会被归因成液压退化故障。

## 6. 第 0～30 天自然退化结果

| 天 | 额定质量等级 | 最大轮角误差 | RMS 误差 | 泵需求比 | 最小泵余量 | 最小供压余量 |
|---:|---|---:|---:|---:|---:|---:|
| 0 | HEALTHY | 0.133314° | 0.039897° | 0.798110 | 4.310 L/min | 6.355 MPa |
| 10 | HEALTHY | 0.133294° | 0.039895° | 0.799080 | 4.287 L/min | 6.353 MPa |
| 20 | HEALTHY | 0.133275° | 0.039893° | 0.800052 | 4.265 L/min | 6.351 MPa |
| 30 | HEALTHY | 0.133256° | 0.039892° | 0.801024 | 4.242 L/min | 6.349 MPa |

自然退化很轻且控制器能够补偿，因而角度误差没有单调放大；但供油需求比增加约 0.00291、最小流量余量下降约 0.0683 L/min、供压余量下降约 0.00531 MPa，证明退化并非被忽略。第 30 天部件损伤范围为泵 0.00248～0.00273、阀 0.00352～0.00531、缸 0.000391～0.00220。

## 7. 指定退化敏感性

重度状态的代表结果：

| 模式 | 动态工况 | 等级 | 最大误差 | RMS 误差 | 泵需求比 | 最小泵余量 | 阀饱和 |
|---|---|---|---:|---:|---:|---:|---:|
| 仅前泵 | +10° | DANGEROUS | 0.1263° | 0.0370° | 1.2004 | -2.356 L/min | 0% |
| 仅后泵 | +10° | DEGRADED | 0.1228° | 0.0388° | 1.0509 | -1.214 L/min | 0% |
| 单阀泄漏 | +30° | SUBHEALTHY | 0.0543° | 0.0130° | 0.8673 | 4.593 L/min | 0% |
| 单缸泄漏 | +30° | SUBHEALTHY | 0.0533° | 0.0147° | 0.9288 | 2.465 L/min | 0% |
| 联合退化 | +30° | DANGEROUS | 9.4697° | 1.7996° | 1.1425 | -2.546 L/min | 19.44% |

单部件试验说明控制器能补偿相当一部分角度误差，但泵/阀/缸模式分别改变供油能力、泄漏需求、压力纹波和控制余量。联合重度退化最终产生明显跟踪失效和阀饱和。不同模式由独立部件参数注入，不同步到其他部件。

## 8. 数值与性能

- D2 检查点使用 RK4、液压步长 3.333 ms、控制周期 10 ms；该加速步长只存在 D2 配置中。
- J1-R2 正式默认 0.5 ms 配置未修改。
- 硬件：Intel64 Family 6 Model 183 Stepping 1，16 逻辑 CPU，Windows 10 build 26200。
- 4 个工作进程；56 个动态工况全部完成。
- 30 天 D1 快速预测：1.232 s。
- 质量动态积分：53.918 s。
- 默认任务谱 + 质量检查点核心计算：55.150 s。
- 含额外反馈证据、表格和图片导出的完整命令墙钟：57.867 s。

## 9. 输出

`outputs/degradation/phase_D2/` 包含：

- `quality_assessment_summary.csv`
- `component_health_status.csv`
- `component_parameters.csv`
- `system_quality_timeline.csv`
- `healthy_vs_degraded_performance.csv`
- `assessment_thresholds.json`
- `degradation_sensitivity.csv`
- `d1_load_feedback_validation.csv`
- `system_quality_timeline.png`
- `degradation_sensitivity.png`
- `healthy_vs_degraded_dynamics.png`
- `runtime_performance.json`
- `REPRODUCE.md`

审计结果：56/56 动态工况 `completed=True`；除空的 `failure_reason` 被 pandas 读作 NaN 外，所有数值指标均为有限值；部件损伤范围 0～0.9，无负损伤。

## 10. 测试结果

命令：

```powershell
E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe -m pytest tests\degradation tests\quality_assessment -q -p no:cacheprovider
E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe -m pytest tests\degradation tests\quality_assessment tests\hydraulics_engineering tests\j0_coupling tests\demo\test_j1r2_ui_and_batch.py -q
E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe -m pytest -q -p no:cacheprovider
```

结果：

- D1/D2 专项：**19 passed**，27.32 s；
- J1-R2 相关回归：**128 passed, 2 skipped**，677.51 s；
- 全仓沙箱运行：**593 passed, 1 skipped**，另有同一个 `test_saved_json_schema` 因沙箱拒绝写入/删除 `outputs/test_tmp` 而产生 1 failure + 1 teardown error，2705.43 s；
- 该唯一权限用例在获准环境单独复跑：**1 passed**，5.91 s；
- 综合功能结论：**594 passed, 1 skipped，0 个代码失败**。

## 11. 工程假设与尚未验证事项

以下不是甲方实测数据：

- 全部质量阈值、部件损伤阈值和轻/中/重指定状态；
- D1 泵压力/流量负载权重和所有退化速率；
- D2 指定重度缸泄漏包络；
- 3.333 ms D2 检查点步长的工程加速选择。

待甲方试验标定：泵耐久/污染系数、阀污染泄漏、缸密封泄漏、四级质量边界及重度故障包络。当前结果用于趋势、接口、独立性和物理反馈验证，不应表述为实车寿命或验收限值。

未解决但不阻塞 D2：自然 30 天退化幅度很轻；反向回零健康应力工况存在已知瞬时蓄能器补流；阀响应时间退化和缸摩擦退化仍为预留模式。

留到 D3：随机 Gamma 增量、完整雨流/随机寿命、RUL Monte Carlo 和不确定性区间。D2 未自动进入这些工作。
