# PHASE D4 电液转向系统质量性能评估与预测软件交付报告

## 1. 交付结论

PHASE D4 已形成一套中文、离线运行的 PySide6 桌面软件，正式入口为
`start_steering_desktop.bat`。软件包含联合仿真、任务载荷谱、部件退化预测、
当前质量评估、剩余任务循环预测五个可操作页面，并通过服务层直接调用
J1-R2、D1、D2、D3 的正式接口。

正式模型保持为：

- `ENGINEERING_STEERING_MODEL`
- `ENGINEERING_HYDRAULIC_V1`

本阶段没有重写机械、液压、退化或寿命内核，没有修改甲方机械坐标，没有
将准稳态批量估计包装为完整动态仿真，也没有修改阈值或结果以改善界面展示。

## 2. 软件结构与运行方式

新增 `src/steering_sim/desktop/`：

- `app.py`：主窗口、左侧导航、工程工具栏、状态栏和后台任务协调；
- `pages.py`：五个业务页面；
- `services.py`：J1-R2/D1/D2/D3 正式计算接口适配；
- `worker.py`：`QThread + QObject Worker` 单任务后台执行、安全检查点取消；
- `models.py`：表格模型和可追溯工程文件；
- `widgets.py`：指标卡、状态提示、可筛选表格、PyQtGraph 工程曲线；
- `reporting.py`：只使用本工程已执行模块的中文综合报告。

离线启动：

```bat
start_steering_desktop.bat
```

启动脚本固定使用：

```text
E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe
```

依赖诊断：

```powershell
E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe scripts\d4\check_desktop_environment.py
```

诊断已通过，实际版本为 PySide6 6.10.0、PyQtGraph 0.13.7、pandas 3.0.5、
openpyxl 3.1.5、NumPy 2.4.6。原 Tkinter 入口保留。

## 3. 五个功能页面

### 3.1 机械—液压—控制联合仿真

- 可设置车速、外轮目标转角、摩擦系数、动态时长和六桥轴荷；
- 单工况调用 J1-R2 完整 22 状态动态仿真；
- 独立显示计算成功、液压跟踪达标、目标轨迹可行性；
- 液压跟踪状态直接复用 J1-R2 的 `TRACKING_PASS` 与
  `TRANSIENT_TRACKING_PASS`，不由界面另设阈值；
- 提供轮角动态、供油压力、十二轮结果；
- 3111 工况按钮明确标记为准稳态能力估计，而不是 3111 次完整动态积分。

### 3.2 任务载荷谱

- 支持 CSV/XLSX 导入、新建、空模板和 30 天示例；
- 支持表格编辑、添加、删除、复制、上下移动任务段；
- 显示总时长、30 天一致性、字段错误、高速大转角风险；
- 提供速度—时间和转角—时间图，保留任务顺序及段间动作。

### 3.3 部件退化预测

- 直接调用 D1 逐段预测和 D3 多模式/雨流接口；
- 显示 2 台齿轮泵、4 个转向阀、4 组等效液压缸；
- 覆盖泵内泄漏/机械损失、阀内泄漏/响应迟滞、缸内泄漏/摩擦增大六种模式；
- 提供模式曲线、部件参数、逐段损伤贡献及雨流等效载荷；
- 显著标记 `ENGINEERING_DESIGN_ASSUMPTION / PENDING_CLIENT_CALIBRATION`。

### 3.4 当前质量性能评估

- 直接调用 D2 `QualityAssessor`；
- 支持健康、轻度、中度、重度和自然检查点状态；
- 标准测试实际运行 22 状态动力学；
- 输出健康、亚健康、退化、危险四级和等级下降原因；
- 将液压跟踪误差与机械机构相对阿克曼理论的固有偏差分开显示。

### 3.5 剩余任务循环预测

- 直接调用 D3 正式寿命预测服务；
- 支持全新、D1 第 30 天、自定义 JSON 初态；
- 支持最大循环、快速/详细模式、Gamma 随机分析、样本数和种子；
- 正确解释 `FAILURE_REACHED`、`FAILURE_BRACKETED`、
  `NOT_REACHED_WITHIN_HORIZON`、`INDETERMINATE`；
- 示例结果显示剩余完整任务 130 次，第 131 次任务的 D07-S07 段检测到
  首次越限；界面明确标注这是段末检测时刻，不是段内精确失效瞬间；
- 随机结果明确标注为工程假设下的寿命分位区间，Monte Carlo 路径采用
  快速近似载荷推进，并非每条路径均执行完整 22 状态验证。

## 4. 后台执行、交互与数据隔离

- 耗时计算均通过 `QThread` 后台任务执行，实际验收期间窗口可切页和刷新；
- 同一时刻只允许一个计算任务，避免重复点击导致并发写入；
- 进度、当前阶段、耗时、失败信息和取消状态进入统一状态栏；
- 可安全取消任务在下一检查点停止；不可拆分的积分过程等待积分返回；
- 计算失败会清除相应页面的新完成标记，不将旧结果冒充新结果；
- 关闭窗口时申请取消并回收工作线程；
- 项目打开只恢复输入和历史结果路径，历史结果不会自动进入本次正式报告。

