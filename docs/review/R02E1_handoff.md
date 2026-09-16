# R02-E.1 人工试车入口交接

## 环境、Git 与变更边界

Python executable：
E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe

开始前已执行 sys.executable 验证。所有运行、测试均使用
PowerShell 的 & "$env:CONDA_PREFIX\python.exe"，未安装依赖或改系统 PATH。
R02-E 工作区 clean 后以非 squash 合并进入 main，再建立
r02-mechanical-demo-entry。该交付分支等待人工验收，不合并回 main。

本次新增：

- examples/run_mechanical_demo_interactive.py
- tests/physics/test_mechanical_demo_interactive.py
- docs/mechanics/MECHANICAL_BASELINE_V0_1.md
- 本交接文档

唯一既有实现变更：examples/run_vehicle_steering_demo.py 的
plot_vehicle_demo 增加可选 title 参数，原调用的默认标题不变。
src 中所有机械核心、CUSTOMER 几何、5-DOF、两套 baseline 配置均未修改。

## 使用方式

    & "$env:CONDA_PREFIX\python.exe" examples/run_mechanical_demo_interactive.py
    & "$env:CONDA_PREFIX\python.exe" examples/run_mechanical_demo_interactive.py --demo
    & "$env:CONDA_PREFIX\python.exe" examples/run_mechanical_demo_interactive.py --preset customer-hint --axle1-deg 1.5 --direction right --save-json outputs/manual_demo/right.json --save-csv outputs/manual_demo/right.csv --plot

无参数提供中文提示，默认 customer-hint / 1.5 / 左。输入支持1～4或模式名称，
角度允许数字后带°，非法或非有限数会提示重新输入。
CLI 模式支持 customer-hint、public、crab、front-only。
--demo 固定选择推荐案例并绘图，显式保存路径仍有效。
默认保存按本地时间戳命名；同秒重复运行添加后缀以保留既有结果。
显式 --save-json/--save-csv 路径采用用户指定的文件名，可覆盖同名文件。

## 符号、位置与角度定义

入口集中定义 DISPLAY_LEFT_TURN_SIGN = +1。
左转=+Y/正目标角，右转=负目标角；核心仍只接受带符号的目标角。
终端明确打印显示约定，后续不同客户符号通过数据/显示映射适配。

程序调用既有 build_coordinator 和 coordinate，实际轮角来自 coordinator
内部调用 MechanicalSteeringIOModel.solve_from_actuators 的结果。
六桥平均角为对应 POS_Y/NEG_Y 实际轮角均值；12轮按桥号及 POS_Y/NEG_Y 输出。
9个位置量为 Front mapped position 和 Axle3～6 A/B stroke，单位mm。
二桥无独立执行器字段；CSV第二桥位置字段为空。
前桥映射未标定，后桥行程继承 R02-D 的符号/比例/零位转换约定。

## 推荐案例实际结果

MECHANICAL BASELINE v0.1 / NOT CUSTOMER CALIBRATED。
customer-hint，左转，目标 +1.500°。

- feasible=True；最大轮角目标偏差 3.374371°。
- 六桥实际平均角 [deg]：
  [+1.326062, +0.954065, -0.712257, -1.227275, -0.184564, -1.280119]。
- ICR=(-4.940000, +189.038107) m。
- Axle5/6 均为 baseline_mismatch，RMS残差分别为 2.538335° / 2.476418°。
- 前桥映射位置 [mm]：-26.079597。
- Axle3 A/B [mm]：+0.964619 / +1.010071。
- Axle4 A/B [mm]：+6.991995 / +7.145214。
- Axle5 A/B [mm]：-15.212385 / -14.955531。
- Axle6 A/B [mm]：+18.284415 / +18.608174。

产物：

- outputs/manual_demo/mechanical_demo_20260916_155717.json
- outputs/manual_demo/mechanical_demo_20260916_155717.csv
- outputs/manual_demo/mechanical_demo_20260916_155717.png

JSON 包含输入、带符号指令、模式、理想/实际轮角与桥均角、9位置、q、
ICR、可行性、逐桥及R02-D残差/状态、配置版本与SHA256、几何SHA256。
CSV一桥一行。结果不属于客户真实精度验证。
PNG复用原R02-E绘图，标题含版本和未标定声明。文件已生成；
本次图像查看工具受到 Windows sandbox helper 权限错误影响，未完成目视验图。

## 不可行处理与继承限制

feasible=False 时给出中文原因、largest_feasible_scale 与建议展示角。
该建议基于继承的 R02-E 数值可行定义，仍可存在 baseline mismatch。
±0.08 rad 仅为 numerical verification interval；并非客户机械极限。
推荐案例 feasible=True 不代表每个轮子都达到理想协调目标。
Axle5 的 POS_Y/NEG_Y 可以出现异号，12轮表和详细JSON保留这一事实。
没有有效几何解、非法输入或文件错误时，入口给中文提示并返回非零退出码。

## 测试

    & "$env:CONDA_PREFIX\python.exe" -m pytest -q

最终结果：62 passed in 84.91s (0:01:24)。

新增9项：左/右符号、1.5°正式链往返、9位置、无二桥执行器、
不可行中文提示、JSON/CSV保存契约、交互默认值及非法输入。
首次全量61项通过，1项因系统pytest临时目录访问权限失败；
随后保存测试改为使用 outputs/test_tmp 下自动清理的独立临时目录。

## 机械封箱与提交

冻结范围见 docs/mechanics/MECHANICAL_BASELINE_V0_1.md：
R02-B + R02-C1（可选动力学）+ R02-D + R02-E + R02-E.1。
后续液压模块独立开发，真正机械—液压耦合另开轮次。

Branch：r02-mechanical-demo-entry。
Commit：包含本交接文件的交付提交；最终聊天报告完整hash，
可用 git log -1 --format=%H -- docs/review/R02E1_handoff.md 定位。
