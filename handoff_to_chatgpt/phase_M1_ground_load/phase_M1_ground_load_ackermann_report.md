# PHASE M1 六桥阿克曼机械转向与地面载荷报告

## 1 结论

PHASE M1 已形成一套可独立运行、与液压和控制代码隔离的六桥机械计算模型。默认批量计算覆盖 0 至 80 km/h、-30 至 30 deg、一共三档摩擦系数和六桥独立轴荷字段，共生成 3111 个工况和 37332 条车轮明细。模型输出 12 轮理想阿克曼角、刚性闭链理论转角、受载实际转角、侧偏角、侧向力、道路阻力矩、机构残差和适用性状态。

本版机械闭链与三桥锁止均通过测试。地面反馈和七缸接口为条件通过：轮胎侧偏刚度、有效拖距、原地转向等效半径、机构刚度和前桥缸行程比例尚无甲方实测标定值。结果可用于结构审查、参数敏感性和后续接口设计，不能宣称达到甲方实车精度指标，也不能直接用于安全控制。

默认扫描中有 2574 个工况至少带一个不可行或超适用范围标志。其中 2550 个工况因后桥机构无法在当前连续数值包络内逼近理想目标而带 `GEOMETRY_INFEASIBLE`，1008 个工况带 `ADHESION_INFEASIBLE`，1350 个工况带 `OUTSIDE_LINEAR_TIRE_RANGE`。标志可以叠加。其余 537 个工况标为 `APPLICABLE_WITH_ASSUMED_PARAMETERS`。

## 2 资料审计与版本边界

本轮读取并核对了 `source_materials` 下的两份 Word 和三张结构图。甲方主说明明确写明表格是“每个连接点的点位，也就是坐标位置”，且所有连接均为绕 z 轴旋转副。坐标单位为 mm，原点位于一桥两侧轮胎中心连线中点，x 向前、y 向左、z 向上。实现没有把任何坐标数值解释为角度范围。

R02B 的 `+-0.08 rad` 在原交接中已明确标为数值验证区间，而不是铰点坐标、机械限位或允许转角范围。未发现旧代码把甲方铰点坐标直接当作旋转副角度范围的证据。需要纠正的是旧 R02B/R02D/R02E 拓扑仍将三桥设置为可转向自由度，并包含三桥双缸；这与最新“无三桥转向”和七缸要求冲突。M1 未修改旧成果，而是新增 `mechanics_ackermann_v2`，复用其可靠的固定杆长闭链求解器并重建上层拓扑。

最新三桥坐标表确认第 20 点 `(-7290,-996) mm` 是三桥一侧车轮与车架的旋转中心，另一侧按 y 对称建立。第 14 至 19 点的油缸、摆臂、横拉杆和边拉杆坐标完整保留，但标记为 `CUSTOMER_HARDWARE_RECORD_PENDING_CONFIRMATION_NOT_ACTIVE`。三桥不进入运动自由度，也不进入七缸接口。

甲方确认的五、六桥长连杆坐标没有修改。五桥边拉杆端点为第 34 点 `(-11630,-500) mm` 和第 35 点 `(-14068,-1010) mm`，参考长度约 2490.772 mm；六桥对应第 42 点 `(-13330,-500) mm` 和第 43 点 `(-16668,-1010) mm`，参考长度约 3376.736 mm。

## 3 真实坐标与模型拓扑

M1 共有 12 个车轮，其中 10 个可转向、2 个固定。独立运动自由度只有四个：

- `q_front`：一、二桥共同闭链。二桥没有独立指令，完全由两侧纵拉杆随一桥运动。
- `q4`、`q5`、`q6`：四、五、六桥各一个闭链自由度。每桥的两个物理缸是同一个自由度的长度输出，不是两个独立自由度。
- 三桥：左右轮角恒为 0 deg，无 `q3`。

刚性机构继续使用每根拉杆的约束

```text
||r_B(theta) - r_A(theta)|| - L_reference = 0
```

固定车架铰点不移动，杆长由零位甲方坐标一次性确定。闭链采用连续分支求解；M1 先对每个自由度从零位向正负方向逐步建立密集运动映射，再对每个理论和受载工况执行完整闭链求解。默认批量计算的最大杆长残差为 `1.46e-12 m`。

配置中的 `q_front/q4/q5/q6` 包络只表示本轮已验证的连续数值包络，来源标记为 `NUMERICALLY_VERIFIED_CONTINUATION_ENVELOPE_NOT_CUSTOMER_MECHANICAL_LIMIT`，不得解释为甲方机械限位。

## 4 理想阿克曼层

三桥作为低速固定参考桥，公共瞬时转向中心的纵向坐标固定为三桥轮心轴线：

```text
x_ICR = -7.290 m
```

当一桥外侧轮目标角不为零时，由指定外侧轮直接反解 ICR 横向坐标：

```text
y_ICR = y_outer + (x_outer - x_ICR) / tan(delta_ref)
```

左转为正，左转外侧轮为一桥右轮；右转为负，右转外侧轮为一桥左轮。随后用每个真实轮心位置计算：

