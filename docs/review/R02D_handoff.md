# R02-D 机械执行器位置到车轮转角 I/O 与标定接口交接

- 日期：2026-09-15
- branch：`r02-mechanical-io-calibration`
- R02-C1：已非 squash 合并至本地 `main`，代码完整保留
- 正式环境：`steering_sim`

## 1. 最终机械模块 I/O 定义

当前正式外部路线为：

```text
MechanicalActuatorInput
  -> actuator sensor conversion
  -> q=[q_front,q3,q4,q5,q6]
  -> R02-B frozen closed-chain kinematics
  -> MechanicalSteeringOutput (12 wheel angles + diagnostics)
```

`MechanicalActuatorInput` 是强类型记录，含 `front_position` 以及 Axle3～6
各 A/B 两个可选传感器位置；不使用裸数组猜索引。每个后桥至少需要 A/B 中一个。
位置显式标记为 `absolute_length_m` 或 `stroke_from_reference_m`。

`MechanicalSteeringOutput` 固定按 Axle1→6、每桥 POS_Y→NEG_Y 输出 12 个轮角，
并含 5 个内部 q、逐执行器/逐桥残差、闭链残差、valid、singular、
out_of_range、可达性、约束条件数、奇异接近度和分支重启诊断。

## 2. Axle2 无独立执行器输入

冻结拓扑中 Axle1 与 Axle2 构成一个 `AXLE_1_2` 联动闭链，唯一内部坐标为
`q_front`；Axle2 由纵拉杆和两桥闭链姿态确定，没有独立横拉杆或独立执行器。
因此高层输入结构有 front position，但故意没有 axle2 actuator 字段。

## 3. 三至六桥逆运动学与双缸处理

每桥仍只求一个 q_i，不把 A/B 缸当成两个 DOF。传感器值先经显式转换：

```text
calibrated = scale * (position - zero_offset)
absolute mode: L = calibrated
stroke mode:   L = L_reference + stroke_sign * calibrated
```

随后复用 R02-B 的 `L_iA(q_i)`、`L_iB(q_i)`，最小化：

```text
J(q_i) = w_A [L_iA(q_i)-L_iA_meas]^2
       + w_B [L_iB(q_i)-L_iB_meas]^2
```

实现先在配置的 numerical inverse search bound 上采样识别局部极小区间，再用
`scipy.optimize.minimize_scalar(method="bounded")` 做一维有界求解，并用已验证的
actuator Jacobian 做有界 Gauss-Newton 精修。若出现等价极小值，以上一时刻 q 最近
者优先；跨 q=0 时从 CUSTOMER 参考构型安全重启冻结闭链，避免数值支路停滞。

两只传感器可用时共同参与目标并返回 A/B residual 与 paired RMS；只有一只可用时
允许反解，另一缸长度作为模型预测写入 diagnostics。输入超出 numerical search
可达长度包络时 `out_of_range=true`、`valid=false`，该边界不是机械限位。

## 4. 前桥 baseline mapping

真实前桥执行器硬点仍未知，未伪造液压缸几何。可替换接口
`FrontActuatorMapping` 的第一版为：

```text
q_front = k_front * (position - position_zero)
position = q_front / k_front + position_zero
```

baseline 为 `k_front=1.0 rad/m`、`position_zero=0 m`，两者均标记
`ASSUMED_BASELINE`、confidence=0、`NOT CUSTOMER CALIBRATED`，仅保证软件往返和
数量级调试。以后可用客户数据标定，或在获得真实前桥几何后替换 mapping；
`MechanicalSteeringIOModel` 外部接口不变。

## 5. Baseline 参数、来源与可标定边界

配置：`configs/mechanics/mechanical_io_baseline.yaml`。每个非 CUSTOMER 数值均含
value、unit、source、confidence、reference、notes、calibratable、lower/upper
bound。8 个后桥缸的 reference length 在运行时由冻结 q=0 CUSTOMER 几何导出；
文件不复制客户硬点或其他车辆行程。

第一层可标定参数：8 缸 zero offset、scale、离散 stroke sign，front k/zero，
12 个 wheel/toe zero offset。连续参数可进入 `scipy.optimize.least_squares`；stroke
sign 只能显式选择 -1/+1 候选，避免连续优化产生无物理意义的中间符号。

所有 CUSTOMER hardpoints 默认冻结。`HardpointCorrection.enabled=false`；未来只有
独立批准二级标定并提供逐点制造/安装公差上下界后才可启用，当前参数集会拒绝启用。

