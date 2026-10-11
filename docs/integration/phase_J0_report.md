# PHASE J0 初步结论报告（控制—液压—机械首次联合调试）

| | |
|---|---|
| 阶段 | PHASE J0（控制—L1-Fast 液压—M1 机械首次联合调试） |
| 状态 | **结构已打通、可运行、有测试；四通道闭环跟踪被液压模型缺陷阻断** |
| 日期 | 2026-10-11 |
| 分支 / HEAD | `r02-mechanical-demo-entry` / `31475626ab39f9737f4113bb8e550ff1d7fae4b0`（工作树 DIRTY，与交接一致；未做任何 reset/clean/stash/commit） |
| 环境 | `E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe`，Python 3.11.16 |
| 上游文档 | `docs/handoff/J0_claude/01…04`；本轮新增 `docs/handoff/J0_claude/05_J0_PLANT_DEFECT_AND_KNOWN_RISKS.md` |
| 交付物 | `handoff_to_chatgpt/phase_J0/`、`handoff_to_chatgpt/phase_J0.zip` |
| 语言约定 | 报告、结论、状态说明、图注一律简体中文；变量名、枚举值、异常消息、`PASS/CONDITIONAL/FAIL` 等技术标识保留英文 |

---

## 1. 总体结论

J0 要求的完整计算链**已经实现并逐段验证**：

```
整车目标转角 + 工况
  → M1 阿克曼 + 真实闭链 → 四组目标行程 q_ref / x_ref          ✅
  → 四通道 PID（10 ms，限幅 + 条件积分抗饱和）                  ✅
  → 四通道阀命令 dirvalve_6/1/8/11                              ✅
  → L1-Fast 压力 / 流量 / 液压力 / 实际缸位移 x,v                ✅
  → 实际缸位移反求 q_front,q4,q5,q6（单调区间反插值）            ✅
  → 真实闭链 12 轮角 + 七缸几何行程 + 杆长残差                   ✅
  → 简化地面负载 → 行程雅可比虚功 → 液压等效外载                 ✅
  → 下一步                                                      ⛔ 闭环发散
```

**最后一环不成立的原因不在 J0 层，而在交付的 L1-Fast V1 液压模型本身。**
本轮在两处独立实验中发现：

* **F1（阻断）**：四个通道的液压阻尼与刚度符号都是发散的
  （`dF_hyd/dv > 0`、`dF_hyd/dx > 0`）。被动执行器必须 `dF/dv < 0`、`dF/dx < 0`。
* **F2（阻断）**：`channel_front` 的静态作动力窗口只有 **33 N**，
  而前端组在 J0-02 需要约 **6 249 N**。一桥、二桥（12 轮中的 4 轮）无法被驱动。

两项都属于"已冻结的液压本构"，J0 阶段禁止修改，且 **PID 无法补偿**
（负阻尼项对任意反馈增益都保持不稳定；20 组增益实测 19 组在 0.03–0.18 s 内失败）。

详细证据、根因定位（代码行级）和最小修复选项见：
**`docs/handoff/J0_claude/05_J0_PLANT_DEFECT_AND_KNOWN_RISKS.md`**。

---

## 2. 环境与既有模型核实

| 项目 | 结果 |
|---|---|
| 唯一指定 Python | `E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe`，`sys.executable` 已确认，3.11.16 |
| `AGENTS.md` | 不存在（已确认根目录及三级子目录） |
| `git status --short` | 与交接文档描述一致：工作树 DIRTY，含大量未跟踪 L1/M1 交付；`tools/Simcenter-Amesim-MCP` 子模块 dirty |
| L1-Fast 核心测试 | `tests/hydraulics_lumped/test_l1_fast_regulated_supply.py` → **8 passed in 0.33 s** |
| M1 测试 | `tests/mechanics_ackermann_v2/test_phase_m1.py` → **22 passed in 21.54 s** |
| 未修改 | L1-Fast 本构方程、M1 闭链、`mechanical_model_input_spec_v1.0.yaml`、Amesim 文件、现有 PID、退化/质量模块 |

交接文档与源码**没有**重大矛盾；`LumpedHydraulicSystem.fast_engineering()`、
`evaluate_hydraulic()`、`PhaseM1Model`、`PIDController` 均按文档所述存在且可调用。
本轮发现的两项阻断是"文档未覆盖的模型行为"，不是"文档与代码不符"。

