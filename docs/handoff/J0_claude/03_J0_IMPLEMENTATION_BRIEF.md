# PHASE J0 实施任务书

## 1. 目标、范围和禁止项

实现“控制—L1-Fast 液压—M1 机械”的首次四通道联合调试：一桥外侧轮目标角与车速/轴荷/摩擦系数 → M1 目标机构位置 → PID 阀命令 → 液压压力/流量/位移/力 → 实际机构 q 和 12 轮角 → 道路负载回馈液压。

本阶段只运行四个 2–3 s 小工况，不扫描 3111 工况，不开发退化、寿命和质量评价，不恢复 109-state 模型，不修改 Amesim 文件，不修改 L1-Fast 液压本构方程，也不推倒重写 M1 闭链。

## 2. 必须先实现的适配层

建议在新的 J0 专用包/脚本中实现，保持正式模型隔离。适配层至少提供：

1. `target_angle_to_q_and_stroke(delta_ref)`：调用 `PhaseM1Model.solve_geometry` 得到 `q_ref` 和目标七缸几何行程。
2. `hydraulic_positions_to_q(x4)`：四个液压相对位移反求 `q_front,q4,q5,q6`；连续分支从零位跟踪。
3. `q_to_linkage(q4)`：调用真实闭链得到 12 轮角、七缸几何行程、杆长残差和行程雅可比。
4. `road_load(q, speed, mu, axle_mass)`：复用 M1 的侧向力、附着和道路力矩公式，但只返回当前 q 上的轮胎量和四个广义道路力矩；不得应用 M1 静态柔度角修正。
5. `generalized_load_to_hydraulic_force(Q, dx_dq)`：按虚功把四个广义力矩转成四个液压等效负载力，并检查奇异点和功率符号。

不要依赖 `PhaseM1Model._...` 私有方法作为长期接口。若需少量扩展，应优先写 J0 adapter 包装现有公开求解器，并为输入、单位、连续分支和异常建立测试。

## 3. 四通道暂定映射

通道顺序固定为：

```text
channel_front  -> q_front -> front_group_1
channel_rear_1 -> q4      -> axle4_A + axle4_B   [ASSUMED cross-module mapping]
channel_rear_2 -> q5      -> axle5_A + axle5_B   [ASSUMED cross-module mapping]
channel_rear_3 -> q6      -> axle6_A + axle6_B   [ASSUMED cross-module mapping]
```

前组 `x_front = 0.25*q_front` m 是占位假设。后三组先把液压 x 定义为该组“主等效行程”；建议暂选 A 缸相对长度 `L_A(q)-L_A(0)` 作可逆坐标，B 缸行程由同一 q 的真实几何伴随计算。此选择必须标 `ASSUMED`，不得宣称 L1-Fast 的一个执行器状态就是两只真实缸各自状态或合力已完成实车标定。

每组映射应保存 `x(q)` 和 `J_x=d x/dq`，使用连续单调区间反插值。`abs(J_x)` 低于配置阈值、映射非单调、越界或闭链条件数过大时，标记 `MAPPING_SINGULAR/INFEASIBLE`，禁止静默裁剪。

## 4. 单一状态所有权

J0 的动态状态只有 L1-Fast 的 16 个状态。机械 q、轮角、伴随缸位置和轮胎负载在每个液压 RHS 评价点由当前四个 x 代数计算：

```text
x_hydraulic(t) -> inverse geometry -> q(t)
q(t) -> exact rigid linkage -> wheel angles and seven geometric strokes
wheel angles + operating condition -> Q_road
Q_road + dx/dq -> F_load
F_load -> hydraulic RHS -> xdot, vdot, pressures
```

禁止另行积分 q；禁止同时给同一缸设置 `prescribed_motion_by_alias`；禁止把 `actual_loaded_angle_deg` 再反馈，因为它已含 `-Q/K` 的静态柔度修正。J0 实际轮角是液压 x 所决定的闭链角。

## 5. 负载和符号

对一个标量组坐标 `x=x(q)`：

```text
J_x = dx/dq            [m/rad]
Q_road = Σ M_i*dδ_i/dq [N*m/rad，rad 无量纲]
F_load = Q_road/J_x    [N]
Q_hydraulic = J_x*F_hydraulic
```

L1-Fast 执行器方程为 `m*xddot = F_hydraulic - F_load - ...`，因此正 `F_load` 抵抗正 x。每个子阶段检查 `F_load*xdot` 与 `Q_road*qdot` 的虚功一致性；若选择的 q/长度方向导致符号相反，应在映射配置中显式设置极性，不能改液压方程补偿。

双缸组的严格关系是 `Q = J_A F_A + J_B F_B`。当前只有一个等效液压力，力分配未知；J0 首版可用主等效坐标折算，但必须在输出中保留该限制。不得把一个输出力复制两次后相加。

