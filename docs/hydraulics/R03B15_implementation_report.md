# R03-B1.5 实施报告

## 结论

本轮结论为 **WAITING_FOR_AMESIM_RESULTS**，不是 FAIL。AMESim 自动化能力为
**PARTIAL**：可确认原生 simulator/batch 能力存在，但在既定安全约束下无法自动创建
并编译新的单组件派生模型。没有运行 AMESim 单组件试验，没有生成伪结果，也没有回填
R03-B1 的 `HYDVORF0.flow()` 或 `HJ020Cylinder.rhs()`。

## 环境与完整性

- Python：`E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe`
- 原模型：`E:\15_project\qh1_1.ame`
- 开始/结束 SHA256：`7613615723973D66A7122C74956C5161F720A64B243139FE9736CB270303B767`
- 大小：87,357,440 bytes
- mtime UTC：`2026-06-05T04:52:13.1639016Z`
- 原模型修改：NO
- `src/steering_sim/mechanics/` 修改：NO

## 冻结的试验设计

HYDVORF0 共 346 点：216 个 identification 点、130 个 validation 点。opening 使用当前
实际 0..100 定义；压差覆盖正、反、零、低压差、过渡、1 bar 特征点和高压差。

HJ020 共 186 个 run：

- B1：固定活塞/规定流量，识别 pointwise compliance 与 beta_eff；
- B2：零外部流量/规定运动，识别 equivalent swept flow；
- B3：流量与运动组合，仅作独立 validation。

时间设置为 0.02 s、输出间隔 0.0001 s、拟合窗 0.002–0.008 s、相对容差 1e-8。
exact AMESim solver GUI 名称必须在人工运行时记录。

## 分析策略

压力导数使用窗口最小二乘直线拟合，不使用单步差分。HYDVORF0 首先计算符号、零点、
单调性、正反对称、characteristic point 和 local log slope；候选关系必须在观测之后
选择。HJ020 使用 B1/B2 identification 构造 diagnostic candidate，再只对 validation
（尤其 B3）报告误差。脚本输出均标注 `DIAGNOSTIC_ONLY_NOT_APPROVED_FOR_R03B1`。

## 测试

- 旧回归：122 passed
- R03-B1.5 新增：11 passed
- 完整项目：133 passed

## 下一步输入

需要项目负责人按 `R03B15_AMESim_manual_execution_guide.md` 建立两个派生 `.ame`，
记录 checksum/solver，并把真实 AMESim CSV 放入 `results_raw/`。收到结果后运行分析器，
审查独立验证误差；只有验收通过后才能开启 R03-B1R。

