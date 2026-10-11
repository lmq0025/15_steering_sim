# Phase L1-R1 集中参数液压模型验收修订报告

## 验收结论

集中参数路线保留，旧 109-state/67-line-state 内核没有恢复。模型仍为 4 个主执行器通道、16 个动态状态、0 个动态管路状态。当前结论是 **CONDITIONAL**：方程和时变输入调度通过，但原 L1 通道绑定被 IR V3 证据推翻并已做最小修正；动态 Amesim 配对只完成 S0，S1/S2 无可用 Amesim 结果。

## 验证证据清理

旧 30G 的 10/10 不是独立动态验证：泵额定流量是参数转移，执行器初值是初始条件，18.6623 MPa 点又用于辨识 `R_eq`。31A 重新分类后，旧表独立验证数量为 0。本轮 S0 产生 8 个独立宏观序列，其中 1/8 达到 10% NRMSE；只有泵流量通过。其余偏差证明 L1 的阀等效和共享供油动态尚未完成宏观校准。

## 通道拓扑修正

IR V3 路径表明原假设 `pump01→dirvalve_1→actuator001` 等四条独立链不成立。正确主关系为：

- pump01/pump01_1 共用前供油组，经 dirvalve_6 服务 actuator002；
- pump01_2/pump01_3 共用后供油组；
- dirvalve_1/2、8/9、11/12 分别对应 actuator001、actuator001_1、actuator001_2 的冗余主阀路径。

运行时已改为两个共享代数供油节点，每个并联泵仍保留自己的压力控制支路。状态数没有变化。完整物理路径见 31B。

## 方程与输入调度

PU001、四通阀孔口律、双腔连续性、液压缸 TF、供油流量平衡和 0 Pa(g) 油箱边界均通过代码审计。没有 hard pressure clipping。`model.evaluate()` 虽不直接使用 `t`，但 RK4 每个 stage 都重新调用 `inputs(t)`；自动测试确认正弦命令没有被冻结。

## Amesim 配对

S0 原生基线成功，审计模型 SHA-256 前后相同。S1 阶跃和 S2 1 Hz 信号在临时模型修改后均被 Amesim 拒绝运行；临时模型关闭时均使用 `AMECloseCircuit(False)`。因此 S1/S2 图明确标注 `NOT COMPARABLE`，没有计算伪误差，也没有时间平移。

## 供油压力可辨识性

`R_eq=1.18e10 Pa·s/m³` 来自同一个 18.6623 MPa 基线点，是校准参数而非验证证据。它表示泵出口到单泵溢流支路的等效代数损失，不是阀前歧管压力，也不是管路动态。不同泵速/阀开度的迁移性仍未验证，供油压力结论为 **CONDITIONAL**。

## 时间步长与运行速度

测试 0.1/0.25/0.5/1/2/5 ms。0.5 ms 是同时满足 S1/S2 主要动态误差不超过 1% 的最快固定步长；1 ms 及以上出现非正腔体容积数值失败。真实动态性能为：1 s STEP 0.377 s，1 s SINE 0.374 s，100 s SINE 37.388 s（2.67× realtime）。上一版 33.8× 只适用于 neutral equilibrium 的 5 ms 步长，不能代表动态吞吐量。

## 线性化与二阶模型

neutral/small/medium 三个工作点先求平衡，动态点无穷范数残差小于 2e-6。增益改为由 `-C pinv(A)B+D` 计算，不再使用占位值 1。当前没有满足“显著主导模态 + 非线性局部响应验证”的二阶模型，因此二阶结论保持 CONDITIONAL/NOT_APPLICABLE，不作为工程传递函数交付。

## 门禁

- CHANNEL TOPOLOGY: PASS AFTER MINIMAL CORRECTION
- MAIN HYDRAULIC EQUATIONS: PASS
- TIME-VARYING INPUTS: PASS
- SUPPLY PRESSURE VALIDATION: CONDITIONAL
- LINEARIZATION: CONDITIONAL
- SECOND-ORDER REDUCTION: CONDITIONAL
- PYTEST: 212 passed
- READY FOR L2 MACRO CALIBRATION: NO（缺少 S1/S2 Amesim holdout）
- READY FOR MECHANICAL INTEGRATION: NO
