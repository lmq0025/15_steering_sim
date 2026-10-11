# PHASE J0-DEMO 阶段报告

**《电液转向系统联合仿真平台》——最小工程核查与中文演示软件封装**

工作目录：`E:\15_project`　唯一 Python：
`E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe`

---

## 1. 本轮做了什么

在**保留 J0-R1 全部正确成果**的前提下：

1. 完成三个必要的演示前检查，并修复其中查出的两个交付缺陷；
2. 建立中文本地交互界面《电液转向系统联合仿真平台》（Tkinter + Matplotlib）；
3. 提供一键启动脚本 `start_steering_demo.bat`；
4. 支持输入工况、运行仿真、预设回放、查看图表、导出 CSV 与结果报告；
5. 为后续退化预测与质量评估预留参数接口（不实现算法）。

**没有**重新开发液压模型、机械机构或 PID 控制器；**没有**研究旧 109 状态模型；
**没有**引入复杂轮胎模型、CFD、Amesim 逐元件复刻或新数值算法框架。

被控对象仍是 J0-R1 的正式模型：

| 层 | 模块 | 规模 |
|---|---|---|
| 液压 | `src/steering_sim/hydraulics_lumped` | L1-Fast V1，4 通道 16 状态，恒压预建压供油，0.5 ms |
| 机械 | `mechanics_ackermann_v2` | M1，六桥十二轮，4 机构自由度，7 缸几何接口 |
| 联合 | `src/steering_sim/j0_coupling` | 10 ms 控制 / 0.5 ms 液压，多速率 RK4 |
| 控制 | `steering_sim.control.pid` | 复用四通道 PID，kp=150 / ki=60 / kd=0 |

---

## 2. 三项演示前检查结论

完整证据见 [phase_J0_DEMO_checks.md](phase_J0_DEMO_checks.md)。

### 2.1 五、六桥车轮转角方向 —— **CONDITIONAL**

+5° 工况下五桥左轮 −1.549°、右轮 +0.870°，六桥左轮 −4.164°、右轮 +0.471°，
同桥左右轮反号；一、二、四桥两轮同向。

逐条核查后确认：

| 核查项 | 结论 |
|---|---|
| 左右镜像角度的定义 | 全部刚体绕同一 +Z 轴，无左右局部镜像角 |
| 轮胎局部角与整车全局角的转换 | 模型直接用刚体姿态角，`SteeringWheelBody` 定义为车轮转角 |
| 左右轮命名 | M1 自身规定左转外侧轮为 `axle1_right`，`POS_Y→left` 正确 |
| 是否存在符号换算错误 | 镜像自洽关系 `w_POS(q) = −w_NEG(−q)` 在机器精度成立，不存在 |
| 机构真实闭链是否确实给出该结果 | 是。条件数 16~36，杆长残差 ~1e-13 m，0~7° 连续扫描无分支跳变 |

**结论：保留结果，标记 `ACKERMANN_GEOMETRY_DEVIATION`。**
不修改甲方真实铰点坐标与杆长，也不把该角度宣称为理想阿克曼精确结果。
平台在界面与报告中始终把"实际角 / 机构可达角 / 理想阿克曼角"作为三个不同的量
分别展示。

### 2.2 供油能力 —— **WARNING**

| 来源 | 前组泵供量 | 前阀中位高压轨取流量 | 余量 |
|---|---:|---:|---:|
| `phase_J0_R1_assumptions.md` 的估计 | 27 L/min | ~36 L/min | 估计为不足 |
| 模型实际阀口流量核算（前腔 9.394 MPa） | 27.00 L/min | **25.84 L/min** | **+1.16 L/min（4.3%）** |

不一致的原因已查明：假设文档的 ~36 L/min 对应**低压**情形（前腔 0.2~0.5 MPa 时
实际取流 37.6/37.3 L/min），而 J0 前组中位实际压力是 9.394 MPa，取流降到 25.84 L/min。

报警计算本身**没有错**：用未编译孔口路径独立复算，与模型内部编译路径在全网格上
最大偏差 6.5e-15 L/min（机器精度）；低压工况下 `capacity_insufficient` 确实会触发。
因此 J0-R1 的 `pump_capacity_warnings = 0` 是正确的。

但**余量只有 4.3%，不能显示"供油能力完全正常"**。本轮新增：

- `SUPPLY_CAPACITY_NEAR_LIMIT`（余量 < 泵供量 10%，黄色警告）；
- `SUPPLY_CAPACITY_OUT_OF_RANGE`（出现真实缺口，明确说明该工况不能标记为
  真实泵能力下验证通过）。

未恢复复杂供油牛顿网络，未使用任何人为硬限压。

### 2.3 统一结果文件与图表 —— **已修复**