---

## 3. 本轮新增的 J0 联合仿真层（独立、不改动正式模型）

```
src/steering_sim/j0_coupling/
    config.py        J0 配置的类型化加载与校验（含 ASSUMED 标签）
    geometry.py      四通道代表行程 ↔ q 映射（自建单调表 + 逆解 + 精确闭链）
    road_load.py     实际 q 上的 M1 道路力矩与虚功折算（禁用 q_loaded 柔度路径）
    authority.py     逐通道阀极性小扰动试验与静态力窗口实测
    diagnostics.py   被控对象表征（dF/dv、dF/dx、力窗口、线性化稳定性指标）
    runner.py        10 ms 控制 / 0.5 ms 液压多速率闭环运行器（RK4，逐 stage 一致载荷）
    reporting.py     CSV / JSON / 三张必需图
configs/j0/j0_config.json
scripts/j0/run_j0.py               四个工况入口
scripts/j0/run_j0_diagnostics.py   被控对象诊断入口
scripts/j0/run_j0_gain_study.py    PID 增益敏感性研究入口
tests/j0_coupling/                 J0 最低测试集
```

设计要点：

* **单一状态所有权**：动态状态只有 L1-Fast 的 16 个。机械 `q`、12 轮角、七缸行程、
  轮胎负载在每个 RK4 stage 由当前四个 `x` **代数**求出，机械层不积分任何自由度。
* **不复用目标角**：轮角一律来自实际 `x` → `q` → 真实闭链。
* **道路负载只施加一次**：调用 M1 的地面公式，但**不**调用 `solve_loaded_case` 的
  `q_loaded = q − Q/K` 静态柔度路径（有专门的测试守住这一点）。
* **虚功换算是恒等式**：`F_load = Q_road / (dx/dq)`，`F_load·ẋ ≡ Q_road·q̇`
  实测残差 ≤ 4.4e-16（不是靠比例系数凑出来的）。
* **显式失败**：映射奇异、超包络、非单调、腔容积非正、NaN/Inf、三桥非零、
  杆长残差超限，一律停机并记录原因，不做静默裁剪。

---

## 4. 四通道 ↔ 四机构自由度映射

| 液压通道 | 阀 | 执行器 | 机构自由度 | 七缸接口 | 代表行程 `x` | 证据等级 |
|---|---|---|---|---|---|---|
| 0 `channel_front` | `dirvalve_6` | `actuator002` | `q_front`（一、二桥联动） | `front_group_1` | `x = 0.25·q_front` [m] | 组别关系有证据；**比例 ASSUMED** |
| 1 `channel_rear_1` | `dirvalve_1/2` | `actuator001` | `q4` | `axle4_A + axle4_B` | `L_A(q4) − L_A(0)` | **ASSUMED** 顺序映射；A 缸代表坐标 ASSUMED |
| 2 `channel_rear_2` | `dirvalve_8/9` | `actuator001_1` | `q5` | `axle5_A + axle5_B` | `L_A(q5) − L_A(0)` | 同上 |
| 3 `channel_rear_3` | `dirvalve_11/12` | `actuator001_2` | `q6` | `axle6_A + axle6_B` | `L_A(q6) − L_A(0)` | 同上 |

**七个物理缸 ≠ 七个液压通道**：后三组各有两个真实几何缸 `A/B`，但只有一个等效动态通道；
`B` 缸行程永远由**同一个 `q`** 产生（有测试保证），并保留"单等效坐标/单等效力"的限制声明，
不把一个输出力复制两次求和。

映射表质量（自建，1e-3 rad 步长，从零位连续延拓）：

| 自由度 | q 包络 [rad] | 代表行程范围 [mm] | `min\|dx/dq\|` [m/rad] | 单调 | 最大杆长残差 [m] | 最大条件数 |
|---|---|---|---:|---|---:|---:|
| `q_front` | ±0.55 | ±137.5 | 0.250 | 是 | 3.1e-13 | 16.4 |
| `q4` | ±0.65 | −171.7 … +108.2 | 0.0891 | 是 | 5.6e-14 | 16.4 |
| `q5` | ±0.15 | −35.0 … +33.7 | 0.2181 | 是 | 1.7e-12 | 30.0 |
| `q6` | ±0.10 | −26.3 … +25.7 | 0.2528 | 是 | 4.0e-15 | 39.3 |

