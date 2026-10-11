# J0 实测发现的液压模型缺陷与已知风险

> ## ⚠ 状态更新（PHASE J0-R1，2026-10-11）
>
> 本文记录的 **F1 与 F2 已在 PHASE J0-R1 修复并验证**，四通道闭环已可稳定运行：
>
> | 缺陷 | 修复 | 验证 |
> |---|---|---|
> | **F1** 力的方向与容积约定不一致 | `actuator.py`：`F_hyd = A_b*p_b - A_a*p_a` | 四通道 `dF/dv < 0`、`dF/dx < 0`；21 项物理测试通过 |
> | **F2** 前桥无有效静态驱动力 | 前阀工作口换位（IR V3 证据）+ 删除 `dirvalve_6` 的 A 腔硬置零 + 撤回 `actuator002` 的人工内泄漏 | 前桥静态力窗口 ±33 N → **±6.2 kN**，双向 |
>
> **F3（冗余阀在恒压边界下无效）仍未处理**，见下文第 3 节与
> `docs/integration/phase_J0_R1_assumptions.md`。
>
> 修复前的四个液压源文件完整备份在
> `handoff_to_chatgpt/phase_J0_R1/baseline_pre_fix/`（含 `SHA256SUMS.txt`）。
> 本轮报告见 `docs/integration/phase_J0_R1_report.md`。
>
> **下文第 0–7 节保留为 J0 结束时的原始缺陷记录**，用于追溯问题如何被发现与定位；
> 其中"当前交付状态无法闭环"等描述已被 J0-R1推翻，请以本节和 R1 报告为准。
> 第 7 节风险登记表中 F1/F2 的处置应读作"已于 J0-R1 修复"。

本文是 PHASE J0 联合调试过程中对 **L1-Fast V1 液压模型** 的实测结论。
所有结论均由只读实验产生，**没有修改任何液压、机械、控制或 Amesim 业务代码**。
每条结论都给出复现命令，任何后续 Agent 都可以独立复核。

阅读顺序仍以 `01_PROJECT_HANDOFF.md` 开始；本文是 J0 结束时追加的证据补充，
优先级高于 `01` 第 2 节对 L1-Fast “工程候选、可直接联调” 的乐观描述。

---

## 0. 一句话结论

> **L1-Fast V1 的四个液压执行器在当前交付状态下无法构成稳定闭环：**
> **四个通道的液压阻尼与液压刚度符号都是发散的（`dF_hyd/dv > 0`、`dF_hyd/dx > 0`），**
> **且 `channel_front` 几乎没有静态作动力（全命令范围约 33 N，而前端组需要约 6.2 kN）。**
> 这两项都是液压模型内部的问题，**PID 无法补偿**，J0 联合层也无法规避。

因此 `03_J0_IMPLEMENTATION_BRIEF.md` 第 9/10 节要求的四通道闭环跟踪，
在当前液压模型上不可实现。J0 交付的是一个**已经打通结构、可运行、可复现、
并能在 0.1 s 内自动停机并报告原因**的联调原型，而不是一个可用的闭环控制器。

---

## 1. 缺陷 F1：全部通道液压阻尼为负（`dF_hyd/dv > 0`）

### 现象

以 1 Hz、±1e-4 m 的 prescribed motion 激励单个通道（机械运动由边界给定，
与积分稳定性完全解耦），用最小二乘拟合 `F = k·x + c·v + b`：

| 通道 | `dF_hyd/dv` [N/(m/s)] | 应为 | 实测判定 |
|---|---:|---|---|
| `channel_front` | **+1.712e3** | < 0 | 负阻尼 |
| `channel_rear_1` | **+4.465e4** | < 0 | 负阻尼 |
| `channel_rear_2` | **+2.819e4** | < 0 | 负阻尼 |
| `channel_rear_3` | **+1.870e4** | < 0 | 负阻尼 |