## 5. 工程保存与导出

已实现：

- 新建、打开、保存、另存为 `.d4project.json` 工程；
- 保存页面输入、任务配置、模型/配置/任务谱哈希、结果路径和完成模块；
- 当前表格导出 CSV/XLSX；
- 当前图表导出 PNG；
- 中文综合报告导出 Markdown；
- 实际窗口验收截图保存。

综合报告仅纳入本工程实际执行的模块，并明确列出未执行模块，不会用历史
示例 CSV 填充正式结果。

## 6. 实际 Windows GUI 验收

验收脚本：

```powershell
E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe scripts\d4\capture_gui_evidence.py
```

在 Windows 上启动实际可见的 Qt 主窗口，通过页面按钮和后台信号完成：

```text
启动 → 30天任务谱 → 联合动态仿真 → 部件退化 → 当前质量评估
     → 剩余寿命预测 → 项目保存 → XLSX/PNG/中文报告导出
```

测试硬件 CPU：Intel Core i5-14400。验收任务谱为
`data/degradation/task_spectrum_30day_example.csv`，最大寿命周期 240，
Monte Carlo 128 条路径，固定种子 20261013。实测结果：

- 稳定状态全流程墙钟时间：49.45 s；
- 寿命预测页面阶段（含页面切换/截图等待）：约 27.36 s；
- 同参数 D3 内核隔离实测：28.80 s；
- 联合动态仿真内核：约 4.4 s；
- 五个计算模块完成标记均为真；
- 窗口截图分辨率：1920 × 1009；
- 截图方法：`QScreen.grabWindow(MainWindow.winId)`，不是生成图片。

性能复测中，在全仓 16 分钟回归刚结束时立即运行曾出现一次 86.40 s 的负载
相关离群值；系统恢复后同一流程回到 49.45 s。软件记录真实耗时，不隐去该波动。

截图证据：

- `outputs/desktop/acceptance/screenshots/01_joint_simulation.png`
- `outputs/desktop/acceptance/screenshots/02_task_spectrum.png`
- `outputs/desktop/acceptance/screenshots/03_degradation_prediction.png`
- `outputs/desktop/acceptance/screenshots/04_quality_assessment.png`
- `outputs/desktop/acceptance/screenshots/05_rul_prediction_result.png`

自动化验收记录：`outputs/desktop/acceptance/gui_acceptance.json`。

说明：尝试使用通用 Windows 计算机控制运行时采集补充证据时，该运行时因
本机 Node 路径缺失返回 `os error 3`。因此采用真实 Qt 可见窗口、Qt 屏幕 API
和自动化业务信号完成验收；截图仍来自实际运行软件。

## 7. 测试与回归

D4 专项测试：

```text
10 passed
```

覆盖五页导航、30 天任务谱、非法输入、中文路径 CSV/XLSX、工程保存/打开、
未执行模块保护、后台响应、安全取消和健康配置哈希不变。

D1/D2/D3、J1-R2 演示层和工程液压专项回归：

```text
125 passed, 2 skipped
```

全仓回归（约 15 分 59 秒）：

```text
616 passed, 2 skipped
1 failed + 1 teardown error（同一个既有测试的临时目录 Windows ACL 拒绝写入）
```

唯一未通过项为
`tests/physics/test_mechanical_demo_interactive.py::test_saved_json_schema`，失败发生在
写入 `outputs/test_tmp/<TemporaryDirectory>/demo.json` 前，异常为 `PermissionError:
WinError 5`；随后清理同一目录再次触发同一 ACL 错误。它不是数值断言、模型回归
或 D4 功能失败。两次申请非沙箱单测复跑分别因自动审批超时和审批服务容量不足
而未执行，故不将其虚报为通过。跳过项为既有条件性测试。

## 8. 健康基线和可追溯性

- 当前 Git HEAD：`4c4a6800431374920ea2c219aa8d8f5a396c8ab7`；
- 健康参数在 GUI 启动和预测前后哈希不变；
- 项目文件和报告记录机械/液压模型、健康配置、D1/D2/D3 配置和任务谱哈希；
- 所有退化率、硬失效阈值、质量阈值和随机分布继续标记为工程设计假设，
  待甲方试验标定。

## 9. 软件封装状态

已提供 `scripts/d4/build_pyinstaller.ps1` 可复现打包脚本和固定依赖清单。
本轮未宣称形成已验证的独立 EXE：当前环境未安装 PyInstaller，也未在另一台
目标 Windows 电脑完成独立运行验证。当前正式交付形态为指定 `steering_sim`
环境下的离线启动脚本。

## 10. 已知限制与后续标定事项

- 当前寿命尺度和随机分布没有甲方退化试验标定，不能视为实测寿命；
- D3 首次越限定位精度为任务段末，段内精确失效时刻需新增独立求解能力；
- Monte Carlo 是快速路径推进，不是 128 次完整 22 状态仿真；
- 3111 批量功能是准稳态能力估计；
- PyInstaller 独立程序尚未形成和跨机器验证；
- 软件未依赖网络、云服务或 Amesim，未进入新一轮算法研究。

D4 至此停止。