* `q ↔ x` 往返误差 ≤ 6.9e-18 rad。
* 表 Jacobian 与 `SixAxleSteeringKinematics.actuator_jacobian` 精确值相对误差 ≤ 3.5e-7。
* 七缸行程与 M1 `cylinder_displacement_mm` 一致到表插值误差（< 20 nm）。
* `q` 包络是**数值连续解范围**，不是甲方机械限位（配置中已如此标注）。

四工况目标（`+2°/5 km/h`、`−2°/5 km/h`、`+5°/10 km/h`）：

| 工况 | 目标外侧角 | `q_front` | `q4` | `q5` | `q6` | `x_front` | `x4` | `x5` | `x6` （mm） |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| J0-02 | +2° | −0.03952 | +0.01180 | +0.05320 | −0.06125 | −9.879 | +2.686 | −12.303 | +15.825 |
| J0-03 | −2° | +0.03952 | −0.01180 | −0.05320 | +0.06125 | +9.879 | −2.708 | +12.135 | −16.067 |
| J0-04 | +5° | −0.09941 | +0.02977 | +0.09039 | −0.09242 | −24.852 | +6.734 | −20.980 | +23.767 |

（M1 的"理想阿克曼角"把 ICR 放在三桥横向线上，因此四、五、六桥在左转时**反向**偏转；
这是 M1 的既定定义，不是错误。）

---

## 5. 阀命令极性与静态作动力实测（§10.7 / §10.13）

做法：从 L1-Fast 预建压工作点出发，对单个通道施加 ±0.01 的短时扰动，
读取 20 ms 自由积分后的速度符号（与 L1-Fast 验收测试同一可观测量）；
静态力窗口则把活塞运动 prescribed 为零、让压力自由松弛到稳态后读取液压力。

| 通道 | 中立命令 | `d(velocity)/d(command)` | 可达 `x` 方向 | 静态力窗口 [N] | 判定 |
|---|---:|---:|---|---:|---|
| `channel_front` | **+1.0** | +8.19e-4 | 仅负方向 | **[0.00, +33.24]** | 单向 + 力可忽略 |
| `channel_rear_1` | 0.0 | +2.216e-2 | 双向 | [−6 039.65, +10 689.50] | 双向正常 |
| `channel_rear_2` | 0.0 | +9.474e-3 | 双向 | [−6 045.07, +10 694.01] | 双向正常 |
| `channel_rear_3` | 0.0 | +5.694e-3 | 双向 | [−6 047.37, +10 695.86] | 双向正常 |

结论：

* **前阀 SC_1 表族（`dirvalve_6`）与后三阀确实不同**，交接文档的警告得到实测确认：
  前通道的中立工作点是 **u = +1.0**（该点 SC_1 四个孔口流量恰为 0），
  命令低于 +1.0 只能把 `x` 推向负方向。
* 四个通道的 `d(velocity)/d(command)` 全为正，配置里 `command_polarity = +1` **由实测确认**，
  不是假定。前通道的中立命令与命令窗口 `[0, 1]` 单独配置。
* **F2**：前通道的静态力窗口上限 33 N，比前端组所需低约 190 倍。

---

## 6. 道路负载与虚功（§10.8 / §10.12）

* 直接复用 M1 的侧向力需求分配、附着力裁剪、原地阻力/回正力矩速度加权公式，
  但**在液压实际产生的 `q` 上求值**，不使用目标工况的 `q`。
* `Q_road(dof) = Σ_i M_i·∂δ_i/∂q`，`F_load = Q_road / J_x`。
* 与 M1 `solve_loaded_case` 的 `generalized_road_moment_Nm` 在同一 `q` 上一致到
  表导数精度（相对差 < 1e-3）。
* **禁用柔度路径**：`tests/j0_coupling/test_j0_load_and_authority.py`
  有专门断言确认 J0 侧不存在 `loaded_q`，且 `q` 只由 `x` 反求。
* 虚功一致性实测残差 ≤ 4.4e-16 N·m/s（恒等式，见 §3）。
* 负载极性（实测，非假定）：四组 `F_load` 与 `x` **同号**，即道路负载起回复作用。

