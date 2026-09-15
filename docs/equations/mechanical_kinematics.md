# R02-B 六轴转向机械运动学

## 坐标和广义坐标

输入硬点保持 CUSTOMER 原值（mm）；构造不可变参考几何时一次性乘 `1e-3` 转为 m。计算平面为 XOY，转轴均为 +Z，不使用 left/right。

```text
q = [q_front, q3, q4, q5, q6]
```

R02-B.1 正式冻结每个 1-DOF 组的广义坐标为该组主摆臂两侧相对 CUSTOMER q=0 参考构型的转角增量平均值：

```text
q_i = (theta_SWING_i_NEG_Y + theta_SWING_i_POS_Y) / 2
```

其中 `q_front` 使用一桥两侧主摆臂，`q3`～`q6` 使用对应车桥两侧主摆臂。它们仅是 **INTERNAL KINEMATIC GENERALIZED COORDINATES**，不是实际传感器角、液压缸位移、方向盘角、控制器命令或转向器输出角。后续真实执行器/传感器坐标必须通过显式映射连接到 q。

## 刚体硬点

对刚体 b，参考转轴为 `o_b`，q=0 全局硬点为 `r_P^0`，局部硬点只计算一次：

```text
rho_bP = r_P^0 - o_b
r_P(theta_b) = o_b + R(theta_b) rho_bP
```

所有参考长度均由 q=0 坐标一次性计算，此后不从当前状态重定义。

## 固定杆约束

每根刚性拉杆 k 连接硬点 A、B：

```text
c_k(theta) = ||r_B(theta)-r_A(theta)|| - L_k^0 = 0
```

一二桥组未知 8 个刚体角，约束为 7 条杆长约束加 1 条 q 坐标约束：一桥横拉杆、NEG_Y/POS_Y 两根纵拉杆、两桥共四根边拉杆。二桥没有也未创建独立横拉杆。

三至六桥每组未知 4 个角，约束为横拉杆、两根边拉杆共 3 条杆长约束，加 1 条 q 坐标约束。

使用 `scipy.optimize.least_squares`，上一时刻解作为下一时刻初值。残差超过 `1e-10 m` 明确抛出 `UnreachableGeometryError`；约束 Jacobian 条件数超过 `1e10` 标记为奇异。

## 约束灵敏度与执行器 Jacobian

令闭链约束为 `c(x,q)=0`，其中 x 是从属刚体角。由隐函数定理：

```text
dx/dq = -(dc/dx)^(-1) dc/dq
```

实现中坐标约束写作 `(theta_NEG_Y+theta_POS_Y)/2-q=0`，等价求解右端向量 `[0,...,0,1]`。

执行器端点差 `d=r_B-r_A`，长度及对所属摆臂角的解析导数为：

```text
L = ||d||
dL/dtheta = (d/L)^T (dR/dtheta) rho_B
J(q) = dL/dtheta * dtheta/dq
L_dot = J(q) q_dot
```

三至六桥每桥两只缸共享同一个 q_i。未来液压力映射接口为：

```text
Q_hyd_i = F_iA J_iA(q_i) + F_iB J_iB(q_i)
```

Ackermann 几何只存在于独立工具 `ideal_ackermann_angles`，不参与实际闭链求解。
