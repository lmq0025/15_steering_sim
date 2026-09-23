# R03-B1 验证计划

本轮验证分三层：

1. 已可执行：SI 单位换算、FX00 冻结表达式、VALVEDYNAMICS0 静态限幅、SC_1 四路拓扑、HJ020 面积/容积/压力力与配置溯源。
2. 已建立但 fail-closed：HYDVORF0 流量接口、HJ020 两压力状态 RHS、两状态 `SingleActuatorPrescribedMotionRig`。
3. 后续解锁后：以 A2.5 冻结的 baseline channels 对齐 command、spool、P/T/A/B 压力与流量、p1/p2、位移、速度、力；先做组件特性，再做相同边界时间历程。

进入动态对照前必须取得 `eqarea/orif3f_` 与 `pcdyn2_/q0top_` 的官方算法说明，或形成由 AMESim 2021.1 单组件试验导出的、可版本冻结的替代特性。没有同工况 AMESim 结果，本轮不作“误差 ≤10%”结论。