| 自由度 | J0-02 `x` [mm] | `Q_road` [N·m] | `dx/dq` [m/rad] | `F_load` [N] |
|---|---:|---:|---:|---:|
| `q_front` | −9.879 | −1 562.13 | +0.2500 | −6 248.5 |
| `q4` | +2.686 | +332.39 | +0.2277 | +1 460.0 |
| `q5` | −12.303 | +118.30 | −0.2312 | −511.7 |
| `q6` | +15.825 | −454.60 | −0.2561 | +1 775.2 |

---

## 7. 四个工况结果（§8 / §9 / §11）

| 工况 | 目标 | 车速 | 运行时长 | 状态 | 停止时间 | 停止原因 |
|---|---:|---:|---:|---|---:|---|
| **J0-01** | 0° | 0 km/h | 2.0 s（跑满） | **PASS** | — | — |
| J0-02 | +2° | 5 km/h | 0.080 s | FAIL | 0.080 s | `channel_rear_3: MAPPING_OUT_OF_ENVELOPE` |
| J0-03 | −2° | 5 km/h | 0.082 s | FAIL | 0.082 s | `channel_rear_2: MAPPING_OUT_OF_ENVELOPE` |
| J0-04 | +5° | 10 km/h | 0.075 s | FAIL | 0.075 s | `channel_rear_3: MAPPING_OUT_OF_ENVELOPE` |

### J0-01（0°/0 km/h）——PASS，且是严格意义上的通过

在预建压工作点上，四个阀都停在中立命令（前 +1.0、后 0），道路负载在 `q=0` 处恒为 0，
因此 `x=0 → q=0 → F_load=0 → 无液压不平衡 → x=0` 是一个**自洽不动点**。实测：

| 检查项 | 结果 |
|---|---|
| 四个 `x`、`v` | 严格 0（全程） |
| 12 轮角 | 严格 0° |
| 三桥左右轮 | 严格 0° |
| 闭链杆长残差 | **0.0 m** |
| 七缸行程 | 严格 0 |
| 压力 | 恒 1.166 / 0.825 MPa（前后供油轨） |
| 控制饱和比例 | 0.0 |

### J0-02 / J0-03 / J0-04——按 §11 停止条件停机

失败机理（有数据）：阀命令 → 压力升降 → 但由于 **F1 的负阻尼**，运动反过来
强化压差 → 0.1 s 内活塞越过 `q` 数值包络、压力冲到 200–300 MPa
（供油轨仅 0.825 / 2.75 MPa）、速度到 5–7 m/s。运行器按 §11
"映射越界 / 腔容积非正" 显式停机，**没有为了让结果好看而夹紧或裁剪**。

### PID 整定无法挽救（`outputs/j0/gain_study/`）

20 组 `(kp, ki, kd)` 从温和到激进全部测试，1 s × J0-02：

| 增益 | 结果 | 失败时间 |
|---|---|---:|
| (0, 0, 0) | 跑满，但**完全不动作**（平凡不动点） | — |
| (1, 0, 0) | 失败 | 0.181 s |
| (20, 0, 0) | 失败 | 0.104 s |
| (40, 0, 0) | 失败 | 0.088 s |
| (2, 0.2, 0) | 失败 | 0.172 s |
| (2, 0, 2) | 失败 | 0.070 s |
| (2, 0, 10) | 失败 | 0.049 s |
| (1, 0, 30) | 失败 | 0.041 s |
| (0.5, 0, 100) | 失败 | 0.035 s |
| (40, 4, 0.4)（配置基线） | 失败 | 0.080 s |

微分项**使情况变差**：阀→压力→力的时间常数约 8 ms，与 10 ms 控制周期同量级，
未滤波的差分在 10 ms 采样下不再提供相位超前的阻尼，而是变成正反馈。
这与"负阻尼无法用比例/积分项补偿"的线性化结论一致（`m·x'' = c·x' + k·x`，`c>0` 恒不稳定）。

**结论：在 J0 固定的 10 ms 控制周期 + 现有未滤波 PID + 不改物理的约束下，闭环不可能稳定。**

---

## 8. 人为阻尼诊断运行（证明 J0 层本身正确）

