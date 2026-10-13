# PHASE D1｜任务载荷谱与关键部件退化预测报告

日期：2026-10-13  
Git 基线：`4c4a6800431374920ea2c219aa8d8f5a396c8ab7`  
正式机械模型：`ENGINEERING_STEERING_MODEL`  
正式液压模型：`ENGINEERING_HYDRAULIC_V1`（22 状态）

## 1. 结论

D1 已完成：30 天顺序任务谱导入、正式机构/道路载荷特征提取、两台齿轮泵/四个转向阀/四个等效缸的独立退化累积、逐段状态继承、工程液压参数内存回写、0～30 天曲线及逐段/最终结果导出。

核心验收链条已经闭合：任务谱中的泵运行时间、供油压差、转向边界动作、通过容积、动作循环、缸绝对滑动距离、载荷与污染严重度分别进入对应部件损伤；保持段不会重复计算一次性转向动作；退化参数进入原 22 状态 RHS，而非在图表层制造差异。

示例 30 天任务谱含 330 个有序工况段，总时长严格为 `2,592,000 s = 30.0 day`。最终复现的纯预测耗时 `0.452 s`，低于 60 秒目标。缓存命中 319 次，11 次刷新计算。

## 2. 已真实实现的功能

1. `CSV/XLSX` 任务谱严格校验必需列、数值范围、布尔泵状态、重复次数及总时长。输入不足或超过指定 30 天会显式失败，不自动补足或截断。
2. 后一段继承前一段目标角和全部部件退化状态。边界转向只计一次；相同目标的保持段滑动距离和阀动作循环为零。
3. 泵停机时泵运行磨损为零；泵运行直行仍按实际运行时间和供油压差累计齿轮泵损伤。
4. 两条供油轨 `front/rear` 各自维护齿轮泵状态；四通道各自维护阀和缸状态，不发生错误同步。
5. 齿轮泵采用齿轮副/端面等效磨损 → 压差内泄漏模型。D1 只用内泄漏扣除流量，容积效率由参考压力下的实际可用流量推导，避免双重扣流量。
6. 阀新增最小 P→T 内泄漏支路。该流量从对应供油轨需求中扣除并流向定压油箱边界，保持流量守恒。
7. 缸内泄漏在 A/B 腔连续方程中一减一加；缸不运动时密封滑动损伤为零。
8. 泵内泄漏非零时，供油初压由 `Q_pump(p) = Q_relief(p)` 数值求解，不再制造虚假充液瞬态。
9. 运行前供油检查按每条供油轨各自的容积效率、内泄漏和平衡压力核算，并计入该轨阀泄漏。
10. `J0Runner` 支持直接接收不可变工程参数内存副本，30 天循环不写临时健康参数 JSON。
11. 旧 `steering_sim.demo.degradation` 保留 GUI/CLI 导入路径，但正式参数类唯一来自 `hydraulics_engineering.parameters.DegradationParameters`；旧 GUI 的 RUL/质量评分仍明确为未实现。

## 3. 统一退化更新与快速计算

各部件使用统一的非负累计形式：

`dD/dE = component_rate × (1 + state_factor_alpha × D)`

代码使用该方程的解析积分，而不是简单 Euler 步进，因此在等价载荷和相同状态条件下，工况段拆分前后的累计损伤保持一致。`D` 被限制在 `[0, maximum_damage]`。

动态转向特征按相邻目标角的正式机构行程差计算，累计行程使用四通道绝对位移增量；稳态保持只给泵运行时间，不重复转向体积、阀循环或缸滑动。缓存键包含前角、后角、车速、附着、六桥轴荷、泵状态、污染严重度及退化刷新分箱，任务段顺序始终保留。

完整雨流计数、Gamma 随机增量和 Monte Carlo 不在 D1 实现范围内。

## 4. 工程假设与待标定参数

配置文件：`configs/degradation/d1_degradation_models.json`。

全部退化速率、压力指数、状态加速系数、最大泄漏系数、温度系数和阈值均标记为 `ENGINEERING_DESIGN_ASSUMPTION / PENDING_CLIENT_CALIBRATION`，没有伪装成甲方实测结果。

液压缸模型参考薛子良所述密封泄漏机理和故障仿真趋势，但没有照搬多级伸缩缸的尺寸、换级结构或绝对健康阈值。当前四个对象仍是 J1-R2 的等效对称缸。

第 30 天示例主要结果：