同时 `dF_hyd/dx` 全部为正（+1.9e1 … +1.3e5 N/m），即**刚度也是发散的**。
对一个被动执行器，压缩腔必须产生回复力，因此 `dF_hyd/dx` 必须为负。

### 后果

* 自由状态下任何非零阀命令都会在 **0.03–0.2 s** 内把活塞驱到行程极限
  （`actuator_rates` 抛 `ValueError: non-positive chamber volume`）。
* 线性化后特征根实部恒为正；**正的机械负载刚度无法改变这一点**
  （`m·x'' = c·x' + k·x`，`c > 0` 时对任意 `k > 0` 都不稳定）。
  这直接否定了 `phase_L1_Fast_report.md` 第 60–62 行
  “the vehicle steering load … will provide the real mechanical constraint”
  的假设：负载只能提供刚度，不能提供补偿负阻尼所需的阻尼。

### 根因（代码级）

`src/steering_sim/hydraulics_lumped/actuator.py` 内部符号不自洽：

| 量 | L1-Fast 写法 | 行 |
|---|---|---|
| 腔容积 | `volume_a0 - area_a*x`（+x **压缩** A 腔） | `chamber_volumes`, L25 |
| 压力方程 | `dp_a = β/V_a*(q_a + A_a*v)`（与其容积约定自洽：`dp=(β/V)(q−V̇)`，`V̇_a=−A_a v`） | L36 |
| **力** | `force = area_a*p_a - area_b*p_b`（+x 由 `p_a` 驱动） | L38 |
| 运动 | `dv = (force − …)/m` | L46 |

容积/压力这一对是自洽的，但 **力约定沿用了“腔 1 随 +x 增大”的旧约定**：
`F = +A_a p_a` 驱动 +x，而 +x 却在压缩 A 腔。于是压缩腔产生的是**推力而不是回复力**，
同时流动产生的压差也强化运动，得到负刚度 + 负阻尼。

对照历史模型 `src/steering_sim/hydraulics/elements/cylinder.py`（L41–L61），
其约定是自洽的：

```python
chamber_volumes_m3(x) = (dead1 + A1*x, dead2 + A2*(stroke - x))   # 腔 1 随 +x 增大
force_n  = A1*p1 - A2*p2 - ...                                     # +x 由 p1 驱动
net1 = q1 - A1*v - leak                                            # dp1 = (β/V1)(q1 - V̇1)
```

**因此这是两个正式液压模型之间的符号约定矛盾**：容积约定相反，力约定相同。
二者必有一个需要翻转（翻转 `force`/`dv` 的符号，或翻转 `chamber_volumes` 的符号），
但这两处都属于“已冻结的液压本构”，J0 阶段禁止修改。

### 复现

```powershell
& 'E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe' scripts/j0/run_j0_diagnostics.py --output outputs/j0/diagnostics
```

输出 `outputs/j0/diagnostics/j0_diagnostics.json` 的 `plant_characterisation` 段，
图中 `plant_characterisation.png` 左、中两栏。

对应测试：`tests/j0_coupling/test_j0_load_and_authority.py::test_delivered_plant_has_negative_hydraulic_damping_and_stiffness`

---

## 2. 缺陷 F2：`channel_front` 无静态作动力

### 现象

把活塞运动 prescribed 为 0，让两腔压力在全命令范围内自由松弛到稳态，
读取该通道的稳态液压力（= 静态作动能力窗口）：

| 通道 | 命令范围 | 静态力窗口 [N] | 宽度 |
|---|---|---:|---:|
| `channel_front` | [0, 1]（中立 = +1.0） | **[0.00, +33.24]** | 33 N |
| `channel_rear_1` | [−1, 1] | [−6039.65, +10689.50] | 16.7 kN |
| `channel_rear_2` | [−1, 1] | [−6045.07, +10694.01] | 16.7 kN |
| `channel_rear_3` | [−1, 1] | [−6047.37, +10695.86] | 16.7 kN |