为把"液压符号缺陷"与"J0 联合层是否可用"分开，用一个**明确标注为人为**的机械阻尼
（`scripts/j0/run_j0.py --diagnostic-damping 1.5e6`，作用在液压外载上，只用于诊断）
临时镇定被控对象，四个工况均可完整跑满 6 s。结果**只用于验证结构，不作为工况 PASS**。

| 检查项 | 实测（四工况） | 判定 |
|---|---|---|
| 闭链杆长残差 | ≤ 1.6e-12 m | PASS（阈值 1e-9） |
| 三桥左右轮角 | 恒 0.0° | PASS |
| 虚功一致性 | ≤ 4.4e-16 N·m/s | PASS |
| 表 vs 精确轮角 | ≤ 2e-6 ° | PASS |
| 控制饱和 / 抗饱和触发比例 | 0.00 / 0.00 | 未饱和，工作在线性区 |
| 供油容量告警 | 0 | PASS |

行程跟踪（实际/目标，6 s）：

| 工况 | `x_front` | `x4` | `x5` | `x6` |
|---|---:|---:|---:|---:|
| J0-02 | 0 / −9.879 mm（**0%**） | 0.37 / 2.69（14%） | 8.93 / 12.30（73%） | 12.02 / 15.82（76%） |
| J0-03 | 0 / +9.879 mm（**0%**） | −0.29 / −2.71（11%） | 9.51 / 12.13（78%） | −11.57 / −16.07（72%） |
| J0-04 | 0 / −24.852 mm（**0%**） | 3.71 / 6.73（55%） | 18.24 / 20.98（87%） | 22.15 / 23.77（93%） |

两点说明：

1. 后三组没有 100% 到位的**原因是人为阻尼本身就是一个大负载**
   （`c·v`，在 mm/s 量级就是 kN 量级），不是 J0 层的误差；行程轨迹是单调趋向目标的。
2. 前端组 0% 是 **F2** 的直接后果，与人为阻尼无关。

---

## 9. 最低测试集执行情况（§10）

`tests/j0_coupling/`，命令：

```powershell
& 'E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe' -m pytest -q tests/j0_coupling -p no:cacheprovider
```

实测结果：**`77 passed, 1 skipped, 1 xfailed in 113.15 s`**
（`xfailed` = 被 F1 阻断的闭环跟踪能力；`skipped` = 人为阻尼诊断运行，已改为脚本产物）。
既有套件未被改动：L1-Fast 8 passed、M1 22 passed。

| # | 要求 | 覆盖测试 | 结果 |
|---:|---|---|---|
| 1 | 映射零位与 `q↔x` 往返 | `test_zero_position_is_the_reference_configuration`、`test_stroke_to_q_round_trip` | PASS |
| 2 | `q`→七缸行程与 M1 一致 | `test_seven_cylinder_strokes_match_m1` | PASS |
| 3 | 伴随 B 缸由同一 `q` 产生 | `test_companion_cylinder_is_not_an_independent_state` | PASS |
| 4 | 前组四轮共用 `q_front`，二桥无独立命令 | `test_front_group_shares_one_coordinate_and_axle2_follows` | PASS |
| 5 | 三桥全过程严格 0° | `test_third_axle_is_locked_everywhere` | PASS |
| 6 | 杆长残差 ≤ 1e-9 m，硬点不变 | `test_closed_chain_residual_and_hardpoints`、`test_hardpoints_are_frozen` | PASS |
| 7 | 每通道阀极性小扰动检查 | `test_measured_command_polarity_matches_the_configured_polarity` 等 | PASS |
| 8 | 虚功/符号检查与雅可比奇异保护 | `test_virtual_work_identity_holds`、`test_load_conversion_flags_a_singular_jacobian` | PASS |
| 9 | PID 限幅、抗饱和、10 ms 节拍 | `test_pid_clamps_to_the_configured_limit`、`test_pid_conditional_integration_prevents_windup`、`test_control_period_is_an_integer_multiple_of_the_hydraulic_step` | PASS |
| 10 | 0° 直行无虚假轮角；±2° 镜像 | `test_straight_ahead_has_no_spurious_wheel_angle`、`test_mirror_symmetry_between_plus_and_minus_two_degrees` | PASS |
| 11 | 实际轮角来自实际 `x` | `test_actual_wheel_angles_follow_the_actual_stroke`、`test_wheel_angles_come_from_x_not_from_the_target` | PASS |
| 12 | 地面负载只施加一次，禁用 `q_loaded` | `test_road_load_matches_m1_generalised_moment_on_the_same_q`、`test_compliance_correction_is_not_applied_in_the_runner` | PASS |
| 13 | 压力/容积/状态有限；容量告警传播 | `test_pressures_stay_inside_the_regulated_envelope_at_the_working_point` 等 | PASS |
| 14 | 四工况可重复运行并输出完整 12 轮数据 | `test_straight_case_records_the_full_output_set`、`test_run_is_repeatable` | PASS（J0-01；02/03/04 见下） |
| — | **闭环跟踪能力本身** | `test_four_channel_loop_tracks_the_j0_reference` | **xfail（F1 阻断，严格标记）** |
| — | 被控对象负阻尼/负刚度（回归守卫） | `test_delivered_plant_has_negative_hydraulic_damping_and_stiffness` | PASS（记录缺陷现状） |