| 部件 | 第30天损伤范围 | 映射后的主要参数 |
|---|---:|---|
| 前/后齿轮泵 | 0.01243 / 0.01368 | 参考压力容积效率约 0.99266 / 0.99502；内泄漏 `1.243e-13 / 1.368e-13 m³/(s·Pa)` |
| 四个转向阀 | 0.00352～0.00531 | 独立 P→T 内泄漏系数 |
| 四个等效缸 | 0.000391～0.00220 | 独立 A↔B 内泄漏系数 |

这些数值只能用于趋势、软件链路和敏感性验证，不能作为寿命或合格判据。

## 5. 22 状态模型物理回写证据

`outputs/degradation/phase_D1/healthy_degraded_physics_comparison.csv` 使用同一个 22 状态 RHS 做独立部件注入：

- 仅前泵磨损时，前轨可用流量下降；后泵参数保持健康。
- 仅 `channel_rear_1` 阀磨损时，只出现该阀 P→T 泄漏，并改变后供油轨压力导数。
- 仅 `channel_rear_2` 缸磨损时，只出现该缸 A→B 泄漏，并改变该通道两腔压力导数。

`healthy_day30_coupled_comparison.json` 进一步用相同 `5 km/h, +10°` J1-R2 闭环工况对比健康与第 30 天内存参数：两次都数值完成。第 30 天相对健康：

- 前轨最低供压变化 `-0.004689 MPa`；
- 后轨最低供压变化 `-0.009406 MPa`；
- 腔压峰值变化 `-0.010529 MPa`；
- 最终一桥右轮角变化约 `-3.4e-8 deg`。

轮角差很小是控制器补偿结果，不影响“退化已经真实进入压力、流量和控制对象动力学”的结论。

## 6. 输出清单

- 空模板：`data/degradation/task_spectrum_template.csv/.xlsx`
- 完整 30 天示例：`data/degradation/task_spectrum_30day_example.csv/.xlsx`
- 逐段载荷、损伤增量和累计状态：`outputs/degradation/phase_D1/segment_load_damage.csv`
- 0～30 天曲线：`degradation_curves_0_30day.csv/.png`
- 第 30 天参数：`final_component_parameters_day30.csv/.json`
- 风险：`task_spectrum_risks.csv`
- 物理注入对照：`healthy_degraded_physics_comparison.csv`
- 闭环健康/第30天对照：`healthy_day30_coupled_comparison.json`
- 性能与健康文件哈希：`performance_summary.json`

30 天示例每天包含一个 `60 km/h, +20°` 段，附着利用率约 `2.146 > 1`。共输出 30 条 `ADHESION_INFEASIBLE` 风险，计算未崩溃，也没有把该轨迹宣称为车辆可实现。

## 7. 测试与回归

- 修改前快速基线：`83 passed, 1 skipped`。
- D1 专项：`11 passed`。
- D1 + 正式工程液压 + J1 工程模型：`59 passed`。
- 全仓：沙箱内得到 `585 passed, 1 skipped`；唯一失败及 teardown error 均为 Windows 拒绝写入/删除 `outputs/test_tmp/...`，不是断言或模型失败。该唯一用例在沙箱外原命令重跑：`1 passed`。综合功能结果为 `586 passed, 1 skipped`。

健康 J1-R2 配置 SHA-256 在预测前后均为：

`9720085e65c4af961bca81305e3bd088e6bad6093141dc6de56bef41b9b5cdcc`

因此健康基线没有被退化预测修改。J1-R2 原有健康模型测试和闭环代表工况保持通过。

## 8. 复现命令

在 `E:\15_project` 执行：

```powershell
E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe scripts\d1\run_phase_d1.py
E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe -m pytest tests\degradation -q
E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe -m pytest tests\engineering\test_j1_model.py tests\hydraulics_engineering\test_engineering_hydraulics.py tests\degradation -q
E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe -m pytest -q
E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe scripts\d1\run_phase_d1.py --package
```

自定义任务谱：

```powershell
E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe scripts\d1\run_phase_d1.py --spectrum path\to\spectrum.xlsx
```

## 9. D2/D3 留项与未解决问题

留到后续阶段：阀响应时间退化、缸摩擦退化、完整循环/雨流统计、随机 Gamma 增量、RUL Monte Carlo、在线故障诊断、D1 GUI 重构。

D1 软件链路没有尚未解决的功能性问题。当前实质限制是：没有甲方部件退化试验数据，因此所有寿命尺度相关系数仍待标定；D1 不输出寿命、剩余寿命或质量评分。

完成 D1 后停止，不自动进入 D2、D3 或 GUI 重构。
