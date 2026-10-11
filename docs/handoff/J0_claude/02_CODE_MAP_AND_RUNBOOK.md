# 代码地图与运行手册

## 1. 固定环境

```text
项目根目录  E:\15_project
Python      E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe
版本        Python 3.11.16
```

本机核对版本：NumPy 2.4.6、SciPy 1.17.1、pandas 3.0.5、openpyxl 3.1.5、Matplotlib 3.11.2、pytest 9.1.1。声明依赖以 `pyproject.toml` 为准，不要自动安装或升级。`steering_sim` 当前从 `E:\15_project\src\steering_sim` 导入。

PowerShell 始终从项目根目录运行，并使用绝对 Python 路径；不要依赖默认 `python` 或 `conda activate`。

## 2. 正式液压代码

| 路径 | 用途 |
|---|---|
| `src/steering_sim/hydraulics_lumped/model.py` | `SystemInputs`、16 状态 RHS、`LumpedHydraulicSystem` |
| `src/steering_sim/hydraulics_lumped/interface.py` | J0 推荐使用的 `HydraulicInput/Output` 和 `evaluate_hydraulic` |
| `src/steering_sim/hydraulics_lumped/parameters.py` | 四通道别名、泵阀缸参数、供油组 |
| `src/steering_sim/hydraulics_lumped/actuator.py` | 双腔连续性、力、位移符号和负载力 |
| `src/steering_sim/hydraulics_lumped/simulation.py` | `simulate_rk4`、`simulate_scipy` |
| `scripts/hydraulics/run_phase_l1_fast.py` | L1-Fast 验收/制品入口；会写输出并跑 100 s，J0 日常不要运行 |
| `tests/hydraulics_lumped/test_l1_fast_regulated_supply.py` | 快速核心验收 |
| `docs/hydraulics/fast_hydraulic_io.md` | 已有 SI I/O 说明 |
| `docs/hydraulics/phase_L1_Fast_results.json` | 已保存运行时间和 230-test 结果 |

实际构造和单步入口：

```python
from steering_sim.hydraulics_lumped import (
    HydraulicInput, LumpedHydraulicSystem, evaluate_hydraulic
)

model = LumpedHydraulicSystem.fast_engineering()
dx, output = evaluate_hydraulic(model, t, state, hydraulic_input)
```

`HydraulicInput`：

- `valve_commands`: 4 个无量纲主阀命令；顺序为 `dirvalve_6, dirvalve_1, dirvalve_8, dirvalve_11`。
- `pump_speeds_rad_s`: 4 个泵转速；别名为 `pump01, pump01_1, pump01_2, pump01_3`。
- `external_load_forces_n`: 4 个负载力 N，正值在执行器方程中抵抗正 x 运动。
- `redundant_valve_commands`: 可选阀别名映射，后三组冗余阀为 `dirvalve_2, dirvalve_9, dirvalve_12`。
- `prescribed_motion_by_alias`: 可选测试边界，值为 `(x[m],v[m/s],a[m/s²])`；闭环 J0 不应同时把同一个 x 当作自由积分和 prescribed motion。

`HydraulicOutput.channels` 每通道输出 `position_m, velocity_m_s, hydraulic_force_n, pressure_a_pa_g, pressure_b_pa_g, flow_a_m3_s, flow_b_m3_s`。系统还输出两组供油压力、容量不足标志和流量裕量。

状态顺序为每通道 `[pA, pB, x, v]`。`initial_state()` 默认压力和 x 都为 0；但 L1-Fast 是预建压边界，验收脚本使用各通道回油轨压力初始化 pA/pB，并用静态平衡负载抵消初始液压力。J0 必须显式采用一致的预建压初始化，不能误把默认零压启动当作已验证工况。

四通道实际参数概要：

| 索引 | 通道 | 执行器别名 | 主/冗余阀 | 泵 | 总行程 | 初始 x |
|---:|---|---|---|---|---:|---:|
| 0 | `channel_front` | `actuator002` | `dirvalve_6` | `pump01+pump01_1` | 0.300 m | 0 m |
| 1 | `channel_rear_1` | `actuator001` | `dirvalve_1/2` | `pump01_2+pump01_3` | 0.130 m | 0 m |
| 2 | `channel_rear_2` | `actuator001_1` | `dirvalve_8/9` | `pump01_2+pump01_3` | 0.195 m | 0 m |
| 3 | `channel_rear_3` | `actuator001_2` | `dirvalve_11/12` | `pump01_2+pump01_3` | 0.265 m | 0 m |

液压最小只读冒烟：

```powershell
& 'E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe' -c "from steering_sim.hydraulics_lumped import LumpedHydraulicSystem; m=LumpedHydraulicSystem.fast_engineering(); print(m.state_count,[c.name for c in m.channels])"
```