前通道除了 `u = −1.0` 处的 +33.24 N 以外，**整个命令区间的稳态液压力恒为 0.00 N**。

### 根因（代码级）

`src/steering_sim/hydraulics_lumped/model.py` L180–183 对 `dirvalve_6` 做特判：

```python
if alias == "dirvalve_6":
    # SC_1 local A is an upstream circulation node; only local
    # B is directly the HJ021 chamber represented here.
    physical_a, physical_b = 0.0, vf_local.q_b
```

A 腔的阀口流量被**硬置零**，A 腔只能经 `leakage = 8.33e-11 m³/(s·Pa)`
从 B 腔补油。前执行器 `actuator002` 的双杆结构使 `area_a == area_b`，
于是

```
pA − pB = A_a·v / leakage        →     F_hyd = A²·v / leakage = 1713·v  [N]
```

即前通道在数学上退化成**一个纯负阻尼器（c = −1713 N·s/m）**，没有任何静态力。
这解释了为什么它的静态力窗口只有几十牛、命令方向与力的方向还相反。

### 后果

前端组（一桥 + 二桥，12 轮中的 4 轮）**无法被驱动**。
J0-02 时前端组需要的道路负载为 `Q_road/J_x = −1562.13/0.25 = −6249 N`，
比可用的 33 N 大 **190 倍**。前桥将永远停留在 0°，与目标角无关。

这条结论与轮胎/拖距等 ASSUMED 参数无关：即使把 M1 道路力矩整体缩放 20 倍，
前端组仍然无法作动。

### 复现

同上诊断脚本；另见 `tests/j0_coupling/test_j0_report_and_outputs.py::test_front_group_cannot_reach_its_reference`。

---

## 3. 缺陷 F3：冗余阀在 L1-Fast 边界下恒为零流量（次要）

`supply.py::solve_regulated_constant_pressure`（L385–392）给冗余 SC_1 包装器
（`dirvalve_2/9/12`）传入的 `p_high` 与 `p_low` 同为回油轨压力，
四条孔口支路压差恒等于 0，因此在 **任何命令下都不产生流量**。
实测：把三个冗余阀命令从 0 改到 1.0，三个后通道 0.1 s 后位置仍严格为 0。

后果：`04_INTERFACES_AND_RISKS.md` 第 2 节里“主/冗余阀”双阀结构在 L1-Fast
的恒压边界下**没有实际作动自由度**。J0 配置显式写入冗余命令 = 0 并记录该限制
（`configs/j0/j0_config.json` → `hydraulic.redundant_valve_note`），
但这一条仍是未解释的建模缺口，需要液压负责人确认。

---

## 4. 由 F1 + F2 直接导致的 J0 结果

| 工况 | 目标 | 速度 | 结果 | 停止时间 | 停止原因 |
|---|---:|---:|---|---:|---|
| J0-01 | 0° | 0 km/h | **PASS** | — | 全部状态严格保持在工作点 |
| J0-02 | +2° | 5 km/h | FAIL | 0.080 s | `channel_rear_3: MAPPING_OUT_OF_ENVELOPE` |
| J0-03 | −2° | 5 km/h | FAIL | 0.082 s | `channel_rear_2: MAPPING_OUT_OF_ENVELOPE` |
| J0-04 | +5° | 10 km/h | FAIL | 0.075 s | `channel_rear_3: MAPPING_OUT_OF_ENVELOPE` |

失败表现为：后通道被阀命令驱动 → 负阻尼放大 → 0.1 s 内越过 `q` 数值包络、
压力升到 200–300 MPa（供油轨只有 0.825 / 2.75 MPa）→ 运行器按
`03_J0_IMPLEMENTATION_BRIEF.md` 第 11 节**显式停机并记录**，没有静默裁剪。

