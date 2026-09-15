# R02-C1 机械约化动力学核心交接

- 日期：2026-09-15
- branch：`r02-mechanical-dynamics-core`
- R02-B.1：已非 squash 合并至本地 `main`，既有提交记录保留
- 依赖：未新增正式依赖，沿用 NumPy、SciPy 与可选 Matplotlib

## 1. 环境验证

执行：

```powershell
& "$env:CONDA_PREFIX\python.exe" -c "import sys; print(sys.executable)"
```

实际 Python executable：

```text
E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe
```

`docs/ENVIRONMENT.md` 已冻结该环境为唯一正式环境。README、R01 与 R02-B
交接中的旧运行说明已更新；不再要求调整 PATH，也不使用其他 Python 环境。

## 2. 新增动力学架构

`ReducedMechanicalDynamics` 直接组合冻结的 `SixAxleSteeringKinematics`，状态仅为：

```text
y = [q, q_dot]
q = [q_front, q3, q4, q5, q6]
dim(y) = 10
```

它复用 R02-B 的 body poses、hard points、wheel angles、link endpoints、actuator
length/Jacobian 和闭链求解器，没有建立独立关节角状态，也没有修改闭链拓扑或
5-DOF 定义。参与惯性组装的清单为 24 个摆臂/车轮转向节等效刚体和 19 根实际
拉杆，共 43 个构件。

新增接口包括刚体 COM/角速度/任意点 Jacobian、质量矩阵、Christoffel 偏置、
逐刚体动能、执行器与外载荷广义力、零损失模型和 10 状态 RHS。质量矩阵异常时
抛出 `IllConditionedMassMatrixError`；RHS 使用 `numpy.linalg.solve`，不显式求逆。

## 3. 质量矩阵与动能

对每个配置为参与惯性的刚体 i：

```text
v_ci = J_vi(q) q_dot
omega_i = J_wi(q) q_dot
T_i = 1/2 m_i v_ci^T v_ci + 1/2 I_zi omega_i^2

M(q) = sum_i [m_i J_vi^T J_vi + I_zi J_wi^T J_wi]
T = 1/2 q_dot^T M(q) q_dot = sum_i T_i
```

摆臂和车轮/转向节的局部原点为其固定旋转副；拉杆采用端点中点为原点、沿
端点 A→B 为局部 +X 的自然 body frame。COM 与 Izz 仍必须由参数提供。

## 4. h(q,q_dot) 计算

`FiniteDifferenceSettings` 集中设置刚体 Jacobian 和质量矩阵导数的中心差分步长，
后续可替换解析实现。当前按数值 `dM/dq` 使用 Christoffel 形式：

```text
h_i = sum_j sum_k 1/2 (
    dM_ij/dq_k + dM_ik/dq_j - dM_jk/dq_i
) q_dot_j q_dot_k
```

不同步长的 body Jacobian、M 和 h 均有收敛趋势测试；`q_dot=0` 时直接严格返回零。

## 5. 广义力与功率映射

液压执行器继续使用冻结的 8×5 Jacobian：

```text
L_dot = J_act(q) q_dot
Q_hyd = J_act(q)^T F_act
q_dot^T Q_hyd = F_act^T L_dot
```

任意动态刚体局部点的二维外力与绕 +Z 力矩使用：

```text
v_point = J_point(q) q_dot
Q_point = J_point(q)^T F_xy
Q_torque = J_omega(q)^T T_z
```

本轮不包含真实轮胎力。`MechanicalLossModel` 为粘性、Coulomb 和效率/阻力预留，
默认 `ZeroMechanicalLoss`，即 `Q_loss=0`，不填入假工程参数。

## 6. 平面重力假设与 RHS

运动严格位于水平 XOY 平面，+Z 竖直向上且重力沿 -Z；没有竖向运动、俯仰或
侧倾，因此重力不做功，第一版明确取 `G(q)=0`，未人为构造平面内重力项。

```text
q_ddot = solve(M(q), Q_total - h(q,q_dot) - Q_loss)
dy/dt = [q_dot, q_ddot]
```

未来加入坡度/车身姿态时再扩展重力广义力接口。

## 7. 质量参数和 synthetic 边界

