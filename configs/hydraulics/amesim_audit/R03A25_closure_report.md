# R03-A2.5 参数闭合、唯一标识修正与验证基准冻结报告

## 1. 任务边界

本轮只消费已验收的 R03-A1/R03-A2 表和只读官方 submodel 元数据，完成引用闭合、标量键修正、验证基准冻结和 VALVEDYNAMICS0 模式确认。未重扫结构，未覆盖 A1/A2 正式表，未编写液压机理方程。

## 2. 原模型完整性

- 路径：`E:\15_project\qh1_1.ame`
- 开始/结束 SHA256：`7613615723973d66a7122c74956c5161f720a64b243139fe9736cb270303b767` / `7613615723973d66a7122c74956c5161f720a64b243139fe9736cb270303b767`
- 大小：87357440 bytes
- mtime_ns：1780635133163901600
- 是否修改：NO

## 3. Python 环境

`E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe`

## 4. R03-A2 继承数据

输入为 A2 的 4334 行正式参数、369 行初值/状态、2371 行变量和 608 条 A/B 候选验证通道。A2 表保持不变。

## 5. global/local reference 解析方法

局部引用按模型级 `GLOBALPARAM` 名称解析；SC_1 全局引用按内部组件所属 parent 和 `USES_SC_GP` 规范名解析。链保留原始名称、目标、深度和完整路径。只允许数值、四则运算、幂、PI 和 sqrt 的受限表达式求值；循环和不支持表达式不会静默求值。

## 6. 关键参数解析结果

- global_reference：84 行；RESOLVED=84。
- local_reference：44 行；RESOLVED=44。
- R03-B 关键参数冻结行：1432。

- HA001: 12 行，未解析 0 行，保留非数值 raw 0 行。
- HJ0022: 51 行，未解析 0 行，保留非数值 raw 0 行。
- HJ020: 45 行，未解析 0 行，保留非数值 raw 0 行。
- HJ021: 16 行，未解析 0 行，保留非数值 raw 0 行。
- HYDVORF0: 1032 行，未解析 0 行，保留非数值 raw 129 行。
- PU001: 12 行，未解析 0 行，保留非数值 raw 0 行。
- RV010: 12 行，未解析 0 行，保留非数值 raw 0 行。
- SC_1: 192 行，未解析 0 行，保留非数值 raw 38 行。
- VALVEDYNAMICS0: 60 行，未解析 0 行，保留非数值 raw 0 行。

## 7. unresolved references

- 无。

## 8. scalar variable key 规则

优先使用 `component_id::Data_Path`；若 Data_Path 缺失或不唯一，则使用 `component_id::amesim_variable_id::variable_name::scalar_index`。原 base/group id 不删除。共 2371 个标量变量键，重复 0。

## 9. scalar state key 规则

规则与 variable 相同，并在碰撞时加入 state_type。共 369 个标量 state/initial-condition 键，重复 0。

## 10. channel re-key 结果

A2 的 608 条候选通道全部保留 old_channel_id，并新增唯一 new_channel_id；重复 0。

## 11. baseline validation set

冻结 24 条：accumulator=3，cylinder=5，pressure_valve=1，pump=3，return=1，supply=1，valve=10。

该集合覆盖供油、回油、泵、代表 HJ020、代表 SC_1、蓄能器和 RV010。SC_1 父接口单位缺失项继续写 `missing`，未按物理常识补单位。

## 12. 为什么选择这些通道

选择边界输入、组件核心输出、功率/泄漏诊断和可直接绑定的 AMESim scalar key。只取一个代表缸、一个代表阀、一个蓄能器和一个压力阀，避免重复实例淹没验收集合。

## 13. diagnostic pool 与 baseline 的区别

608 条 A/B 记录仍是 candidate pool；HL012 的大量 `pn_n/qn_n` 是 diagnostic pool。baseline 只含一个有明确供油代表意义的管路压力，不批量纳入内部节点。

## 14. VALVEDYNAMICS0 调查结果

官方 `.spe` 和 `.c` 已交叉确认枚举、参数可见性、状态尺寸和代码分支。未修改或编译安装文件。

## 15. spool dynamics=1 的含义

值 1=`no (static)`，dynamic order=0；time constant、natural frequency、damping ratio 均不参与当前模式。值 2 为一阶并使用 time constant；值 3 为二阶并使用 natural frequency 与 damping ratio。

## 16. 57 个离散状态是否阻塞 R03-B

不阻塞第一批静态 SC_1 和基础泵/缸组件代码化。VALVEDYNAMICS0 明确有两个整数 store（limit/endstops）；其他 HJ/RV/PV/line 的逐项归属仍 UNKNOWN，涉及端止点、滞环、切换或流态事件的高保真复现必须后续专项验证。

## 17. remaining missing / unknown

- SC_1 父接口 P/T/A/B 压力、流量单位元数据缺失，baseline 继续保留 `missing`。
- 57 个全模型离散状态没有逐项名称或 owner 映射。
- 代表 supply line 的物理命名基于现有拓扑证据；动态对比阶段应以 AMESim 导出通道再次 spot-check。

## 18. 是否可以进入 R03-B

建议 **YES WITH CONDITIONS**：可以从 PU001、HJ020/HJ0022/HJ021、HA001、RV010 和当前静态模式 SC_1 开始；必须保留单位缺失、离散事件归属和供油通道命名三项限制，且不能宣称已完成动态精度验证。