> 闭环跟踪测试以 `xfail(strict=True)` 记录。**不允许**为了让闭环"通过"而放宽这些断言；
> 液压符号约定解决后，该标记应被移除并重新整定。

---

## 10. PASS / CONDITIONAL / FAIL 汇总

| 项目 | 判定 | 依据 |
|---|---|---|
| **HYDRAULIC-MECHANICAL MAPPING** | **CONDITIONAL** | 结构、单位、符号、往返、雅可比全部 PASS；后三项通道↔桥号与 A 缸代表性为 `ASSUMED` |
| **STRAIGHT（J0-01, 0°/0 km/h）** | **PASS** | 严格不动点，残差 0，三桥锁定，12 轮 0° |
| **LEFT +2 DEG（J0-02）** | **FAIL** | 0.080 s 停止条件（F1） |
| **RIGHT −2 DEG（J0-03）** | **FAIL** | 0.082 s 停止条件（F1） |
| **LEFT +5 DEG（J0-04）** | **FAIL** | 0.075 s 停止条件（F1） |
| **WHEEL ANGLES** | **12/12 输出** | 12 轮角均为实际 `x` 经真实闭链求得 |
| **THIRD AXLE FIXED** | **YES** | 全程严格 0.0°（表与精确求解器双路径一致） |
| **PID TRACKING** | **FAIL** | 20 组增益 19 组失败；唯一"跑满"者为 `(0,0,0)` 平凡解 |
| **MECHANICAL CONSTRAINTS** | **PASS** | 杆长残差 ≤ 1.6e-12 m；硬点不变；条件数 ≤ 39 |
| **HYDRAULIC SANITY** | **FAIL** | `dF/dv > 0`、`dF/dx > 0`（F1）；`channel_front` 静态力 33 N（F2）；冗余阀零流量（F3） |
| **前端组作动能力** | **FAIL** | 需 6 249 N，可用 33 N（F2，与 ASSUMED 轮胎参数无关） |
| **READY FOR NEXT ROUND** | **NO（需先解决 F1/F2）** | 见 §11 |

---

## 11. 尚未确认的假设与待甲方确认项

**本轮新增或确认的 ASSUMED（全部在 `configs/j0/j0_config.json` 中带标签）：**

1. `channel_rear_1/2/3 → q4/q5/q6` 顺序映射（跨模块无证据）。
2. 后三组以 **A 缸相对长度**作为单一等效行程坐标（客户硬点是 `CUSTOMER_GEOMETRY`，
   选 A 缸作代表是工程假设）。
3. 前组 `x = 0.25·q_front` 占位比例（缺甲方前缸两端硬点与真实零位）。
4. 双物理缸 → 单等效通道的力分配未知，J0 只用一个明确命名的等效力。
5. 摩擦系数 0.75、每桥 11.5 t、轮胎侧偏刚度、有效拖距、原地等效半径、机构刚度/阻尼
   全部沿用 M1 默认 ASSUMED 值。
6. 初始平衡外载 `A_a·p − A_b·p` 是**初始化装置**（让 t=0 成为真平衡），不是实测载荷。

**待甲方/液压负责人确认（优先级排序）：**

1. **F1**：HJ020/HJ021 的腔容积与力符号约定，究竟哪一侧权威
   （L1-Fast 与历史 109-state 模型不一致）。
