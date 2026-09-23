# R03-B1 实施报告

## 1. 任务边界

本轮仅处理代表链 `dirvalve_6 / SC_1 -> actuator001 / HJ020`，机械运动、供油压力和回油压力均为 prescribed boundary。未修改机械模型，未连接六轴机构，未实现泵站、蓄能器、压力阀网络或控制器，也不作动态精度结论。

结论为 **BLOCKED**：静态阀映射和缸几何已代码化并通过测试，但 AMESim 2021.1 安装只公开 `eqarea/orif3f_`、`pcdyn2_/q0top_` 的声明，没有公开算法体。按任务约束，没有用通用孔口公式或常体积模量公式代替，所以最小压力动态链不能可信积分。

## 2. 环境与起始状态

- `sys.executable`: `E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe`
- branch: `r02-mechanical-demo-entry`
- start HEAD: `7d4ec43d3e727627b33668ff02287860d6dca4bb`
- 工作区开始时已有 R03-A1/A2/A2.5 未跟踪审计成果；未 reset、clean、checkout、merge 或 commit。

## 3. 原模型完整性

- 路径：`E:\15_project\qh1_1.ame`
- 开始/结束 SHA256：`7613615723973D66A7122C74956C5161F720A64B243139FE9736CB270303B767`
- size：87,357,440 bytes
- mtime UTC：`2026-06-05T04:52:13.1639016Z`
- 是否修改：NO

## 4. 新增架构

- `units.py`：AMESim 常用单位到 SI 的集中转换。
- `expressions.py`：递归 AST 白名单解释器，不调用 Python `eval`。
- `fluid.py`：FP04 冻结数据容器，不伪造私有物性算法。
- `valve_dynamics.py`：VALVEDYNAMICS0 mode 1 静态限幅。
- `orifice.py`：HYDVORF0 method 1 配置及 traceability guard。
- `valve.py`：配置驱动的四路径 SC_1 拓扑。
- `cylinder.py`：HJ020 几何、容积、压力力、泄漏和压力 RHS guard。
- `single_actuator_rig.py`：两压力状态的最小装配接口。
- `r03b1_factory.py`：从生成配置构造组件。

## 5. Equation traceability

### VALVEDYNAMICS0

active mode 为 `spool dynamics=1 = no (static)`，dynamic order=0，无连续阀芯状态。上下限为 -1/+1，裁剪会返回诊断；保存的 0.05 s、20 Hz、1.8 在当前分支不参与。证据为官方 `VALVEDYNAMICS0.spe/.c` 和 A2.5 定义文件。

### FX00

阀芯映射和 P-B/P-A/T-A/T-B 四条开口表达式从生成配置读取。安全解释器只允许数字、已声明变量、算术、单一比较、`sqrt`、`fabs` 和 `pi`，拒绝属性访问、导入、builtins 及任意函数。

### HYDVORF0

active branch 为 method=1。官方 `HYDVORF0.c` 清楚显示限幅、归一化、面积缩放、`eqarea` 初始化和 `orif3f_` 求流；`hydr_public.h` 只有声明。由于 `orifices.c`/`orifices_common.c` 算法体不在安装证据中，流量计算显式 BLOCKED。详见 `R03B1_HYDVORF0_equation_trace.md`。

### HJ020

官方 `HJ020.c` 已闭合面积、容积、泄漏、压力力、端止点外壳和 port1/port2 符号；压力导数调用私有 `pcdyn2_`，扫掠流量使用 `q0top_`。两者只有声明，故压力 RHS 显式 BLOCKED。没有用 `dp/dt=beta/V*(Q-A*v)` 冒充 AMESim active branch。

## 6. dirvalve_6

- 外口：`ext0=P, ext1=T, ext2=B, ext3=A, ext4=signal`。
- 流路：`orifice_13=P-B`、`orifice_14=P-A`、`orifice_24=T-A`、`orifice_23=T-B`。
- 每路：1 L/min @ 1 bar，critical flow number=1000，method=1，measurement fluid=850 kg/m³ 与 60 cSt。
- static dynamics：FX00 映射后由 VALVEDYNAMICS0 截至 `[-1,1]`。
- 流量符号：路径名称第一端到第二端为正；组件端口以流入阀为正。

## 7. actuator001

- piston diameter：79.7884560802865 mm；piston area：0.005000000000000 m²。
- rod diameter：40.6842894512822 mm；rod area：0.001300000000000 m²。
- annular area：0.003700000000000 m²。
- stroke：0.13 m。
- dead volume 1/2：各 50 cm³ = 5e-5 m³。
- pressure states：`[p1,p2]`，初值均 0 bar gauge。
- leakage/viscous friction：当前均为 0。
- 合法行程压力力：`p1*A_p-p2*A_annular`；Python 的 `v=dxact/dt=-v_port`。

