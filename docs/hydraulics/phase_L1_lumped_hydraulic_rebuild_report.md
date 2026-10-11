# Phase L1 集中参数液压模型重构报告

## 结论

旧 109-state detailed model 已终止作为主运行内核，但代码、IR 和审计证据均完整保留。新模型在独立包 `hydraulics_lumped` 中实现了 4 个真实独立主液压通道，每通道 `[p_A,p_B,x,v]` 四个状态，共 **16 states**；动态管路状态为 **0**。

模型由 PU001 流量源、SC_1 集中 MR、双腔 C、液压缸 TF、局部移动质量 I、泄漏/阻尼 R、RV010 物理溢流 R 和 TK000 0 Pa(g) Se 组成。供油压力由流量平衡求解，没有 hard clipping。管路/滤芯只保留代数等效阻力。

## 参数可追溯性

参数统计：AMESIM_EXACT=45，PHYSICS_DERIVED=14，AMESIM_IDENTIFIED=1，MISSING=2。唯一进入健康基线的识别量是泵—溢流主路径等效稳态阻力；它由 C1 的 18.6623 MPa、RV010 160 bar 和已验证泵流量识别。MISSING 项仅作为未来退化接口，当前不参与方程。

## 通道与状态

四个主通道分别对应四台 PU001 与 actuator001、actuator001_1、actuator001_2、actuator002。三个 spring-return 缸保留在参数资产中，但不是四个独立主受控输出，因此 L1 不错误合并也不额外制造状态。SC_1 正常 `spooldyn=1`，采用静态饱和 opening；`tau_v` 仅预留接口。

## 验证

正常闭阀基线供油压力：Amesim 18.6623 MPa；Lumped 18.6577 MPa。不存在无物理原因的 >100 MPa 压力。STEP 和 0.1–5 Hz SINE 数值检查均有限且通过。C1 原生输入与本报告诊断 STEP 不同，因此第一轮宏观评分只对输入不变量和基线量做正式数值门禁：10/10 在 10% 内；动态宏观曲线标记为下一阶段少量参数校准对象，未对内部 pipe/MR 微观状态评分。

## 线性化与二阶模型

neutral、small-load、medium-load 三点均生成数值 Jacobian A/B。二阶映射只在确有共轭主导极点时生成，绝不人工指定 `wn` 或 `zeta`；当前状态为 **PASS**。完整映射见 30D/30E。

## 性能

固定步长 RK4 在 dt=1/2/5 ms 下均建档。dt=5 ms 时：1 s 物理过程 0.030069 s；100 s 物理过程 2.959062 s。性能基准采用 neutral equilibrium，STEP/SINE 另用更保守 dt 验证。

## 决策

MODEL BUILDS=PASS；PIPE DYNAMIC STATES=0；NaN/Inf=0；UNEXPLAINED HIGH PRESSURE=0；MACRO AMESIM COMPARISON=CONDITIONAL；PYTEST=203 passed。可以进入 L2 宏观少参数校准，但本阶段未进入机械、PID、退化或雨流。