PID 整定无法挽救：见 `outputs/j0/gain_study/gain_study_J0-02.csv`，
20 组 `(kp, ki, kd)` 中 **19 组在 0.03–0.18 s 内失败**，
唯一“跑完”的一组是 `(0, 0, 0)`——即完全不动作的平凡不动点。

---

## 5. 这不是 J0 联合层的问题（需要保留的证据）

为了让下一轮能直接判断“修好液压符号后 J0 层是否可用”，
用一个**明确标注为人为**的机械阻尼（`--diagnostic-damping`）临时镇定被控对象后，
J0 层可以完整跑完并保持全部结构约束：

| 检查项 | 实测 | 判定 |
|---|---|---|
| 闭链杆长残差 | ≤ 1.6e-12 m | PASS（阈值 1e-9） |
| 三桥左右轮角 | 恒 0.0° | PASS |
| 虚功一致性 `F_load·ẋ = Q_road·q̇` | ≤ 4.4e-16 | PASS |
| 表 Jacobian vs 精确求解器 | 相对误差 ≤ 3.5e-7 | PASS |
| `q ↔ x` 往返 | ≤ 6.9e-18 rad | PASS |
| 10 ms 控制 / 0.5 ms 液压 ×20 | 配置断言 | PASS |
| 后三组行程跟踪（J0-04, 6 s） | 实际/目标 = 55% / 87% / 93% | 部分 |
| 前端组行程跟踪 | 0% | **FAIL（F2 所致）** |

即：**映射、闭链、道路负载、虚功换算、多速率控制节拍都是正确的；
唯一失效的是 L1-Fast 执行器本身的符号。**

---

## 6. 待液压负责人决策的最小修复选项

以下任一**单点**改动即可让 F1 消失（`dF/dv` 与 `dF/dx` 同时变号），
但都需要先决定哪一侧是权威约定，J0 不自行实施：

1. `actuator.py` `actuator_rates`：`force` 改为 `area_b*p_b - area_a*p_a`
   （或等价地把 `dv` 的符号取反）；
2. `actuator.py` `chamber_volumes`：改为 `volume_a0 + area_a*x, volume_b0 - area_b*x`，
   并把 `dp_a/dp_b` 中 `A*v` 的符号同步翻转（与
   `src/steering_sim/hydraulics/elements/cylinder.py` 的历史约定对齐）。

F2 需要单独处理（`model.py` 对 `dirvalve_6` 的 A 腔硬置零）。
选项：把前通道 A 腔接到低压轨（而不是零流量），或改用对称四通阀表。
这两种都会改变液压本构，必须先确认 HJ021 在 Amesim 中的真实连接。

---

## 7. 风险登记（供后续阶段继承）

| ID | 风险 | 级别 | 当前处置 |
|---|---|---|---|
| F1 | 全通道负阻尼 + 负刚度（两个正式液压模型符号约定矛盾） | ~~阻断~~ **已修复（J0-R1）** | 力方向改为 `F_hyd = A_b*p_b - A_a*p_a`；表征测试已改为assert正确符号 |
| F2 | `channel_front` 无静态作动力（A 腔硬置零） | ~~阻断~~ **已修复（J0-R1）** | 前阀工作口换位 + 删除硬置零 + 撤回人工内泄漏；±6.2 kN 双向 |
| F3 | 冗余阀在恒压边界下零流量 | 中 | 显式配置为 0 并记录 |
| R1 | 后三液压通道 → q4/q5/q6 顺序映射 | 高 | `ASSUMED`，配置化，待甲方确认 |
| R2 | 前组 `x = 0.25·q_front` | 高 | `ASSUMED` 占位，缺甲方硬点 |
| R3 | 双物理缸 → 单等效通道的力分配 | 高 | 单等效坐标/力，输出保留该限制 |
| R4 | 轮胎侧偏刚度、拖距、机构刚度未标定 | 中 | 全部标 `ASSUMED_ENGINEERING_PARAMETER` |
| R5 | q 数值包络不是甲方机械限位 | 中 | 分开报告，不当作限位使用 |