## 6. PID 和多速率循环

- 液压固定步长 `dt_h=0.0005 s`，建议继续用现有 RK4 形式。
- 控制器每 `dt_c=0.010 s` 更新一次，即每 20 个液压步更新，期间零阶保持命令。
- 每通道一个 PID 或等价的四通道封装；`kp,ki,kd,command_limit` 全部配置化。
- 使用现有 `PIDController` 的条件积分抗饱和；每个工况开始前 `reset()`。
- PID 跟踪目标应是四个机构组的代表行程，不是 12 轮角，也不是把目标角复制四份。
- 主阀命令分别写入 `dirvalve_6,1,8,11`；冗余阀命令首版保持显式配置值，不得遗漏后由隐式默认决定。
- 阀命令到 x 的极性必须通过每通道小幅、短时、无越界扰动确定。前阀 SC_1 曲线与后三阀不同，不能假设四通道同号。

RK4 的每个 stage 使用 stage state 的 x/v 重新计算机构和道路负载，或清楚记录采用的近似；不要在整个 0.5 ms 步内使用与 state 不一致的载荷。

## 7. 初始化

L1-Fast 是预建压正常点模型。复用 `run_phase_l1_fast.py::working_point` 的原则：各通道 pA/pB 初始化为对应供油组的 `regulated_return_rail_pressure`，x=v=0，并设置与初始液压力一致的平衡外载。之后按工况平滑接入道路负载和控制目标，避免把零压充液瞬态误当 J0 响应。

初始化还必须验证：q=0、12 轮角=0、七缸相对行程=0、三桥两轮=0、闭链残差≤1e-9 m。若某组选择 A 缸作代表，液压 x=0 必须严格对应 A 缸零位相对长度。

## 8. 首批工况

按顺序运行，每项先 2 s，不足时最多 3 s：

| ID | 一桥外侧目标 | 车速 |
|---|---:|---:|
| J0-01 | 0° | 0 km/h |
| J0-02 | +2° | 5 km/h |
| J0-03 | −2° | 5 km/h |
| J0-04 | +5° | 10 km/h |

摩擦系数和六桥轴荷从单独 J0 配置显式给出；可用 M1 默认 `mu=0.75`、每桥 11.5 t 作为 `ASSUMED_ENGINEERING_PARAMETER` 初始值。不要先跑全范围。

## 9. 每步和每工况输出

至少保存：时间、目标角、四个 q_ref/q_actual、四个 x_ref/x/v、四个 PID 命令、pA/pB、QA/QB、液压力、等效负载力、四个 `dx/dq`、四个广义道路力矩、12 轮实际角、七缸几何行程、三桥锁止值、杆长残差、供油容量标志、映射条件/奇异标志、轮胎侧偏/需求与饱和侧向力。

工况摘要至少包含稳态轮角误差、最大压力、最大速度/行程、最大闭链残差、第三桥最大绝对角、控制饱和时间比例、积分抗饱和状态、功率/符号检查和 PASS/CONDITIONAL/FAIL。

## 10. 最低测试集

1. 映射零位和 q↔x 往返误差。
2. q→七缸行程与 M1 已有输出一致。
3. 后桥伴随 B 缸始终由同一个 q 产生，不作为独立状态。
4. 前组四轮共用 `q_front`，二桥无独立命令。
5. 三桥全过程严格 0°。
6. 每一闭链杆长残差≤1e-9 m，固定硬点不变。
7. 每通道阀极性小扰动检查。
8. 负载转换虚功/符号检查和雅可比奇异保护。
9. PID 限幅、积分抗饱和和 10 ms 更新保持。
10. 0°直行不产生虚假轮角；左右 ±2°镜像趋势正确。
11. 实际轮角来自实际 x；强制改变 x 时轮角相应改变，而目标不直接穿透。
12. 地面负载只施加一次，禁用 M1 `q_loaded` 柔度路径。
13. 液压压力、容积、状态均有限；供油不足标志被传播。
14. 四个 2–3 s 工况可重复运行并输出完整 12 轮数据。

## 11. 停止条件与交付

遇到下列情况停止该工况并报告，不做“自动修正”：闭链不可达/分支跳跃、`dx/dq` 奇异或非单调、液压腔容积非正、状态 NaN/Inf、超过模型行程、持续供油容量不足、三桥非零、杆长变化、功率符号不一致。

完成后报告哪些映射有证据、哪些仍为 `ASSUMED`，不得声称达到甲方精度。将 J0 源码、配置、测试、四工况结果、图和报告复制到 `E:\15_project\handoff_to_chatgpt\phase_J0\`，生成并 CRC 验证 `E:\15_project\handoff_to_chatgpt\phase_J0.zip`，然后停止等待审核。
