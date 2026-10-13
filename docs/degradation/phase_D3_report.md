# PHASE D3｜任务载荷谱驱动的剩余寿命预测与多模式退化分析

## 1. 交付结论

D3 已完成。软件能够导入顺序保持的 30 天任务谱，从全新、D1 第 30 天或用户 JSON 指定状态开始，逐段继承 2 台齿轮泵、4 个转向阀、4 组等效液压缸的 20 个独立模式状态，预测还能完整执行多少次相同任务，并记录首次失效循环、循环内日期、任务段、限制部件和终止依据。

正式示例从 `D1_DAY30` 开始，结果为：

- 状态：`FAILURE_REACHED`；
- 从当前时刻起还能完整执行 130 次 30 天任务；
- 第 131 次任务的第 6.465278 天，在 `D07-S07` 段首次达到终止条件；
- 限制部件：前通道转向阀 `valve:channel_front`；
- 原因：阀响应迟滞模式损伤 `0.900032 >= 0.9` 的独立部件硬限值；
- 从新件累计口径：D1 已完成 1 次，加后续 130 次，共完整完成 131 次；
- 对应当前时刻起的运行时间为 3906.465278 天。

上述寿命数值是 `ENGINEERING_DESIGN_ASSUMPTION`，标记为 `PENDING_CLIENT_CALIBRATION`，不能解释为甲方实测寿命。

## 2. 实现范围

### 2.1 P0：确定性剩余任务循环寿命

新增 `RepeatedMissionRULPredictor`，采用两级判断：

1. 第一级逐段解析推进六模式损伤。保留任务顺序、上一转角、部件当前状态和段内首次越限位置；损伤跨 30 天任务继承，未达到上限时返回 `NOT_REACHED_WITHIN_HORIZON`，不把计算上限伪装成寿命。
2. 损伤每跨越 0.05 刷新区间时，重新调用 D1 负载特征计算，并根据当前泵机械效率/功率能力、阀迟滞、阀泄漏和缸摩擦修正供油及压力负载特征。
3. 在循环 0、约 25%、50%、75% 和候选寿命点运行 D2 的 `STD_L10`、`STD_L30` 两个额定工况，均使用正式 22 状态 `ENGINEERING_HYDRAULIC_V1`。反向回零应力诊断和附着风险不进入默认寿命终止。
4. 若稀疏真实检查只能证明系统失效位于两个检查点之间，返回 `FAILURE_BRACKETED`；质量验证异常返回 `INDETERMINATE`，不会输出虚假精确寿命。

本示例的真实质量检查点如下：

| 后续任务循环 | 额定质量等级 | 最大跟踪误差/deg | 最小泵流量余量/(L/min) |
|---:|---|---:|---:|
| 0 | HEALTHY | 0.126255 | 5.434224 |
| 33 | HEALTHY | 0.129605 | 3.225108 |
| 66 | SUBHEALTHY | 0.131977 | 1.083648 |
| 98 | DEGRADED | 0.134167 | -1.292036 |
| 131 | DEGRADED | 0.132560 | -2.668791 |

控制器补偿使轮角误差变化较小，但供油余量和需求比已经真实恶化。第 131 循环额定质量尚未达到 `DANGEROUS`，所以正式终止由阀响应迟滞硬限值触发，而非人为把损伤比例乘到轮角误差上。

### 2.2 P1：三类部件六种退化模式

每个实例的两种模式都有独立 `ComponentDamageState`、等效暴露、状态因子、物理参数映射、上下限、硬失效阈值和 Gamma 尺度：

| 部件 | 模式 | 物理模型入口 |
|---|---|---|
| 齿轮泵 | 内泄漏磨损 | 压差内泄漏降低实际可用流量；不再用第二个效率因子重复扣流 |
| 齿轮泵 | 机械损失 | 机械效率影响输入功率，并通过显式额定驱动功率限制高压可用流量 |
| 转向阀 | 内泄漏磨损 | P-T 泄漏支路进入供油需求和压力连续方程 |
| 转向阀 | 响应迟滞 | `lag_time_s * lag_scale` 直接进入阀芯一阶动态状态 |
| 液压缸 | 内泄漏磨损 | A-B 腔内泄漏一减一加进入两腔压力方程 |
| 液压缸 | 摩擦增长 | `friction_scale` 直接放大库仑/黏性摩擦并进入活塞受力方程 |