## 8. Fluid property

fluid index 0 对应 FP04、proptype=2：density=850 kg/m³，bulk modulus=17000 bar，absolute viscosity=51 cP，air/gas content=0.1%，saturation pressure=1000 bar。密度、体积模量、黏度均来自模型保存值；HYDVORF0 特征点另保存 850 kg/m³、60 cSt。由于 `fpconbmu_/pcdyn2_/q0top_` 未公开，当前只保存/换算参数，不声称完整流体性质已重构。

## 9. SingleActuatorRig

- state vector：`[p1_pa,p2_pa]`。
- inputs：`command,pP,pT,xact,dxact/dt`。
- planned outputs：spool、四路 opening/flow、P/T/A/B flow、p1/p2、force、leakage、volume/power diagnostics。
- solver：RHS 与 solver 已解耦；当前 RHS 在 HYDVORF0 guard 处终止，未调用 BDF/Radau。

## 10. 守恒与功率诊断

SC_1 端口记账使用四条路径构造，任意测试流路下 `qP+qT+qA+qB` 残差为数值零（测试容差 1e-18 m³/s）。这验证的是拓扑，不是尚未实现的 HYDVORF0 数值。

HJ020 的 AMESim 储能功率依赖 `q0top_` 及 `pcdyn2_`。在它们未闭合前，实际功率残差为 **unavailable**；报告数值会误导，因此未生成。

## 11. 配置与溯源

`scripts/hydraulics/generate_r03b1_config.py` 从 A2.5 冻结表生成三个 JSON。每个文件包含 `source_component`、`source_submodel`、`audit_file`。类内部没有客户模型几何、压力、流量或物性魔法数字。

## 12. 测试

- R03-A1/A2/A2.5 专项回归：39 passed。
- R03-B1 unit/integration：21 passed。
- 首轮 full project：121 passed, 1 failed；唯一失败是 A2.5 的阶段门禁仍禁止 `valve.py/cylinder.py`。
- 门禁按 R03-B1 范围收窄后最终 full project：122 passed。

A2.5 门禁调整仅允许本轮明确授权的 valve/cylinder 文件，仍禁止 Pump、完整 SC1Valve 和 HydraulicModel 网络文件。

## 13. 演示

`examples/run_r03b1_single_actuator.py` 成功读取正式配置并计算五个命令点的 spool/opening，随后按设计在 `orif3f_` traceability guard 停止，退出码 2。证据 CSV：`outputs/r03b1_single_actuator/r03b1_blocked_diagnostic.csv`。

没有生成 pA/pB/force 时间历程或图片；因此最大/最小 pA、pB、force 均为 unavailable。未出现 NaN/Inf；触发的是预期 physical traceability guard。

## 14. 已知阻塞与所需输入

1. Siemens 官方 `orifices.c/orifices_common.c` 中 `eqarea`、`orif3f_` 的算法说明，特别是层流—湍流过渡。
2. Siemens 官方 `pcdyn2.c` 及 fluid volume conversion `q0top_` 的算法说明，含 FP04 proptype=2 的气含量/饱和处理。
3. 若官方不能提供源码，可由 AMESim 2021.1 建立两个只读派生单组件试验：导出 HYDVORF0 正反向、低压差、过渡区特性，以及 FP04/HJ020 定容注流压力响应；必须冻结工况和版本后才可作为替代证据。

这些定义直接阻塞 HYDVORF0、HJ020 压力 RHS、动态 demo 与 B2 网络求解。

## 15. 未实现项

VALVEDYNAMICS0 mode 2/3、其他 SC_1 实例、高保真 endstop、57 个离散状态完整 owner、pump network、accumulator、relief valve、full line dynamics、机械耦合、PID/SMC、动态误差结论。

## 16. 冻结区与 Git

- `src/steering_sim/mechanics/` 等机械冻结区 diff：空，modified=NO。
- 未 commit、merge、reset、clean 或 checkout。
- 本轮改动仅为 hydraulics R03-B1 代码/配置/文档/示例和相关测试；已有审计成果仍保持原状态。

## 17. 自评与下一步

R03-B1：**BLOCKED**。

理由：A、B、D、E、F、G、J、M、N 基本满足；C 被严格遵守；但验收项 H（HYDVORF0 可信流量）、I（HJ020 可信压力 RHS）、K（最小动态 RHS 可运行）、L（动态字段对齐）不能满足。当前不建议进入 R03-B2。应先完成上述两个官方 utility 定义的人工/Siemens 证据闭合。

