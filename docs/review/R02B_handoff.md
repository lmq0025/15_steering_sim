# R02-B 六轴转向机械运动学交接

- 日期：2026-09-15
- 分支：`r02-mechanical-kinematics`
- 主输入：本地冻结 `mechanical_model_input_spec_v1.0.yaml`
- 主输入 SHA-256：`693103a3c4914dbb94491008869543d669631a955400f5baaa55772dbd664c95`
- JSON 交叉检查：逐字节及解析对象均一致，SHA-256 相同
- 单位：输入 mm；构造参考几何时统一转为 m

## 实际实现的刚体和约束模型

实现了项目所需的最小类型：`RigidBody2D`、`SteeringWheelBody`、`RevoluteJoint2D`、`RigidLink2D`、`ClosedChainConstraint`、`HydraulicActuatorGeometry` 和不可变 `ReferenceGeometry`。

程序从冻结硬点自动识别 12 个 SWING、12 个 WHEEL、24 个绕 +Z 的 FRAME 旋转副、19 根固定拉杆和三至六桥 8 只镜像执行器。q=0 时以 FRAME 转轴为刚体原点，一次性计算局部硬点和参考杆长；运动中只变换刚体位姿，绝不重定义杆长或修正 CUSTOMER 坐标。

闭链采用 `scipy.optimize.least_squares` 求解，并保存每组上一解作为下一次初值。杆长残差超过 `1e-10 m` 抛出 `UnreachableGeometryError`；小步条件下从属角突跳超过 0.5 rad 抛出 `BranchDiscontinuityError`；约束 Jacobian 条件数超过 `1e10` 返回 singular 状态。

## 5 个广义自由度

```text
q = [q_front, q3, q4, q5, q6]
```

- `q_front`：AXLE_1_2 联动组唯一自由度。
- `q3`～`q6`：AXLE_3～AXLE_6 各自唯一自由度，桥间机械独立。
- 两只液压缸不是自由度，缸长均为相应 q 的输出函数。

冻结文件没有定义 q 对应哪一个实际测量角。为保持 NEG_Y/POS_Y 无偏置及镜像等变性，本轮冻结软件接口为：

```text
q_i = (theta_SWING_i_NEG_Y + theta_SWING_i_POS_Y) / 2
```

`q_front` 使用一桥两主摆臂平均角。此约定需甲方在下一接口评审中确认；若甲方指定转向器输入角/位移，需增加显式输入映射，但闭链拓扑不变。

## 一二桥约束方程

AXLE_1_2 共 8 个刚体角未知，由 8 个方程唯一确定：

1. 一桥横拉杆 12 固定长度；
2. NEG_Y 纵拉杆 12 固定长度；
3. POS_Y 镜像纵拉杆 12 固定长度；
4. 一桥 NEG_Y/POS_Y 两根边拉杆固定长度；
5. 二桥 NEG_Y/POS_Y 两根边拉杆固定长度；
6. 一桥两主摆臂平均角等于 `q_front`。

每根杆统一使用 `||r_B-r_A||-L_ref=0`。二桥未创建独立横拉杆。

## 三至六桥约束方程

每桥 4 个刚体角未知，由横拉杆、NEG_Y 边拉杆、POS_Y 边拉杆的 3 个固定长度约束，加该桥两摆臂平均角等于 `q_i` 的 1 个坐标约束确定。两只镜像执行器只测量/施力，不增加机械自由度。

## 液压缸长度、Jacobian 与速度

```text
d = r_B - r_A
L = ||d||
dL/dtheta = (d/L)^T (dR/dtheta) rho_B
dx/dq = -(dc/dx)^(-1) dc/dq
J = dL/dtheta * dtheta/dq
L_dot = J(q) q_dot
Q_hyd_i = F_iA J_iA + F_iB J_iB
```

公开接口：`actuator_length(q)`、`actuator_jacobian(q)`、`actuator_velocity(q,q_dot)`、`generalized_actuator_force(q, actuator_forces)`。Jacobian 为 8×5，前三至六桥各有两行只作用于其对应 q 列。

## 数值验收结果