核心专项测试（本次实跑 8 passed）：

```powershell
& 'E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe' -m pytest -q tests/hydraulics_lumped/test_l1_fast_regulated_supply.py --disable-warnings
```

## 3. 正式机械代码

| 路径 | 用途 |
|---|---|
| `mechanics_ackermann_v2/model.py` | `PhaseM1Model`、理想/闭链/地面负载结果类 |
| `mechanics_ackermann_v2/batch.py` | CSV/XLSX 工况和批量输出 |
| `mechanics_ackermann_v2/config.json` | q 数值包络、地面假设、前缸假设、默认扫描 |
| `mechanics_ackermann_v2/run_phase_m1.py` | 完整 M1 制品入口；J0 不需重跑 |
| `src/steering_sim/mechanics/kinematics.py` | 实际复用的 R02B `SixAxleSteeringKinematics` 闭链求解器 |
| `src/steering_sim/mechanics/input_spec.py` | mm→m 一次转换和硬点/杆/缸几何构建 |
| `mechanical_model_input_spec_v1.0.yaml` | 冻结甲方坐标和拓扑（JSON-compatible YAML） |
| `tests/mechanics_ackermann_v2/test_phase_m1.py` | M1 专项测试 |

实际入口：

```python
from mechanics_ackermann_v2.model import CaseInput, PhaseM1Model

model = PhaseM1Model(
    r"E:\15_project\mechanical_model_input_spec_v1.0.yaml",
    r"E:\15_project\mechanics_ackermann_v2\config.json",
)
geometry = model.solve_geometry(first_axle_outer_angle_deg)
loaded = model.solve_loaded_case(case, geometry)  # M1 静态评估；J0 闭环勿重复使用其柔度角
```

`GeometryResult` 含 12 轮理想角、理论角、几何误差，四个 q、轮角雅可比、七缸相对/绝对行程、闭链残差和可达性。`LoadedCaseResult` 另含 M1 静态受载角、侧偏角、需求/可提供侧向力、道路力矩、广义道路力矩和适用性标志。

M1 当前只有明确的 `q → 轮角/七缸行程` 路径；没有供 J0 直接调用的公开 `液压 x → q` 逆接口。不要把私有方法名称当作稳定 API。

机械最小运行（只解直行，约需建立查找表）：

```powershell
& 'E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe' -c "from mechanics_ackermann_v2.model import PhaseM1Model; m=PhaseM1Model(r'E:\15_project\mechanical_model_input_spec_v1.0.yaml',r'E:\15_project\mechanics_ackermann_v2\config.json'); print(m.solve_geometry(0).theoretical_angle_deg)"
```

专项测试（本次实跑 22 passed）：

```powershell
& 'E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe' -m pytest -q tests/mechanics_ackermann_v2/test_phase_m1.py
```

完整 M1 批量命令如下，但会重写 M1 输出和交付包，J0 日常不要运行：

```powershell
& 'E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe' -m mechanics_ackermann_v2.run_phase_m1
```

## 4. 控制和联合层现状

- `src/steering_sim/control/pid.py` 已有 `PIDController`：离散 PID、命令限幅、条件积分抗饱和。构造器是一组标量增益；J0 可每通道实例化一个控制器，增益必须外部配置。
- `src/steering_sim/control/base.py` 定义 `Measurement/Reference/Command`。
- `src/steering_sim/coupling/interfaces.py` 只有通用交换记录和功率平衡类型，没有可运行的 J0 联合求解器。
- 当前不存在已完成的 J0 入口。下一 Agent 应新建隔离的联合层、配置、脚本和测试，不要把联合逻辑塞入液压本构文件。

## 5. 历史资料与禁止误用

- 旧 109-state 模型：`src/steering_sim/hydraulics`，相关 `scripts/hydraulics/run_python_phase2*.py`；仅证据库。
- 旧机械报告：`docs/review/R02B_handoff.md`、`R02D_handoff.md`、`R02E_handoff.md`；其中活动 q3 与 M1 冲突。
- 甲方原始资料：`source_materials`；不要改写。
- Amesim：`qh1_1.ame`、`qh1_1_MCP_AUDIT.ame`；不要修改或保存覆盖。

## 6. 测试说明

本轮没有重跑耗时完整套件。`230 passed in 111.47 s` 是 `docs/hydraulics/phase_L1_Fast_results.json` 中保存的最近全仓结果；当前小范围实跑结果是 M1 22 passed、L1-Fast 核心 8 passed。pytest 因工作区权限无法创建 `.pytest_cache`，产生一个缓存警告，不影响测试通过结果。
