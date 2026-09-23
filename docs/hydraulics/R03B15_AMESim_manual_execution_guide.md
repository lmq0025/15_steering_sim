# R03-B1.5 AMESim 单组件试验人工执行指南

## 0. 不可变边界

只使用 Simcenter AMESim 2021.1。不得打开后覆盖保存 `qh1_1.ame`。所有新模型保存在
`E:\15_project\amesim_experiments\r03b15\`，标题/注释写明
`DERIVED TEST MODEL — NOT CUSTOMER BASELINE`。任何数值均从两张扫描矩阵复制，
不得手抄另一套参数。

## 1. HYDVORF0 静态试验模型

### 1.1 建模

1. 新建模型，另存为 `R03B15_HYDVORF0_characterization.ame`。
2. 放置两个 Hydraulic pressure source，明确选择 exact submodel `PS00`
   （官方标签：piecewise linear hydraulic pressure source）。
3. 放置可变液压孔口并选择 exact submodel `HYDVORF0`；不要选择兼容 submodel。
4. 上游 `PS00` 接 HYDVORF0 port 1，下游 `PS00` 接 port 2。连接没有预设真实流向，
   `dp` 的记录定义为 `p1-p2`。
5. 用常值/分段信号源连接 HYDVORF0 opening signal port。输入量纲按当前 submodel
   参数界面的 `0..100`，不是 `0..1`；矩阵同时给出 `opening_fraction` 供核对。
6. 从 `dirvalve_6/orifice_14` 冻结配置逐项设置：method=1，characteristic flow
   1 L/min，corresponding pressure drop 1 bar，critical flow number 1000，measurement
   density 850 kg/m³，measurement kinematic viscosity 60 cSt，minimum/maximum signal
   0/100。section type、hydraulic diameter definition、area function等其余字段必须从
   `configs/hydraulics/r03b1/dirvalve_6_sc1.json`及审计 raw 记录复制；看不到证据的字段
   不改默认值，并在 manifest 记录。
7. 运行一次 `opening=100, dp=+1 bar` 的 smoke test，确认端口号、输出符号和保存变量，
   但不要据此修改矩阵或假定本构。

### 1.2 扫描

以 `r03b15_hydvorf_experiment_matrix.csv` 每行作为一个独立 run：

- 将 `upstream_pressure_bar_g` 填入 port-1 PS00；
- 将 `downstream_pressure_bar_g` 填入 port-2 PS00；
- 将 `opening_input` 填入信号源；
- 仿真到稳态（无状态的静态网络可用 0.01 s）；保存末端稳定值。

矩阵共 346 点：216 identification、130 validation。验证点使用独立开度与压差，
禁止移动到 identification 集。正反压差均通过交换高低压力形成，两侧边界始终不低于
5 bar(g)，避免用负绝对压力制造“反向”。

### 1.3 必须保存与导出

勾选 port-1 pressure、port-2 pressure、HYDVORF0 volumetric flow、opening input；若
variable list 提供 actual area / hydraulic diameter，也勾选。导出 UTF-8 CSV，列名严格
映射到结果模板：`test_id, opening_input, upstream_pressure_bar_g,
downstream_pressure_bar_g, pressure_drop_bar, flow_lpm, area_mm2,
hydraulic_diameter_mm, amesim_model_checksum, run_timestamp, notes`。
每个 test_id 一行；不可用的两个诊断列留空，不补猜测值。

## 2. HJ020/FP04 压力动态试验模型

### 2.1 建模

1. 新建并另存为 `R03B15_HJ020_characterization.ame`。
2. 放置双腔单杆缸，exact submodel `HJ020`。设置 piston diameter
   79.7884560802865 mm、rod diameter 40.6842894512822 mm、stroke 0.13 m、port1/2
   dead volume 各 50 cm³、leakage 0 L/min/bar、viscous friction 0 N/(m/s)。
3. 放置/复制当前 Hydraulic fluid properties，exact submodel `FP04`，fluid index=0、
   proptype=2；密度、体积模量、黏度、含气量和饱和压力由冻结配置复制。不要把
   17000 bar 直接写成实验结论中的常数 beta_eff。
4. 两个液压口各接一个 `QS00`（官方标签：piecewise linear hydraulic flow source）。
   要求零流量时可将其曲线设为 0；若因图标/因果要求需要零源，使用 exact submodel
   `Q000`（zero hydraulic flow source）。不要用压力源固定被测腔压力。
5. 机械端接 `VELC02`（conversion of a signal to a velocity in m/s and a displacement
   in m），由信号源同时规定 velocity 和 displacement；固定活塞时也可用 `V001`
   zero speed source，但必须确保初始位移等于矩阵 `x_initial_m`。
6. HJ020 的 `xact` 与机械端速度符号遵循 R03-B1 已冻结说明：`dxact/dt=-v_port`。
   首次 smoke test 对比导出的 `xact` 和命令；若 VELC02 输入需取负，只改边界信号
   映射并记录，不改 HJ020 或矩阵中 x/v 的物理定义。

### 2.2 三组正交试验

- **B1 固定活塞、规定流量**：`v=0`，按矩阵只激励一个腔，另一腔 Q=0。逐 run
  设置两腔 initial pressure 和 x。用于局部线性回归得到 compliance/beta_eff。
- **B2 零外部流量、规定运动**：两个液压口 Q=0，以 VELC02 规定 x/v；远离端止点。
  用 B1 的局部 compliance 反推 equivalent swept flow，不预设等于 A·v。
- **B3 组合验证**：同时设置 q1/q2/v，仅属于 validation；不得用于拟合 B1/B2 参数。

### 2.3 数值设置

每行 matrix 已冻结：duration 0.02 s、output interval 0.0001 s、relative tolerance
1e-8、导数拟合窗 0.002–0.008 s。Solver 选择 AMESim 2021.1 GUI 中的 Standard
variable-step，并把 GUI 显示的 exact solver 名称/版本写进导出 notes；如因模型因果性
必须改变 solver，只能整套重跑并更新 manifest。初始化必须显式设置 p1、p2、x，禁用
端止点接触工况。

### 2.4 保存与导出

按 `r03b15_amesim_variable_export_list.csv` 保存 time、xact、mechanical velocity、port1/2
flow、port1/2 pressure，以及可用时 jack force。导出长表，每个 test_id 有完整时间序列，
列名严格为结果模板字段。流量必须保存 AMESim 实际端口流量而不是命令值；若实际符号
与命令相反，不做手工翻转，在 notes 记录。

## 3. 结果目录与分析

原始导出放 `amesim_experiments/r03b15/results_raw/`；不要覆盖 `results_templates/`。
随后使用批准的 steering_sim 解释器运行两支分析脚本。脚本使用局部最小二乘斜率，
拒绝单步差分、缺 test_id、重复静态点和 identification/validation 数据泄漏。

本指南完成的是可重复实验准备，不代表试验已运行。没有真实 CSV 前，R03-B1 仍保持
BLOCKED，状态为 `WAITING_FOR_AMESIM_EXPERIMENT_RESULTS`。