**缺陷 A：字段名与单位不符。**
`phase_J0_R1_results.json` 的 `final_stroke_mm` 实际装的是以**米**为单位的行程
**区间**，且与同文件内以毫米计的 `target_x_ref_mm` 混用。已拆分为语义正确的三个
字段（`final_stroke_mm` 末值 / `final_stroke_error_mm` 末值误差 /
`stroke_range_mm` 区间），统一按 `_mm`=毫米、`_m`=米换算。

**缺陷 B：图与摘要不同源。**
`package_phase_J0_r1.py` 把含地面负载（5 s）与无地面负载（3 s）两组同名图像复制进
同一个 `figures/` 目录，后者覆盖前者，导致交付图像横轴只有 3 s 而报告引用 5 s 结果。
实证：交付的 `J0-01_..._fig1.png` 为 100 416 B（= `j0_r1_noload` 版本），
而 5 s 版本是 98 451 B。已分目录存放（`figures/` 与 `figures_no_road_load/`，
后者前缀 `NOLOAD_`），并重新生成 J0-R1 结果 JSON 与交付包。

平台另加自动判据 `TIME_AXIS_SHORTER_THAN_REQUESTED`，任何一次运行的时间序列末点
与请求时长不符即判失败。

---

## 3. 中文演示界面

### 3.1 技术选型

检查 `steering_sim` 环境：`streamlit` **未安装**，`tkinter` 可用。
按任务书"不强制联网安装新依赖"，采用 **Python Tkinter + 现有 Matplotlib**，
不引入新前端框架。

### 3.2 结构

```
src/steering_sim/demo/
    scenario.py      工况输入、范围校验、四个预设
    assessment.py    三项演示前检查 + 运行后一致性校验
    service.py       唯一的"跑一次仿真"入口（含预设缓存与导出）
    plots.py         六张演示图（含六桥十二轮俯视图）
    ui.py            Tkinter 中文界面
    cli.py           无界面命令行入口
    degradation.py   退化/质量评估参数接口（预留，不实现算法）
scripts/j0_demo/start_demo.py     一键启动（环境自检 + 中文错误提示）
start_steering_demo.bat           双击启动
```

**界面与缓存共用同一条计算路径**，因此图像、结果摘要与时间序列必然来自同一次仿真。

### 3.3 输入

一桥外侧目标转角、车速、地面摩擦系数、六桥轴荷、仿真时长、四个预设工况。

默认值：转角 0°、车速 0 km/h、**摩擦系数 0.75**、**每桥轴荷 11.5 t**、时长 5.0 s。
后两者是工程假设（`ASSUMED_ENGINEERING_PARAMETER`），界面明确标注。

范围策略：

| 层级 | 处理 |
|---|---|
| 超出甲方任务书范围（±30°、0~80 km/h、μ 0.7~0.8、轴荷 10~13 t） | **拒绝运行**，给出中文原因 |
| 在任务书内但超出已验证动态联调范围（±5°、0~10 km/h、μ=0.75、11.5 t） | 允许运行，标记 `EXTRAPOLATION:*` |
| 机构闭链不可达（如 +20°、+30°） | **拒绝运行**，报 `GEOMETRY_INFEASIBLE` |

不静默外推，不因为用户输入 ±30° 就强行运行到异常状态。

### 3.4 结果展示（六张图，全部来自同一次仿真）

| 图 | 内容 | 对应要求 |
|---|---|---|
| `fig1_plan_view.png` | 六桥十二轮俯视结构示意，实际角/机构可达角/理想阿克曼角三线叠加，三桥高亮锁止 | A |
| `fig2_wheel_angles.png` | 按桥分组的目标与实际车轮转角，三桥固定可见 | A、C |
| `fig3_strokes.png` | 四通道液压缸行程与活塞速度 | B、C |
| `fig4_hydraulics.png` | A/B 腔压力、液压力 vs 地面负载、主阀控制输入、A 腔流量 | B |
| `fig5_control.png` | 行程误差、轮角跟踪误差、PID 输出 | C |
| `fig6_case_and_supply.png` | 附着利用率、轮胎侧偏角、泵供量 vs 高压轨取流与余量、工况与限制文字面板 | B、D |

### 3.5 交互与导出

选择工况 / 修改输入 / 运行仿真 / 预设回放 / 恢复默认 / 导出 CSV / 导出结果报告。

**「预设结果回放」与「重新运行仿真」被严格区分**，界面右上角始终显示结果来源；
回放另附缓存时间与代码版本，不会被显示成"刚刚完成的实时仿真"。

### 3.6 一键启动

`start_steering_demo.bat` 使用指定解释器，处理路径中的空格，
失败时给出中文原因（解释器不对 / 依赖缺失 / 文件不完整）并暂停等待查看。
不依赖 Amesim，不需要联网，未引入复杂打包工具。