泵机械效率模式不会被解释成容积流量损失。零机械损伤时功率约束完全禁用，D3 六模式全健康状态与原健康 RHS 逐元素一致。`six_mode_physical_injection.csv` 记录六种单模式注入对 RHS、泵流量/输入功率、阀泄漏、缸泄漏、阀芯导数和活塞加速度的实际影响。

### 2.3 P2：雨流计数

实现无外部依赖的 ASTM 风格四点雨流计数：

- 从顺序拼接的液压缸有符号实际载荷估计序列提取峰谷；
- 段边界不重置算法，残余半循环在完整序列中统一处理；
- 输出范围、幅值、均值、次数、起止记录索引和范围—均值矩阵；
- 雨流等效暴露只进入 `cylinder.friction_growth` 的载荷反转项；缸泄漏磨损继续使用实际绝对滑动距离和压差，避免对同一泄漏机理重复计数。

示例每个缸得到 90.5 个等效计数；等效载荷结果见 `equivalent_cycle_loads.csv`。人工序列 `[0,1,0,1,0]` 的测试结果为 2.0 个单位范围循环。

### 2.4 P3：Gamma 与 Monte Carlo

随机模式以确定性损伤增量为期望，使用非负 Gamma 增量：

`shape = E[ΔD] / gamma_scale_damage`，`scale = gamma_scale_damage`。

相同模式使用固定尺度，因此等价暴露拆分后的独立增量具有可加的 Gamma 过程统计性质。随机状态逐循环反馈到非线性状态因子和部件硬阈值；寿命不是给确定性寿命乘随机系数生成的。

默认 128 条路径、种子 `20261013` 的结果：

| 寿命分位数 | 首次失效任务循环 |
|---|---:|
| P05 | 127 |
| P10 | 128 |
| P50 | 130 |
| P90 | 132 |
| P95 | 133 |

本次 0 条右删失；若路径在预测上限内未失效，会明确保存为 `RIGHT_CENSORED`，不会按上限循环判为失效。上述区间是随机路径寿命分位区间，不是统计均值的置信区间，也不是实测寿命分布。

## 3. 配置、接口和兼容性

- D3 配置：`configs/degradation/d3_rul_models.json`。
- 多模式状态与映射：`src/steering_sim/degradation/multimode.py`。
- 寿命推进：`src/steering_sim/degradation/rul.py`。
- 雨流计数：`src/steering_sim/degradation/rainflow.py`。
- Gamma/Monte Carlo：`src/steering_sim/degradation/stochastic.py`。
- 正式运行入口：`scripts/d3/run_phase_d3.py`。
- D1 `predict()` 仅增加可选初始外轮角，默认仍为 0°；段记录新增阀/缸等效暴露和有符号载荷列，历史调用兼容。
- 工程泵退化参数新增机械效率和可选驱动功率上限，默认 `rated_drive_power_w=0`，旧配置和健康模型不改变。
- D2 可用泵流量指标改为调用正式 `available_pump_flow()`，因此能够识别 D3 功率约束。

支持的初始状态：

- `--initial-state healthy`：全新健康状态；
- `--initial-state d1_day30`：先计算输入任务谱的 D1 第30天状态；
- `--initial-state <json>`：读取以 `pump:front:leakage_wear` 等平面模式键表示的用户状态。

## 4. 输出清单

正式结果目录为 `outputs/degradation/phase_D3/`，包括：

- `rul_prediction_summary.json/csv`、`mission_cycle_history.csv`、`first_failure_details.json`；
- `component_degradation_modes.csv`、`component_parameter_trajectories.csv`、`component_failure_thresholds.json`；
- `quality_over_mission_cycles.csv`、`quality_checkpoint_case_details.csv`；
- `quality_vs_mission_cycles.png`、`healthy_vs_eol_dynamics.png`；
- `rainflow_cycle_count.csv`、`rainflow_matrix.csv`、`equivalent_cycle_loads.csv`；
- `monte_carlo_rul_summary.csv`、`monte_carlo_rul_samples.csv`、`stochastic_degradation_paths.csv`；
- `rul_distribution.png`、`stochastic_degradation_paths.png`；
- `six_mode_physical_injection.csv`、`reproducibility_and_performance.json`。

