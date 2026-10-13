# PHASE D4-R1 交付报告

## 1. 交付结论

D4-R1 已完成约定范围内的三项工作：修复 Windows 正式 BAT 启动链路；在联合仿真页加入可配置的线性斜坡指令及 12 轮/4 组等效作动通道的到位和稳态分析；形成目标设备信息表和跨平台离线部署计划。没有修改机械坐标、退化速率、寿命阈值，也没有开展新的退化或控制算法研究。

正式模型仍为：

- `ENGINEERING_STEERING_MODEL`
- `ENGINEERING_HYDRAULIC_V1`
- 4 个等效作动通道、22 个连续状态

## 2. BAT 闪退原因、修复与验收

### 2.1 真实原因

在未激活 Conda、当前目录为 `C:\Windows` 的普通 `cmd.exe` 中运行原正式 BAT，实际出现了诸如 `'确认' is not recognized`、`'APP_ROOTAPP_ROOT"' is not recognized` 等错误。根因是原 BAT 使用 UTF-8/LF 且含中文命令文本，普通 Windows `cmd.exe` 按本机代码页解析后破坏了命令边界；这与“脚本内启动 Qt 成功”不是同一条启动链路。

### 2.2 修复

- `start_steering_desktop.bat` 改为纯 ASCII、CRLF 的薄启动外壳；
- 固定使用唯一 Python：`E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe`；
- 从任意当前目录切换到项目根目录，初始化该环境的 `Library\bin`、`Scripts`、`bin` 和项目 `PYTHONPATH`；
- 新增 `scripts/d4/launch_desktop.py`，在导入 Qt 之前创建日志并记录 Python、工作目录、DLL 搜索目录、关键依赖、Qt 初始化、主窗口创建、完整 traceback 与退出码；
- 首选日志目录为 `outputs/desktop/logs/`，不可写时回退到 `%LOCALAPPDATA%`，再回退临时目录；
- 非零退出时 BAT 保留命令窗口并给出日志位置；正常关闭返回 0，不误报失败。

### 2.3 实测结果

以下均运行了真实 Qt 主窗口而非仅导入模块：

1. 未激活环境、从 `C:\Windows` 调用正式 BAT：通过；
2. 显式激活 `steering_sim` 后运行 `python -m steering_sim.desktop --maximized`：通过；
3. 直接使用唯一 Python 运行同一模块：通过；
4. 正式 BAT 窗口持续显示 30 秒：通过；
5. 自动轮换五个业务页并执行一次健康联合仿真：通过；
6. 正常关闭后第二次从 `C:\Windows` 启动：通过，退出码 0；
7. 启动日志示例：`outputs/desktop/logs/desktop_startup_20261013_171301_4548.log`。

自动化环境无法产生“资源管理器鼠标双击”这一物理输入事件；本轮完成的是与双击相同的未激活普通用户 `cmd.exe /c start_steering_desktop.bat` 链路，并取得真实窗口和日志证据，不把脚本内测试冒充鼠标操作。

## 3. 6 s/°斜坡进入真实 22 状态模型的方式

联合仿真页新增“阶跃输入/斜坡输入”。阶跃仍调用原接口和原 0.5 ms 液压步长，默认行为未改变。斜坡模式输入初始外轮角、最终外轮角、每度斜坡时间和目标后观察时长：

`command_completion_s = abs(final_angle - initial_angle) * seconds_per_degree`

归一化参考量在指令完成前按时间线性增长，完成后保持。每个积分时刻均由原机械逆运动学把一桥外侧轮目标角映射为 4 个作动通道目标行程；控制器接收这些时变行程，22 状态液压模型积分得到 4 组真实位移，再由正式机械模型映射为 12 轮实际角。显示层没有把目标数组复制成实际数组。

非零初始角（例如 +10°→−10°）先运行同一 22 状态模型建立真实液压初态，再将最终状态作为连续斜坡计算的初态。验收数据中跨零工况 `t=0` 的一桥左轮目标/实际角均为约 10.355°，随后连续积分到负向目标，证明没有重置为零位。