扫描定义：从 q=0 分别沿正、负装配分支推进，各坐标同步扫描至 ±0.08 rad；每个方向 33 点。所有值为 SI 单位。

| 指标 | 结果 |
|---|---:|
| q=0 最大坐标重构误差 | `0.00000000000000000e+00 m` |
| 扫描最大固定杆长漂移 | `1.93178806284777238e-13 m` |
| 最大闭链杆长残差 | `1.93178806284777238e-13 m` |
| 8×5 Jacobian 中心差分最大误差 | `5.62107194124195075e-10 m/rad` |

Jacobian 差分步长为 `1e-6 rad`，检查点为 `[0.01,-0.02,0.015,-0.01,0.02] rad`。

## pytest 完整结果

```text
python -m pytest -q
........................                                                 [100%]
24 passed in 3.21s
```

本机裸 `python` 仍指向 AMESim Python 3.6；测试会话将 `E:\ProgramData\anaconda3` 放到 PATH 首位后执行上述原命令。

新增测试覆盖：YAML/JSON 一致性、零位重构、刚性杆不变、镜像等变、一二桥自由度、各后桥自由度、执行器长度连续性、速度/Jacobian 差分、闭链残差、小步分支连续、不可达异常及双缸 Jacobian 稀疏结构。R01 的 12 项测试同时回归通过。

## 可视化

独立调试脚本：`examples/plot_mechanical_kinematics.py`。

生成图片：`outputs/R02B_kinematics_check.png`，含 q=0 和五坐标均为 0.05 rad 两个构型，标出 Axle 1～6、NEG_Y/POS_Y、摆臂、横/纵/边拉杆、12 个车轮及三至六桥 8 只缸。图片为 2880×1260 RGBA PNG，不进入核心模型或 Git 提交。

## 已知问题

1. 甲方尚未定义 `q_front/q3...q6` 的实际传感器或执行器坐标；当前采用两侧主摆臂平均角，需确认。
2. 冻结输入没有给出允许运动范围；±0.08 rad 只是本轮连续数值扫描域，不是工程限位。0.20 rad 同步输入至少使 AXLE_5 不可达，程序会明确报错，但不能据此认定真实机械限位。
3. 车轮角输出是相对 CUSTOMER q=0 刚体姿态增量；尚无轮胎零位前束/绝对轮平面方向定义。
4. 前桥转向器或液压执行器几何被输入规范明确延后，本轮只把 `q_front` 当外部给定机械坐标。
5. 奇异判据为数值条件数阈值，后续应结合实际行程和机构传动比设定工程警戒阈值。
6. CUSTOMER 坐标、冻结说明和派生图片均被 `.gitignore` 排除；依赖真实输入的测试在无本地冻结文件的环境会 skip。
7. 本轮无质量、惯量、动力学、摩擦、柔度、轮胎载荷、液压或控制模型。

## 下一轮机械动力学所需参数

- 每个摆臂、车轮/转向节、拉杆及转向器运动件的质量、质心坐标和绕 +Z 转动惯量；
- 车架连接与运动件的真实自由度、是否可把拉杆质量集中或忽略；
- q 与方向盘、电机、转向器输出/齿条位移、前桥执行器之间的传动映射；
- 各旋转副/球铰/衬套/转向器的摩擦、阻尼、回差和效率；
- 拉杆、摆臂、车架和液压缸安装结构的等效刚度/阻尼及是否按刚体处理；
- 机械限位位置、接触刚度/阻尼和允许载荷；
- 六桥轴荷、主销位置和几何参数、轮胎规格、胎压、车速和路面工况；
- 各车轮回正力矩/轮胎侧向力模型或可辨识台架/整车载荷数据；
- 重力方向、车辆姿态范围，以及坡道/侧坡是否进入二维动力学；
- 机械力、位移、角度、速度传感器定义及独立 AMESim/试验验证时序。

## Git

- branch：`r02-mechanical-kinematics`
- merge：未合并 `main`
- commit hash：R02-B 交付提交即本文件所在提交。Git hash 由包括本文件在内的完整内容计算，无法在同一提交内自嵌最终 hash；提交后以 `git rev-parse HEAD` 获取，并在最终聊天交付中报告。
