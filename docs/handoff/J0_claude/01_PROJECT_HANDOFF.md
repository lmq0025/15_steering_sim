# 15所电液转向项目交接（J0 前）

## 1. 项目目标与当前阶段

项目名称为“电液转向系统质量性能评估方法”。最终目标是在离线 Windows 环境中形成不依赖 Amesim 的机械、液压、控制、性能退化与质量预测软件。

既定开发顺序是：L1-Fast 液压轻量模型 → M1 阿克曼机械模型 → **J0 控制—液压—机械首次联合调试** → 后续性能评估与退化预测。当前只允许开展 J0；不得提前开发退化、寿命或质量评价。

## 2. 当前正式模型

### 液压：L1-Fast V1

- 正式包：`E:\15_project\src\steering_sim\hydraulics_lumped`
- 构造入口：`LumpedHydraulicSystem.fast_engineering()`
- 联调用单步接口：`evaluate_hydraulic(model, t, state, HydraulicInput)`
- 四个通道、每通道 `[pA,pB,x,v]`，共 16 个连续状态；0 个管路动态状态。
- 两组预建压恒压供油；保留 SC_1 四孔口、反向流、双腔连续性和缸动力学。
- 固定步长基线为 0.5 ms；2 ms 已被数值检查否决。
- 已保存验收结果：1 s 实际墙钟约 0.684 s，100 s 约 68.795 s，完整仓库 `230 passed in 111.47 s`。
- 本轮轻量复核：L1-Fast 专项文件 `8 passed`。
- 状态：工程候选；独立 Amesim 宏观精度 `NOT_VERIFIED`，不能宣称达到甲方 10% 精度。

旧的 109-state/67-line-state 路线位于 `src/steering_sim/hydraulics` 及相应历史脚本/报告，仅作为历史实现和元件参数证据库。J0 不得恢复或调用它。

### 机械：M1

- 正式包：`E:\15_project\mechanics_ackermann_v2`
- 模型入口：`PhaseM1Model(geometry_path, config_path)`
- 甲方坐标输入：`E:\15_project\mechanical_model_input_spec_v1.0.yaml`
- 配置：`E:\15_project\mechanics_ackermann_v2\config.json`
- 六桥 12 轮；一桥主动，二桥由纵拉杆随动，三桥固定 0°，四至六桥各一机构自由度。
- 四个自由度：`q_front, q4, q5, q6`；七个物理缸几何接口：`front_group_1`、`axle4_A/B`、`axle5_A/B`、`axle6_A/B`。
- M1 默认输出：3111 工况、37332 条轮结果；已保存报告及本轮复核均为 `22 passed`；闭链最大杆长残差约 `1.46e-12 m`。
- 地面载荷、轮胎刚度、机构柔度及前桥缸映射含未标定工程假设，因此结论为条件适用。

M1 使用 `src/steering_sim/mechanics` 中冻结的 R02B 闭链求解器，但以 M1 上层拓扑删除了活动 `q3`。旧 R02B/R02D/R02E 仍保留五自由度历史拓扑，不是 J0 的直接入口。

## 3. 已冻结的物理与工程决策

- 甲方 Word 中的点值是 mm 坐标和绕 z 轴旋转副中心，绝不是角度范围。
- 坐标系：原点为一桥轮心连线中点，x 向前、y 向左、z 向上；内部长度统一转 SI 米。
- 不移动固定铰点，不更改零位杆长；五、六桥长连杆不得缩短。
- 三桥左右轮在任何工况恒为 0°；三桥油缸记录不激活。
- 二桥无独立控制量，必须由 `q_front` 闭链和纵拉杆随动。
- 七个物理缸不等于七个独立液压动态通道；当前只有四个液压通道和四个机构自由度。
- `ideal_ackermann_angle_deg` 是理想校核；`theoretical_angle_deg` 是无地面载荷的刚性机构角；M1 的 `actual_loaded_angle_deg` 是静态柔度演示值。
- J0 中实际轮角必须由液压缸实际位移反求机构自由度，再经闭链得到，不能复制目标角。
- J0 不得再次施加 M1 的静态 `q_loaded=q-Q/K` 柔度修正，否则会与液压位移/负载闭环重复计算。
- 不修改液压本构方程，不新增虚构液压状态，不提前接入退化或质量评价。

## 4. 当前限制与待确认

1. M1 已有 `q → 七缸几何行程 → 轮角`，但没有正式公开的“单一液压通道位移 → q”逆接口；J0 应在新建的联合适配层实现并测试，不应推倒重写 M1。
2. 前组因缺甲方安装硬点，使用 `stroke_front[m] = 0.25*q_front[rad]`。这是 `ASSUMED_ENGINEERING_PARAMETER_INTERFACE_PLACEHOLDER`。
3. 后三液压通道与 q4/q5/q6 的顺序对应在液压代码中没有跨模块显式证据。J0 暂按 rear_1→q4、rear_2→q5、rear_3→q6，必须标 `ASSUMED`。
4. 每个后桥有 A/B 两个真实几何缸，但 L1-Fast 每组只有一个等效动态通道。如何把等效液压力分配到双缸尚无实车证据。
5. 阀命令正号不等于左转正号；应以小扰动极性测试逐通道确认并固化配置。
6. 轮胎侧偏刚度、有效拖距、原地等效半径、四组机构刚度/阻尼、传感器零点及真实机械限位尚未由甲方标定。
7. M1 数值 q 包络是连续求解范围，不是甲方机械限位。部分默认工况因包络或模型适用性被标记不可行。

## 5. J0 工作边界

J0 只做四个 2–3 s 小工况的首次闭环：0°/0 km/h、+2°/5 km/h、−2°/5 km/h、+5°/10 km/h。控制更新 10 ms，液压积分 0.5 ms。使用最简单的可配置四通道 PID，带限幅和积分抗饱和。

联合运行必须保持单一状态所有权：液压模型积分四个 `x,v`，机械 `q` 由 `x` 代数反解，轮角由闭链计算；机械层不得再积分同一个自由度。道路广义负载通过行程雅可比换算为液压 `external_load_forces_n`，雅可比奇异点必须报告并停止该工况。

详细实施要求见 `03_J0_IMPLEMENTATION_BRIEF.md`，接口证据和假设见 `04_INTERFACES_AND_RISKS.md`。

## 6. Git 与保护范围

- 分支：`r02-mechanical-demo-entry`
- HEAD：`31475626ab39f9737f4113bb8e550ff1d7fae4b0`
- 工作树：**DIRTY**。包含大量现有未跟踪 L1/M1 交付，以及 `tools/Simcenter-Amesim-MCP` 子模块内部 dirty；不得 reset、clean、stash、提交或覆盖。
- 本轮检查时没有发现正在运行的 Python 进程；这不构成任何外部任务调度状态保证。
- 必须保护：`qh1_1.ame`、`qh1_1_MCP_AUDIT.ame`、`source_materials`、`mechanical_model_input_spec_v1.0.yaml`、两个正式模型目录及现有 outputs/docs/handoff。
- 原始材料：`source_materials`；历史交接：`docs/review`；液压验收：`docs/hydraulics`；M1 报告：`docs/mechanics/phase_M1_ground_load_ackermann_report.md`；已有快照：`.snapshots`。

本交接只新增文档和小型交接包，没有执行 J0，也没有修改液压、机械、控制或 Amesim 业务代码。
