# R03-B1.5 缺失本构关系辨识记录

当前状态：**WAITING_FOR_AMESIM_EXPERIMENT_RESULTS**。本文不含伪造观测值，也没有把
候选式回填到 R03-B1。

## HYDVORF0 method=1

缺失的是私有 utility `eqarea/orif3f_` 的算法体。单组件模型用两个 PS00 压力边界和
一个规定 opening 隔离 HYDVORF0，冻结 216 个 identification 点与 130 个 validation
点，覆盖零、小开度、特征点、低/过渡/高压差和正反流。

收到结果后先报告 sign(q) vs sign(dp)、零压差/零开度、单调性、正反对称、1 L/min @
1 bar 特征点，以及局部斜率 `d ln|Q| / d ln|dp|`。只有观察这些行为后，才比较具有
物理含义的层流/湍流分段或平滑过渡候选。分析器当前产生的 signed-power fit 仅用于
观察 local exponent 与残差，明确标为 diagnostic candidate，不是冻结本构。

必须在独立 validation 集报告 MAE、RMSE、带低流量 floor 的最大相对误差、低流量
absolute error、反向误差和 characteristic-point error。主工作区若无法稳定达到约 2%
且无系统偏差，则不足以恢复 R03-B1 flow。

## HJ020 + FP04 pressure dynamics

缺失的是私有 `pcdyn2_/q0top_`。B1 用固定活塞与规定流量识别 pointwise hydraulic
compliance/beta_eff；B2 用零外部流量与规定运动识别 equivalent swept flow 的符号、
有效面积和压力/位置依赖；B3 只用于组合工况独立验证。

分析器以 0.002–0.008 s 的局部线性回归估计 dp/dt，不用单步差分。它利用 B1 最近
邻域 compliance 和 B2 median swept-flow ratio 形成 diagnostic candidate，再对 B3
计算预测残差；这不是 Siemens 原始算法，也不是获批 Python RHS。

最终允许采用的名称只能是“针对当前 AMESim 子模型及当前参数状态辨识得到的等效
本构关系”。适用范围必须限制在矩阵覆盖的 5–200 bar、0.1–0.9 stroke、规定流量与
速度范围；端止点、非零泄漏、其他 FP04 fluid index、其他 HJ 系列均不在本轮范围。

在真实结果、派生模型 checksum、solver 设置和独立验证误差齐备前，两项均不足以
回填 R03-B1，仍需要 AMESim 单组件运行结果；不要求取得 Siemens private utility 源码。