`RigidBodyMassProperties` 包含 body ID、mass、局部 COM、Izz、source、confidence、
notes 和显式惯性纳入标记，并能展开为 R01 `ParameterMeta`。工程入口缺少任一必需
构件或必填值时抛出 `MissingMechanicalParameterError`，不填默认质量。决定忽略
某构件惯性时必须显式设置 `include_in_inertia=false` 并写明 notes。

- 工程空模板：`configs/mechanics/mechanical_mass_properties_template.csv`
- 分级参数需求：`docs/mechanics/R02C_dynamic_parameter_request.md`
- 测试参数：`data/example/mechanical_mass_properties_SYNTHETIC_TEST_ONLY.csv`

测试文件全部为 `source=ASSUMED`，notes 为 `synthetic numerical verification only;
not customer engineering data`。正式构造默认拒绝该参数集，只有 tests/examples 可
显式设置 `allow_synthetic_test_only=True`。`uniform_slender_rod_estimate()` 也只返回
明确标记 ASSUMED 的估算，不会写入正式工程配置。

## 8. 数值验收指标

M 指标取 q=0 及五个坐标分别为 ±0.05 rad、其余为零的 11 个 isolated numerical
verification states；这不是机械限位或工程工作范围。其余恒等式检查点为
`q=[0.01,-0.015,0.012,-0.008,0.006] rad`、
`q_dot=[0.03,-0.02,0.025,-0.015,0.01] rad/s`。

| 指标 | 结果 |
|---|---:|
| M 最大对称性误差（无穷范数） | `0.00000000000000000e+00 kg*m^2` |
| M 最小特征值 | `1.53654236532115240e-01 kg*m^2` |
| 动能一致性绝对误差 | `5.42101086242752217e-20 J` |
| actuator power identity 绝对误差 | `8.88178419700125232e-16 W` |
| point-force power identity 绝对误差 | `1.38777878078144568e-17 W` |
| 最大功率恒等式误差 | `8.88178419700125232e-16 W` |
| synthetic demo 相对 free-motion energy drift | `5.66723307293333042e-10` |

自由运动示例在 `[0,0.15] s` 内无外力、无损失积分，只用于数值验证。输出图：
`outputs/R02C_synthetic_dynamics.png`，标题明确标记不是客户车辆预测。

## 9. pytest 完整结果

```text
& "$env:CONDA_PREFIX\python.exe" -m pytest -q
..................................                                       [100%]
34 passed in 18.18s
```

原 R01 + R02-B 的 24 项测试全部回归通过；新增 10 项覆盖环境文档、缺参失败、
synthetic guard、M 对称/正定、零速度偏置/零重力、动能恒等式、执行器功率、点力
功率、自由运动能量以及 J/M/h 有限差分收敛。

## 10. 已知问题

1. 当前没有 CUSTOMER 质量、COM 或 Izz，所有动态数值只具有 synthetic 验证意义。
2. body Jacobian 和 dM/dq 使用数值中心差分，精度/成本适合 5-DOF 核心验证，但后续可按性能需要替换解析导数。
3. 当前无真实摩擦、阻尼、效率、回差、柔性、机械限位、轮胎力或液压力动态。
4. 机构仍为水平平面模型，不覆盖车身俯仰、侧倾、坡度或构件竖向运动。
5. 连接杆按端点定义刚体位姿；实际非均匀形状的 COM/Izz 必须由客户数据覆盖，不能使用细杆估算作工程结论。

## 11. R02-C2 仍需用户提供的真实参数

A 类、工程动力学必须：43 个模板构件逐项 `mass_kg`、局部 COM X/Y、绕 COM 的
`izz_kg_m2` 及来源/置信度/备注；若明确忽略某构件惯性，还需批准依据。

B 类、第二阶段重要：关节/衬套/转向器摩擦、粘性阻尼、效率/阻力、回差、真实
机械限位及限位接触参数。

C 类、后续外载荷：六桥轴荷、轮胎转向力矩或可辨识轮胎模型、车速、路面与轮胎
条件，以及用于验证的 AMESim/试验通道定义和时序。

## 12. Git

- branch：`r02-mechanical-dynamics-core`
- merge 回 main：未执行
- commit hash：R02-C1 交付提交即本文件所在提交；提交后以 `git rev-parse HEAD` 获取并在最终聊天中报告。