## 4. 到位与稳态判据

判据集中在 `configs/desktop/d4_r1_response_analysis.json`，全部标记为 `ENGINEERING_DESIGN_ASSUMPTION / PENDING_CLIENT_CONFIRMATION`，没有修改原 J1-R2 `TRACKING_PASS` 阈值：

| 判据 | 当前值 |
|---|---:|
| 轮角终值容差 | 0.10° |
| 等效通道位移终值容差 | 0.00020 m |
| 轮角速度阈值 | 0.02°/s |
| 活塞速度阈值 | 0.0010 m/s |
| 连续稳定观察窗口 | 2.0 s |
| 默认最大保持观察时长 | 10.0 s |

- 指令完成时间：最终目标斜坡完成的时刻；
- 首次到位时间：指令完成后，实际值首次进入最终目标位置容差带的采样时刻；
- 稳态建立时间：指令完成后，位置和速度同时合格，并在随后完整 2 s 窗口内持续合格的最早时刻；
- 全轮/全通道/整机共同稳态：在同一时刻以后，所有对应信号持续满足条件的最早时刻，不是各信号短暂进入容差时间的简单最大值；
- 仿真范围内没有满足连续窗口时返回 `NOT_SETTLED_WITHIN_HORIZON`，绝不以仿真结束时间代替。

0°目标和不转向的第三桥仍执行同一最终位置与速度判据，零目标不会造成除零或用相对百分比误判。

## 5. 实际斜坡验收与性能

标准条件：5 km/h、摩擦系数 0.8、六桥各 11.5 t、6 s/°、目标完成后保持 5 s；运行硬件为 Windows AMD64、Intel64 Family 6 Model 183、16 逻辑处理器。以下时间均来自实际 22 状态积分：

| 工况 | 指令完成/s | 12轮共同稳态/s | 4通道共同稳态/s | 整机共同稳态/s | 服务墙钟时间/s |
|---|---:|---:|---:|---:|---:|
| 0→+2° | 12.00 | 12.40 | 12.00 | 12.40 | 14.21 |
| 0→+5° | 30.00 | 30.40 | 30.00 | 30.40 | 29.30 |
| 0→+10° | 60.00 | 60.39 | 60.00 | 60.39 | 53.84 |
| 0→−10° | 60.00 | 60.39 | 60.00 | 60.39 | 53.81 |
| +10→−10° | 120.00 | 120.39 | 120.00 | 120.39 | 104.76 |
| 0→+30° | 180.00 | 180.28 | 180.00 | 180.28 | 153.19 |

0→30°未能在一分钟内完成，已如实记录。长斜坡 GUI 使用 2 ms 液压积分步长、10 ms 原控制周期和 10 ms 记录间隔；历史阶跃仍为 0.5 ms。0→2°同工况与原 0.5 ms 对照结果：墙钟时间 50.65 s 降至 13.82 s（3.66 倍），最终轮角最大差 `7.11e-15°`，最终缸位移最大差 `2.43e-17 m`，两供油轨峰值压力最大差 0 MPa。对照结果见 `outputs/desktop/r1/ramp_timestep_validation.json`。

## 6. 界面和导出

联合仿真页新增：

- 输入指令类型、初始角、每度斜坡时间和目标后观察时长；
- 可选择任意一个车轮的目标/液压实际角曲线；
- 可选择 4 组等效作动通道的目标/实际行程曲线；
- 指令完成、首次到位、单信号稳态、共同稳态竖直标线；
- 12 轮和 4 通道中文时间表；
- 原始时间序列与两个响应时间 CSV；
- 当前表格、当前图、项目和综合报告沿用 D4 导出能力。

真实 Qt 截图位于 `outputs/desktop/r1/`：`bat_startup_main.png`、`ramp_wheel_dynamics.png`、`ramp_cylinder_dynamics.png`、`ramp_wheel_response_table.png`、`ramp_cylinder_response_table.png`。GUI 0→2°完整后台工作流 16.95 s，计算期间窗口事件循环保持运行，旧结果不会作为新结果显示。