---

## 8. 下一轮的入口

* 联调层：`src/steering_sim/j0_coupling/`（映射 / 道路负载 / 极性 / 多速率运行器 / 诊断 / 出图）
* 入口脚本：`scripts/j0/run_j0.py`、`scripts/j0/run_j0_diagnostics.py`、`scripts/j0/run_j0_gain_study.py`
* 配置：`configs/j0/j0_config.json`
* 测试：`tests/j0_coupling/`
* 结果：`outputs/j0/`（四工况）、`outputs/j0_diag/`（人为阻尼诊断）、`outputs/j0/diagnostics/`

**在 F1 与 F2 解决之前，不要再投入 PID 整定或控制架构工作。**

---

## 9. PHASE J0-DEMO 新增已知问题（2026-10-11）

演示平台封装阶段做了三个演示前检查，新增登记如下（详见
`docs/integration/phase_J0_DEMO_checks.md` 与
`docs/integration/phase_J0_DEMO_assumptions.md`）：

| ID | 风险 | 级别 | 当前处置 |
|---|---|---|---|
| F-D1 | 五、六桥同桥左右轮反号（违反低速共同瞬时中心同向要求） | 高 | 已核查为 M1 闭链在甲方硬点下的**真解**（非映射/符号错误）；保留结果并标记 `ACKERMANN_GEOMETRY_DEVIATION`；不得修改甲方硬点，待甲方确认 |
| F-D2 | M1 `solve_geometry` 仅在拟合触及 q 包络时才报 `NUMERICAL_ENVELOPE_LIMIT`；+5° 时 q5/q6 拟合 RMS 4.26°/4.93°（限值 0.25°）却报 `geometry_status = OK` | 中 | **未修改冻结模型**（改了会使已交付 J0-R1 结果失去可复现性）；改在演示层独立计算并显式标记 |
| F-D3 | 前组中位供油余量仅 1.16 L/min（泵 27.00、高压轨取流 25.84，4.3%） | 中 | 原报警逻辑正确（无真实缺口），但缺"接近上限"档；演示层新增 `SUPPLY_CAPACITY_NEAR_LIMIT` 黄色警告 |
| F-D4 | 前通道闭环稳态残差 0.311°（J0-02/J0-03） | 中 | J0 遗留，已证非整定问题；演示层如实判 `CONDITIONAL` |
| F-D5 | 大转角（≥+20°）下 q5/q6 触及数值包络，闭链不可达 | 中 | 演示平台拒绝运行并报 `GEOMETRY_INFEASIBLE`，不强行外推 |
| F-D6 | 轮胎/地面为简化模型（附着椭圆 + 线性侧偏） | 中 | 沿用既有 `ASSUMED`，附着利用率接近 1 时只作趋势 |

同时修正了两处**交付缺陷**（非模型缺陷）：

* `phase_J0_R1_results.json` 的 `final_stroke_mm` 实为以米为单位的区间 →
  已拆为 `final_stroke_mm`（末值）/ `final_stroke_error_mm` / `stroke_range_mm`；
* J0-R1 交付包的 `figures/` 中，无地面负载（3 s）图覆盖了含地面负载（5 s）图 →
  已分目录（`figures/` 与 `figures_no_road_load/`），交付包已重建。

## 10. J0-DEMO 的入口

* 演示平台：`src/steering_sim/demo/`（`ui.py` 界面、`cli.py` 命令行）
* 一键启动：`start_steering_demo.bat`（纯 ASCII + CRLF；中文由 Python 输出）
* 演示前检查：`scripts/j0/check_wheel_sign_convention.py`、
  `python -m steering_sim.demo.cli checks`
* 测试：`tests/demo/`
* 结果：`outputs/j0_demo/`（四预设图、`demo_checks.json`、`preset_cache/`）