2. **F2**：`dirvalve_6` 的 A 腔在 Amesim 中的真实连接（是否接到低压轨？是否应对称四通？）。
3. **F3**：冗余阀 `dirvalve_2/9/12` 在恒压供油边界下是否应当有流量。
4. 后三液压通道对应的真实桥号；每通道代表 A 缸、B 缸还是双缸合成。
5. 阀与传感器正方向；真实缸行程与机械限位。
6. 实车压力/行程/轮角同步数据（用于最终精度验收；本轮**不宣称**达到甲方 10% 精度）。

---

## 12. 建议的下一步

1. **暂停任何 PID 整定或控制架构工作。** 负阻尼下它们不可能成功。
2. 由液压负责人裁定 F1 的权威符号约定，做**单点**修改并重跑 L1-Fast 验收
   （`tests/hydraulics_lumped/`，注意该套件目前的 8 个用例**不会**发现此问题，
   需要新增 `dF/dv < 0` 与 `dF/dx < 0` 的断言）。
3. 处理 F2（前通道 A 腔连接），使前端组具备 ≥ 7 kN 级的静态作动力。
4. 上述完成后，直接复用本轮 J0 层重跑四工况；届时
   `test_four_channel_loop_tracks_the_j0_reference` 的 `xfail` 标记应被移除。
5. 之后再谈工况精度（10%）与更大范围的工况扫描。

---

## 13. 交付物清单

| 路径 | 内容 |
|---|---|
| `docs/integration/phase_J0_report.md` | 本报告 |
| `docs/handoff/J0_claude/05_J0_PLANT_DEFECT_AND_KNOWN_RISKS.md` | 缺陷正式登记（F1/F2/F3）与最小修复选项 |
| `outputs/j0/J0-0{1..4}_*_timeseries.csv` | 四工况逐步数据（列名带单位） |
| `outputs/j0/J0-0{1..4}_fig1_wheel_angles.png` | 目标 vs 实际 12 轮角 |
| `outputs/j0/J0-0{1..4}_fig2_strokes.png` | 目标 vs 实际四通道行程 |
| `outputs/j0/J0-0{1..4}_fig3_pressure_force_load.png` | 双腔压力 / 液压力 / 等效地面负载 / 广义道路力矩 |
| `outputs/j0/j0_summary.json` | 四工况摘要（含假设、权威性、残差、饱和、虚功） |
| `outputs/j0_diag/J0-0{1..4}-DIAG_*` | 人为阻尼诊断运行（结构验证用，6 s） |
| `outputs/j0/diagnostics/j0_diagnostics.json` + `plant_characterisation.png` | 被控对象表征（F1/F2 证据） |
| `outputs/j0/gain_study/gain_study_J0-02.{json,csv}` | 20 组 PID 增益敏感性 |
| `src/steering_sim/j0_coupling/` | J0 联合仿真层源码 |
| `configs/j0/j0_config.json` | J0 配置（含全部 ASSUMED 标签） |
| `scripts/j0/` | 三个入口脚本 |
| `tests/j0_coupling/` | J0 测试集（含 `xfail` 缺陷标记） |

---

## 14. 最终状态行

```text
PHASE J0 COMPLETE

HYDRAULIC MODEL = L1-FAST V1
MECHANICAL MODEL = M1
CONTROL = FOUR-CHANNEL PID
EQUIVALENT ACTUATION GROUPS = 4
PHYSICAL CYLINDER GEOMETRY = 7
HYDRAULIC-MECHANICAL MAPPING = CONDITIONAL
STRAIGHT = PASS
LEFT +2 DEG = FAIL
RIGHT -2 DEG = FAIL
LEFT +5 DEG = FAIL
WHEEL ANGLES = 12/12
THIRD AXLE FIXED = YES
PID TRACKING = FAIL
MECHANICAL CONSTRAINTS = PASS
HYDRAULIC SANITY = FAIL
TESTS = 77 passed, 1 xfailed, 1 skipped
READY FOR NEXT ROUND = NO
BLOCKING DEFECTS = F1 (四通道液压负阻尼 + 负刚度),
                    F2 (channel_front 静态作动力 33 N，前端组需要 6249 N)
HANDOFF ZIP = E:\15_project\handoff_to_chatgpt\phase_J0.zip
```

**J0 阶段到此停止，等待对 F1/F2 的裁决，不进入退化、寿命或质量评价。**