## 7. 兼容性与配置保护

- 阶跃入口未设置斜坡参数时仍走原 `run_case` 默认参考曲线；
- 斜坡功能只在联合仿真页显式启用，D1/D2/D3 与 D2 标准动态测试默认不变；
- 未修改 `configs/j1/engineering_mechanism.json`、`mechanical_model_input_spec_v1.0.yaml` 的机械意义或坐标；
- 当前 SHA-256：机械设计 `21d4c39edc5aae4aafc9a37175aaaf4e1d5c9412a63d44211c849ebc6fa44f9b`，正式液压 `9720085e65c4af961bca81305e3bd088e6bad6093141dc6de56bef41b9b5cdcc`，原始机械输入 `693103a3c4914dbb94491008869543d669631a955400f5baaa55772dbd664c95`；
- D4-R1 专项及 D1/D2/D3/桌面相关回归：74 passed；D4-R1 与 J0 取消增量复测：19 passed；
- J0/J1-R2 耦合、正式液压和机械映射核心回归：141 passed；
- 全仓单次受限工作区运行：624 passed，1 failed，1 teardown error，耗时 941.15 s。失败和 teardown error 均来自同一历史测试 `test_saved_json_schema`，原因是托管沙箱拒绝在 `outputs/test_tmp` 新建临时目录中写 `demo.json`，不是数值或业务断言失败；将该唯一测试以同一 Python 在沙箱外单独复跑为 1 passed（3.77 s）。因此合并验证覆盖的 625 项功能测试全部通过，但保留单次全仓命令的真实 ACL 失败记录，不把它隐去。

## 8. 跨平台离线部署准备

`docs/deployment/OFFLINE_DEPLOYMENT_PLAN.md` 已记录当前依赖版本、Windows x64、Linux x86-64、国产 Linux/ARM64、Qt 插件、图形桌面、wheelhouse/Conda 离线介质和验收清单。`TARGET_DEVICE_INFORMATION.xlsx` 用于收集操作系统、CPU 架构、内存、磁盘、管理员权限、图形桌面、安装与 U 盘限制等信息，包含样式、冻结窗格、自动筛选、数据校验和必填状态公式。

跨平台源码兼容不等于打包产物跨平台。当前只验证了 Windows AMD64 源码环境。PyInstaller 构建脚本已保留，但当前唯一环境未安装 PyInstaller，因此本轮没有生成或虚报独立 EXE。Linux、国产 Linux、ARM64 必须取得目标设备信息后，在同操作系统/同架构构建并重新做数值和 GUI 验收。

## 9. 复现命令

```bat
E:\15_project\start_steering_desktop.bat
```

```powershell
E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe scripts/d4/run_ramp_acceptance.py
E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe scripts/d4/validate_ramp_timestep.py
E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe scripts/d4/capture_d4_r1_evidence.py
E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe -m pytest -q tests/desktop tests/degradation tests/quality_assessment tests/demo/test_demo_scenario_and_assessment.py tests/demo/test_j1r2_ui_and_batch.py
E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe -m pytest -q tests/j0_coupling tests/hydraulics_engineering tests/ackermann/test_m3_redesign.py
E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe -m pytest -q -p no:cacheprovider
```

## 10. 限制与待确认项

- 到位/稳态容差为工程假设，待甲方确认；
- 2 ms 长斜坡步长已做 0→2°对照，尚未逐个用 0.5 ms 重跑 180 s 长工况；
- 0→30°当前约需 153 s，优先保证真实动力学与 GUI 不冻结，没有虚报一分钟内完成；
- 实际甲方设备的操作系统、CPU 架构、权限、图形桌面和介质策略未知；
- 尚未在甲方实机执行资源管理器物理双击，也尚未构建独立 EXE；
- 本轮到此停止，不进入新的退化、寿命或控制策略研发。