---

## 4. 四预设工况结果

四个预设与 J0-R1 已交付的四工况参数完全一致（μ=0.75、每桥轴荷 11.5 t、5 s）。

| 预设 | 目标 | 车速 | 判定 | 机械检查 | 供油检查 |
|---|---|---:|---|---|---|
| J0-01 | 0° | 0 km/h | PASS | OK | NEAR_LIMIT |
| J0-02 | +2° | 5 km/h | CONDITIONAL | ACKERMANN_GEOMETRY_DEVIATION | NEAR_LIMIT |
| J0-03 | −2° | 5 km/h | CONDITIONAL | ACKERMANN_GEOMETRY_DEVIATION | NEAR_LIMIT |
| J0-04 | +5° | 10 km/h | PASS | ACKERMANN_GEOMETRY_DEVIATION | NEAR_LIMIT |

J0-02/J0-03 判 CONDITIONAL 的唯一原因是前通道稳态残差 0.311°（超 0.25° PASS 带），
该限制已在 J0-R1 用 5 组增益试验证明不是整定问题，本轮未再动 PID。

结构化的逐桥、逐通道数值见交付包中的 `demo_checks.json`。

---

## 5. 退化与质量评估接口

`src/steering_sim/demo/degradation.py` 预留 13 个退化参数
（泵容积效率、泵排量、阀流量系数/响应/泄漏、缸内外泄漏/摩擦/阻尼、
PID 三个增益与控制限幅），健康值一律 1.0，**不改变任何现有默认值**。
每个参数都标注了在现有模型中的落点。

界面显示「性能退化与质量评估（待开发）」，
**当前不输出任何寿命或质量预测数值**；未实现的入口显式抛
`DegradationNotImplementedError`，不返回占位数字。

详见 [phase_J0_DEMO_degradation_interfaces.md](phase_J0_DEMO_degradation_interfaces.md)。

---

## 6. 最小验收自检

| # | 验收项 | 结果 |
|---|---|---|
| 1 | 页面能正常打开 | PASS |
| 2 | 四个预设工况能加载 | PASS |
| 3 | 直行可以运行 | PASS |
| 4 | 左转 +2° 可以运行 | PASS |
| 5 | 右转 −2° 可以运行 | PASS |
| 6 | 左转 +5° 可以运行 | PASS |
| 7 | 十二轮角来自真实缸位移 | PASS（闭链反求，首点不为目标角） |
| 8 | 三桥保持零角 | PASS（≤1e-9°） |
| 9 | 图表、数据和单位一致 | PASS（`TIME_AXIS_SHORTER_THAN_REQUESTED` 判据） |
| 10 | CSV 能正确导出 | PASS |
| 11 | 超适用范围输入能正确提示 | PASS（拒绝运行 + 外推标记） |
| 12 | 供油能力不足不会被隐藏 | PASS（NEAR_LIMIT / OUT_OF_RANGE） |
| 13 | 不产生 NaN/Inf 或不明原因超高压力 | PASS |
| 14 | 未调用 Amesim | PASS（进程内无 Amesim 模块） |
| 15 | 退化预测没有虚假计算结果 | PASS（显式抛异常） |

---

## 7. 本轮修改的文件

| 文件 | 修改 |
|---|---|
| `src/steering_sim/demo/*`（新增 8 个） | 演示平台 |
| `scripts/j0_demo/start_demo.py`、`package_phase_j0_demo.py`（新增） | 启动器与打包器 |
| `start_steering_demo.bat`（新增） | 一键启动 |
| `src/steering_sim/j0_coupling/runner.py` | 补出 `final_stroke_m` / `final_stroke_error_m` 字段；`run_case` 增加可选 `on_progress` 回调（只供界面显示，不影响数值） |
| `scripts/j0/build_j0r1_results.py` | 修正字段名与单位 |
| `scripts/j0/package_phase_j0_r1.py` | 图像分目录，杜绝同名覆盖 |
| `scripts/j0/check_wheel_sign_convention.py`（新增） | 轮角方向核查脚本 |
| `tests/demo/*`（新增 3 个） | 演示层回归测试（35 条） |

**未修改**：L1-Fast 液压本构、Amesim 文件、甲方铰点坐标与杆长、
`mechanics_ackermann_v2` 的几何与判定逻辑、PID 以外的控制、退化与质量模块。

### 7.1 两个实现上的坑（已修正，记录备查）