所有正式输出记录任务谱、D1/D2/D3 配置哈希、模型版本、随机种子、预测方式、硬件和实际墙钟时间。健康参数文件 SHA-256 在预测前后均为 `9720085e65c4af961bca81305e3bd088e6bad6093141dc6de56bef41b9b5cdcc`。

## 5. 性能

测试环境：Windows 10 build 26200，Intel64 Family 6 Model 183，16 逻辑 CPU，Python 3.11.16；只使用项目指定解释器。

- 确定性寿命预测（131 个候选循环、10 个 22 状态动态工况）：22.771849 s；
- 128 条 Gamma 随机路径：1.256844 s；
- 结果和绘图在内的总运行：26.636015 s。

确定性与随机默认模式均小于 60 s。性能不是通过删除真实动态检查实现；本次确实运行了 5 个状态检查点、每点 2 个完整 22 状态工况。

## 6. 测试结果

- D3 新增验收：15 passed（0.87 s）。
- D1/D2/工程液压/J1-R2 相关专项：134 passed（237.55 s）。
- 全仓沙箱运行：605 passed、1 skipped；唯一用例因 Windows 沙箱拒绝
  `outputs/test_tmp` 临时目录写入和清理而同时产生 1 failed/1 error。该同一历史用例在获准的
  非沙箱环境单独复核为 1 passed（3.91 s）。因此功能性合计为 606 passed、1 skipped，
  没有 D3、D2、D1 或 J1-R2 功能回归失败。全仓沙箱运行耗时 960.14 s。
  全仓运行后又补充的 `FAILURE_BRACKETED`、`INDETERMINATE` 和随机系统质量规则
  3 项均通过；按当前测试集汇总为功能性 609 passed、1 skipped。

D3 测试覆盖状态继承、解析首次失效、未达到寿命、部件独立、六模式 RHS 影响、齿轮泵效率去重、雨流人工序列、Gamma 非负/复现/均值/拆分统计、右删失、健康文件只读和零模式健康 RHS 精确兼容。

复现命令：

```powershell
E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe scripts/d3/run_phase_d3.py --spectrum E:\15_project\data\degradation\task_spectrum_30day_example.csv --initial-state d1_day30
E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe -m pytest tests/degradation/test_d3_rul.py -q
E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe -m pytest tests/degradation tests/quality_assessment tests/hydraulics_engineering tests/j0_coupling -q
E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe -m pytest -q
```

## 7. 工程假设与待标定项

以下全部不是甲方实测值，必须由耐久、污染、温升、内泄漏、驱动功率和整车性能试验标定：

- 六模式退化率、非线性状态因子和最大损伤；
- 泵机械效率下降斜率、额定驱动功率余量；
- 阀最大迟滞倍数、缸最大摩擦倍数；
- 六模式独立硬失效阈值；
- 雨流参考载荷、指数和摩擦损伤权重；
- Gamma 尺度参数及部件间相关性；
- D2 四级质量阈值和系统 `DANGEROUS` 终止规则。

D2 健康分级阈值没有被偷换成 D3 实物报废限值；D3 硬限值在独立文件中明确列出。

## 8. 当前可信度限制

- 没有甲方退化与寿命试验，当前可验证的是状态继承、物理接入、算法一致性和趋势，不是绝对寿命准确度。
- 快速载荷层使用 J1-R2 几何/道路负载和供油方程的等效特征，不对每个长期任务段做 0.5 ms 积分；关键检查点才运行完整 22 状态动力学。
- 随机路径使用小样本、独立 Gamma 模式；尚未标定共因污染、批次差异和模式相关性。
- 系统性能若只在稀疏真实检查点间越限，只报告 `FAILURE_BRACKETED`。当前正式结果由逐段部件硬阈值精确定位，不存在该区间不确定性。
- 示例任务谱中部分中文段名继承了历史 CSV 的编码显示问题；寿命定位仍保留稳定的 `D07-S07` 前缀和原始输入哈希。

## 9. 停止条件

D3 的 P0–P4 已完成并停止。未进入 PySide6 GUI 重构，也未修改机械坐标、正式几何意义或旧 Amesim/L1-Fast 路径。
