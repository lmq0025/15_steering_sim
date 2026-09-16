# Mechanical Baseline v0.1

MECHANICAL BASELINE v0.1 — NOT CUSTOMER CALIBRATED

## 冻结范围

- R02-B：CUSTOMER 硬点、参考构型、闭链运动学。
- R02-C1：可选的约化机械动力学核心；工程运行仍需真实质量参数。
- R02-D：正式 actuator-position -> wheel-angle 接口、位置转换、标定接口。
- R02-E：整车几何协调层、PUBLIC / CUSTOMER_HINT preset。
- R02-E.1：中文交互、CLI、JSON/CSV 保存、复用绘图。

广义坐标固定为 q_front、q3、q4、q5、q6，共五维。
它们是相应两侧主摆臂相对于 CUSTOMER q=0 构型角增量的平均值。
Axle1/2 联动且共用 q_front；二桥没有独立执行器输入。

## 人工试车

验证 steering_sim 环境后运行：

    & "$env:CONDA_PREFIX\python.exe" examples/run_mechanical_demo_interactive.py
    & "$env:CONDA_PREFIX\python.exe" examples/run_mechanical_demo_interactive.py --demo
    & "$env:CONDA_PREFIX\python.exe" examples/run_mechanical_demo_interactive.py --preset customer-hint --axle1-deg 1.5 --direction right --plot

无参数进入中文交互；回车默认 customer-hint、1.5°、左。
--demo 固定采用 customer-hint、1.5°、左转并保存图。
左右转映射仅在展示入口定义：左=+Y/正角，右=-Y/负角。

## 输出契约

实际轮角来自协调器内部完成的 R02-D actuator-position round trip。
六桥实际平均角是对应 POS_Y/NEG_Y 轮角的算术平均。
9 个执行器量为前桥组 mapped position 加三至六桥 A/B 的8个
stroke_from_reference 位置量，以 mm 显示。
这些后桥数值沿用 R02-D scale、zero_offset、stroke_sign 约定，
不能等同于未经转换的原始传感器读数或统一符号的缸长变化。
前桥 mapped position 基于未标定映射，不是已知真实前桥缸行程。

JSON 保存用户输入、带符号指令、实际/目标轮角、q、ICR、
逐桥诊断、机械残差，以及配置 schema version/SHA256 和几何摘要。
CSV 一桥一行，二桥执行器字段为空。

## 当前物理边界

±0.08 rad 只是 numerical verification interval，真实机械限位未知。
feasible=True 表示继承的 R02-E 数值可行定义，并不证明理想目标已达到。
Axle5/6 的 baseline_mismatch 必须保留；geometry_limited 表示数值边界受限。
PUBLIC 采用三/四桥间 ICR；CUSTOMER_HINT 采用二/三桥间 ICR，
后者来自用户回忆，等待甲方正式确认。
前桥映射、传感器零点/比例、协调参数、轮角零位仍需客户数据标定。

## 后续开发边界

本轮完成后封存机械核心。后续液压子模块独立开发，
机械—液压真实耦合应另开轮次，不通过演示入口改变冻结机械算法。
真实精度验收、真实机械限位和客户车辆预测均未在此版本宣称完成。