**批处理文件不能含多字节字符。** `start_steering_demo.bat` 最初写成 UTF-8 中文 +
`chcp 65001`，结果 cmd.exe 会以**错误的字节偏移重读自身**，把中文行撕裂成
"不是内部或外部命令"，并最终去调用 PATH 里排在前面的
`E:\Simcenter\2021.1\Amesim\python.bat`（该机器上 `where python` 的第一项）。
现在该文件是**纯 ASCII + CRLF**：cmd 层只做判断与跳转，所有中文（横幅、
自检结果、错误原因）一律由 Python 输出；两处 BAT 级失败用
`powershell -EncodedCommand`（UTF-16LE base64）弹中文对话框，同样不依赖代码页。

**界面不能在后台线程里积分。** 早期版本把积分放在工作线程、主线程用
`update()` 泵事件，在 Tk 存在时会在垃圾回收阶段**间歇性触发进程级致命异常**
（`Windows fatal exception: code 0x80000003`，栈顶为 GC）。改为**单线程 +
进度回调**（`run_case(on_progress=…)`）后彻底消除，界面在积分期间由模态进度窗
接管，不会重入。

### 7.2 J0-R1 交付包已重新生成

因检查 3 的缺陷，`handoff_to_chatgpt/phase_J0_R1.zip` 已用修正后的打包器重建：

- 58 个成员（原 46），新增 `figures_no_road_load/`；
- zip 2.17 MB → 4.11 MB（两组图像不再互相覆盖，图变多）；
- 新 sha256 `4ff3328027da8f4d8e0bb503886fc4df32beca250bd0ee8ecf4e8f2b675b0699`
  （原 `3346eecf…` 作废）；
- `phase_J0_R1_results.json` 的行程字段名与单位已修正；
- 风险登记册 `05_J0_PLANT_DEFECT_AND_KNOWN_RISKS.md` 增加了第 9、10 节
  （本轮新增 F-D1…F-D6 与 J0-DEMO 入口）。

J0-R1 的四个工况结论**未发生变化**（重跑后仍为 PASS / CONDITIONAL /
CONDITIONAL / PASS）。

---

## 8. 剩余问题

见 [phase_J0_DEMO_assumptions.md](phase_J0_DEMO_assumptions.md)：

- `F-D1` 五、六桥左右轮反号 —— 已标记，未解决（需甲方确认硬点或机构方案）
- `F-D2` M1 拟合残差不报警 —— 已记录，未修改冻结模型
- `F-D3` 前组供油余量 4.3% —— 已加黄色警告
- `F-D4` 前通道闭环残差 0.311° —— J0 遗留，非整定问题
- `F-D5` 大转角机构不可达 —— 平台拒绝运行
- `F-D6` 轮胎与地面模型为简化模型

---

## 9. 交付物

| 交付物 | 路径 | 校验 |
|---|---|---|
| 演示平台交付包 | `handoff_to_chatgpt/phase_J0_Demo.zip` | CRC OK，53 个成员，解压 5.17 MB，压缩 4.62 MB（zip 自身的 sha256 无法写进包内，见交付说明与包内 `SHA256SUMS.txt`） |
| J0-R1 交付包（已修正重建） | `handoff_to_chatgpt/phase_J0_R1.zip` | CRC OK，58 个成员，4.11 MB，sha256 `4ff3328027da8f4d8e0bb503886fc4df32beca250bd0ee8ecf4e8f2b675b0699` |

## 10. 结论

控制—液压—机械三模块闭环可运行，十二轮角全部由真实液压缸位移经机构闭链反求，
三桥锁止，无人工诊断阻尼，无 NaN/Inf。演示平台可离线运行、可一键启动、
可输入工况与导出结果，并能如实暴露机械拓扑偏差与供油余量边界。

全仓测试（本阶段交付时）：**394 passed**（340.58 s，0 failed），其中演示层 35 条。

> 注：后续 PHASE M2 扩充了演示层与机械层；PHASE M3 又新增了
> `REDESIGNED_ACKERMANN` 机械模式（本文件描述的演示平台因此新增了机械模式选择，
> 默认改为优化设计机构，`AS_BUILT_REFERENCE` 仍可单独查看）。
> 详见 `docs/mechanics/phase_M2_report.md` 与 `docs/mechanics/phase_M3_report.md`。
>
> **本报告记录的四个预设工况结论与验收自检针对的是 `AS_BUILT_REFERENCE`
> （甲方原始机构）**；PHASE M3 的演示层测试用显式的 `mechanical_mode` 夹具
> 继续锁定这些原始机构行为，没有因为换了默认模式而删改任何一条。

**本轮到此停止，不进入 J1 控制整定、退化建模、雨流、寿命预测或质量评估开发。**

仓库状态：分支 `r02-mechanical-demo-entry`，HEAD `31475626ab39f9737f4113bb8e550ff1d7fae4b0`
未变；未做 commit / push / reset / clean / stash；甲方坐标、杆长与 Amesim 文件字节未变。
