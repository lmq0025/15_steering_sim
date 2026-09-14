# Equation registry

R02/R03 开始，每条方程必须登记：符号、SI 单位、适用边界、参数来源、假设、参考文献/图纸、解析极限和验证数据。R01 只冻结函数接口，不批准任何工程方程或默认参数。

连续机械候选形式：

```text
M(q) q_ddot + h(q, q_dot) + g(q) + constraint_forces = external_load + actuator_effort
```

液压网络候选形式：

```text
E(x, p) p_dot = continuity(p, Q, actuator_velocity, leakage)
```

实际 ODE/DAE 形式须由转向构型和液压原理图决定。