```text
delta_i = axis_equivalent(atan2(x_i - x_ICR, y_ICR - y_i))
```

`axis_equivalent` 将无方向的滚动轴等价角映射到 `[-pi/2, pi/2]`。当 `delta_ref=0` 时，所有理想角、理论角和受载角直接置零，不发生除零。三桥轮心的 x 坐标等于 `x_ICR`，因此其理想角也严格为零。

该形式与 SAE 论文所述“所有转向轮围绕同一转向中心”的多轴 Ackermann 原则一致：[Research on Steering Control of Multi-Axle Steering Heavy Commercial Vehicle Based on Reducing Tire Wear](https://saemobilus.sae.org/articles/research-steering-control-multi-axle-steering-heavy-commercial-vehicle-based-reducing-tire-wear-10-04-01-0005)。

## 5 理论机械角

`theoretical_angle_deg` 定义为满足真实固定杆长闭链、尚未施加地面载荷的轮角。`ideal_ackermann_angle_deg` 只用于理想几何校核，两者差值为：

```text
ackermann_geometry_error_deg
  = theoretical_angle_deg - ideal_ackermann_angle_deg
```

一桥由外侧轮目标角反求 `q_front`，同一个 `q_front` 同时决定一桥内侧轮和二桥左右轮。四至六桥分别在自身单自由度真实闭链上最小化左右轮对理想角的均方误差。求解不会移动固定铰点，也不会修改任何杆长。

当最优解到达连续数值包络边界且残差超过 0.25 deg RMS，标记 `GEOMETRY_INFEASIBLE`。该 0.25 deg 只是数值显示阈值，不是甲方验收精度。即使工况不可行，CSV 仍保留理想角、边界处真实机构理论角、几何误差和原因，不会缩小目标角伪造成可行。

## 6 侧向力、轮胎和附着

车速和曲率产生的需求量为：

```text
v = speed_kmh / 3.6
kappa = sign(delta_ref) / abs(y_ICR)
a_y = v^2 * kappa
F_y_total_demand = sum(m_axle) * a_y
Fz_axle = m_axle * 9.81
Fz_wheel = Fz_axle / 2
```

六桥侧向力使用加权最小范数分配，同时强制总侧向力平衡和关于质量中心的稳态横摆力矩平衡：

```text
A = [[1,1,1,1,1,1], [x_1-x_cg,...,x_6-x_cg]]
F_axle = W A^T (A W A^T)^+ [F_y_total_demand, 0]^T
W = diag(m_axle)
```

在当前静态轴荷和质量中心定义下，该解等价于按轴荷分配，但保留了两条显式平衡约束。多轴车辆总侧向力、横摆力矩和线性侧偏形式参考：[Yaw Rate Synchronisation Steering Control of Multi-axle Heavy Vehicle](https://link.springer.com/chapter/10.1007/978-981-96-5527-4_112)。

每轮使用线性侧偏刚度和附着饱和：

```text
Fy = -C_alpha * alpha
alpha_demand = -Fy_demand / C_alpha
Fy_available = clip(Fy_demand, -mu*Fz, +mu*Fz)
```

该线性加饱和形式参考 MathWorks 的 [Blockset Designer Tire Model Example](https://www.mathworks.com/help/simulink/slref/blockset-designer-tire-model-example.html)。`tire_slip_angle_deg` 和机械 `wheel_steering_angle_deg` 分列输出，模型从不把侧偏角直接减到机械轮角上。

## 7 道路阻力矩与受载角

行驶中的回正力矩量级为 `abs(Fy_available) * t_effective`。零速和极低速使用 `mu * Fz * r_effective` 的原地转向量级。为避免在所有速度下把两项作为常量相加，使用速度权重：

```text
w_pivot = exp(-(speed_kmh / v_transition)^2)
M_road = w_pivot * mu*Fz*r_effective*engagement
       + (1-w_pivot) * abs(Fy_available)*t_effective
engagement = tanh(abs(delta_theoretical) / delta_engagement)
```

低速阻力的适用工况和随速度显著下降的趋势参考：[Study on Low-Speed Steering Resistance Torque of Vehicles Considering Friction between Tire and Pavement](https://www.mdpi.com/2076-3417/9/5/1015)。上述指数混合、等效半径和角度接合函数是本项目的工程简化，并非该论文原方程或甲方验证方程。

每组车轮先通过真实机构雅可比汇总为一个广义道路力矩：

```text
Q_road,j = sum_i(M_road,i * d(delta_i)/dq_j)
delta_q_j = -Q_road,j / K_steer,j
q_loaded,j = q_theoretical,j + delta_q_j
```

再以 `q_loaded` 重新执行完整固定杆长闭链求解，得到 `actual_loaded_angle_deg`。因此一二桥四轮只接受同一个 `q_front` 修正，四至六桥每桥左右轮只接受各自共同自由度修正。不存在逐轮任意角度修正。用载荷/力矩与转角柔度建立可配置关系的思想参考 MathWorks [Independent Suspension K and C](https://www.mathworks.com/help/vdynblks/ref/independentsuspensionkandc.html)，但本版刚度数值不是该模块默认值。

三桥没有转向自由度，其道路侧向力仍计入整车平衡，但不会改变三桥轮角。

## 8 工程假设和敏感性

以下参数均标记为 `ASSUMED_ENGINEERING_PARAMETER`，不是甲方实测特种车辆参数：

| 参数 | 默认值 | 说明 |
|---|---:|---|
| 单轮等效侧偏刚度 | 300000 N/rad | 线性小侧偏工程假设 |
| 小侧偏适用阈值 | 5 deg | 超过时标记，不强制缩角 |
| 行驶有效拖距 | 0.06 m | 将侧向力转换为回正力矩 |
| 原地转向等效半径 | 0.035 m | 接地、主销偏置和轮胎几何的合并量 |
| 低速过渡速度 | 5 km/h | 工程混合函数尺度 |
| 原地转向接合角 | 1 deg | 避免直行零角产生虚假静摩擦矩 |
| 中柔度前组刚度 | 200000 Nm/rad | 一二桥共同自由度 |
| 中柔度四至六桥刚度 | 150000 Nm/rad | 每桥共同自由度 |

低柔度、中柔度、高柔度分别使用 2 倍、1 倍、0.5 倍的中柔度刚度。`flexibility_sensitivity.csv` 给出 +10 deg、20 km/h、mu=0.75 下三档对照。高柔度应产生更大的载荷诱导角误差，专项测试已验证这一顺序。

## 9 不可行和适用性判定

- `GEOMETRY_INFEASIBLE`：真实机构在当前连续数值包络内不能充分逼近理想目标，或一桥外侧轮目标没有达到。
- `ADHESION_INFEASIBLE`：`abs(a_y)/(mu*9.81) > 1`。轮胎可提供力已经裁剪至 `mu*Fz`，需求力和可提供力分别保存。
- `OUTSIDE_LINEAR_TIRE_RANGE`：任一轮 `abs(alpha_demand) > 5 deg`。
- `LOADED_GEOMETRY_INFEASIBLE`：柔度修正后的自由度超出已验证连续包络或闭链失败。此时不输出被裁剪后冒充真实值的轮角。
- `APPLICABLE_WITH_ASSUMED_PARAMETERS`：未触发上述标志，但仍受未标定工程参数限制。

不可行工况的理想角、理论机械角和载荷需求仍保存；其中受载结果仅是边界/假设下的演示数据，不是已验证实车预测。

## 10 七缸机械接口

七个接口为：`front_group_1`、`axle4_A/B`、`axle5_A/B`、`axle6_A/B`。四至六桥缸长由甲方车架端和摆臂端硬点直接计算，CSV 同时给出绝对长度和相对零位行程。

甲方资料没有给出前桥主缸的两个安装硬点，因此 `front_group_1` 当前只提供可替换接口，采用 250 mm/rad 的 `q_front` 到行程比例，占位来源明确标为 `ASSUMED_ENGINEERING_PARAMETER_INTERFACE_PLACEHOLDER`，绝对缸长为空。七缸映射因此为 `CONDITIONAL`，尚不具备与液压 Fast 模型连接的足够条件。

默认 -30 至 30 deg 扫描的行程范围为：前组占位接口 -137.5 至 +137.5 mm；四桥 A/B 约 -51.62 至 +44.50 mm；五桥 A/B 约 -34.98 至 +33.65 mm；六桥 A/B 约 -26.33 至 +25.69 mm。这些是当前数值包络输出，不是已确认机械限位。

## 11 测试与输出

M1 专项测试共 22 项，覆盖直行、三桥锁止、左右镜像、一桥外侧轮定义、二桥机械随动、固定硬点、杆长不变、零载回归、原地转向、速度平方关系、mu 和轴荷响应、共同自由度受载修正、附着裁剪、侧偏角分离、12 轮输出、七缸接口、三档刚度敏感性以及 CSV/XLSX 工况输入。

主要输出：

- `all_cases.csv`：3111 行工况汇总，包含每工况 12 轮理想角、理论角和受载角。
- `wheel_angles.csv`：37332 行长表，包含 12 轮角度、侧偏角、需求/可提供侧向力、法向载荷和道路力矩。
- `cylinder_displacements.csv`：61 个目标角乘 7 个接口，共 427 行。
- `model_parameters.csv`：坐标、公开理论参数边界和所有工程假设的来源标签。
- `flexibility_sensitivity.csv`：低、中、高柔度对照。
- 五张要求图：六桥拓扑、左右转示例、理论与受载角对比、速度角度对比。

## 12 当前未标定参数与后续条件

仍需甲方提供或确认：前桥液压缸两端硬点、真实前桥行程与 `q_front` 映射、四个机构自由度等效刚度和阻尼、轮胎规格/胎压/单轮侧偏刚度、有效拖距、主销偏置和接地等效半径、真实机械限位、轮角零位、各缸传感器零点/比例/正方向，以及同步实测轮角、缸位移、轴荷、车速和路面条件。

在这些参数完成标定前，`READY FOR HYDRAULIC-MECHANICAL MAPPING = NO`。本轮没有修改或接入 `hydraulics_lumped`、PID、电液联合模型、退化或寿命预测模块。