公开资料边界见 `docs/references/multi_axle_steering_baseline.md`。Ackermann 只由
`SteeringPlausibilityEvaluator` 作为参考误差计算，绝不覆盖闭链轮角。

## 6. 合理性检查

当前 evaluator 可报告 wheel-angle continuity、逐轮 monotonicity、POS_Y/NEG_Y
同向关系、可选 Ackermann reference error、paired-cylinder RMS、reachable/
out-of-range 和 singularity proximity。这不是客户精度验证。

冻结几何在 q5 从 -0.04 到 +0.04 rad 的 isolated numerical scan 中，Axle5 两侧
轮角被 evaluator 报告为局部非单调；该事实保留为后续客户数据核查项，不伪装成
通过，也不解释为真实工作范围或机械限位。

## 7. 标定与训练/验证隔离

`MechanicalCalibrationProblem` 支持时间列、8 个后桥位置列、front position，以及
任意子集的 12 个实测轮角列；缺失观测不参与目标。目标为加权轮角残差并可加参数
正则项。`fit(calibration_set)` 与 `evaluate_validation(validation_set, ...)` 分离；
若验证集与拟合集内容相同，接口明确拒绝。

指标预留 MAE、RMSE、max absolute error 和 normalized RMSE。normalized RMSE 的
分母使用观测跨度与 `1e-3 rad` floor 的较大值，不会在接近零角时直接除以近零真值。
项目“≤10%”仍未定义，也未在本轮宣称。

## 8. Synthetic 数值结果

往返工况使用 11 个 q 点，q3 在 ±0.05 rad 内取值，其余坐标按固定比例取值；这是
synthetic numerical verification，不是车辆转向策略或工程范围。

| 指标 | 结果 |
|---|---:|
| q→L→q 最大绝对误差 | `3.11903280980629916e-15 rad` |
| 一致 synthetic 双缸最大 paired RMS | `1.25607396694702013e-15 m` |
| synthetic wheel-offset 标定恢复误差 | `4.60429958049068944e-12 rad` |

标定 synthetic truth 仅把 `WHEEL_3_POS_Y` zero offset 设为 `0.012 rad`；拟合与验证
使用不同 q 点。该结果只证明接口可恢复已知 synthetic 参数，不是客户标定结论。

## 9. Demo

`examples/run_mechanical_io_demo.py` 分别只扫描 `q_front`、q3、q4、q5、q6，生成：

- `outputs/R02D_actuator_to_wheel_demo.png`
- `outputs/R02D_actuator_to_wheel_demo.csv`

CSV 共 105 行，包含 position definition、front/8 缸输入、5 个内部 q、12 个轮角、
最大执行器/闭链 residual 和 valid。图与 CSV 均明确属于 SYNTHETIC/BASELINE ONLY。

## 10. Python executable 与 pytest

```text
E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe
```

```text
& "$env:CONDA_PREFIX\python.exe" -m pytest -q
...........................................                              [100%]
43 passed in 39.96s
```

## 11. 已知问题

1. 前桥 actuator geometry、真实 k_front 和 position datum 未提供。
2. 8 个后桥位置传感器的 absolute/stroke 定义、正方向、零偏、比例和不确定度未确认。
3. 12 个实测轮角的零位、toe 定义、正方向、采样同步和单位未确认。
4. numerical inverse search bound 只是 R02-B 已验证区间，不是客户机械限位。
5. paired residual 尚无客户传感器噪声/一致性验收阈值。
6. Ackermann 参考需要客户冻结的转弯中心/轴距定义；公开案例 ±0.5 deg 不是本项目阈值。
7. CUSTOMER hardpoint correction 未启用，且本轮未继续机械动力学参数工作。

## 12. 后续甲方真实数据最少字段

- `time` 与数据集标识（`calibration_set` 或 `validation_set`）；
- `front_position`；
- Axle3～6 每桥至少一个 A/B position，推荐 A/B 均提供；
- 至少一个同步实测 wheel-angle 列，完整验证推荐 12 列全部提供；
- 配套元数据：每个位置是 absolute length 还是 reference stroke、单位、stroke sign、
  reference/zero datum、scale、传感器精度，以及每个轮角的 POS_Y/NEG_Y、单位、正方向和 toe/zero 定义。

标准列名为 `axle3_A_position`…`axle6_B_position` 以及
`axle1_POS_Y_angle`…`axle6_NEG_Y_angle`。

## 13. Git

- branch：`r02-mechanical-io-calibration`
- merge 回 main：未执行
- commit hash：R02-D 交付提交即本文件所在提交；提交后以 `git rev-parse HEAD` 获取并在最终聊天中报告。
