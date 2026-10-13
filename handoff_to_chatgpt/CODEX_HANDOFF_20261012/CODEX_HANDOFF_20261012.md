# CODEX 交接文档 — 15所电液转向系统

**项目名称**：《电液转向系统质量性能评估方法》
**交接日期**：2026-10-12
**交接范围**：代码与资料交接。**本轮不修改任何仿真模型、算法、参数或界面，不开发退化预测。**

> 本文件里的每一个类名、方法名、字段名、列名都取自**当前源码**。
> 机器可读的完整接口清单见同目录 `codex_interface_map.json`（由
> `scripts/handoff/build_handoff_pack.py` 用 `ast` 从活代码提取），
> 如与本文件的叙述冲突，**以那份 JSON 为准**。

---

## 0. 交接元信息

| 项 | 值 |
|---|---|
| 工作区 | `E:\15_project` |
| Git 分支 | `r02-mechanical-demo-entry` |
| Git HEAD | `4c4a6800431374920ea2c219aa8d8f5a396c8ab7`（提交信息：`健康模型完成_20261012`，由**用户**提交） |
| 工作区状态 | 仅 `tools/Simcenter-Amesim-MCP` 显示为修改（该子模块的历史状态，不是本轮产物）；其余干净 |
| 唯一 Python | `E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe`（Python 3.11.16） |
| 已装依赖 | numpy 2.4.6、scipy 1.17.1、pandas 3.0.5、openpyxl 3.1.5、matplotlib 3.11.2、Pillow、pytest |
| **未装依赖** | **PySide6（MISSING）**、PyQt5（MISSING） |
| 正式机械模型 | `ENGINEERING_STEERING_MODEL`（唯一） |
| 正式液压模型 | `ENGINEERING_HYDRAULIC_V1`（唯一） |
| 唯一客户原始数据 | `mechanical_model_input_spec_v1.0.yaml`（32099 B，**不得修改**） |
| 上一阶段交付 | `handoff_to_chatgpt/phase_J1_R2.zip`（sha256 `b9879ede…367fbdd`，81 个成员） |
| 本阶段交付 | `handoff_to_chatgpt/CODEX_HANDOFF_20261012.zip` |

**本轮未做任何 `git commit / push / reset / clean / stash`，未修改生产代码。**

---

## 1. 当前代码架构

### 1.1 分层总览

```
┌─ 界面层 ────────────────────────────────────────────────────────────┐
│ src/steering_sim/demo/ui.py          Tkinter 中文界面（唯一 UI 文件）  │
│ src/steering_sim/demo/cli.py         命令行入口（assess/run/replay/…） │
└───────────────┬─────────────────────────────────────────────────────┘
                │ 只调用 DemoService / demo.batch / demo.scenario
┌─ 服务层 ──────▼─────────────────────────────────────────────────────┐
│ src/steering_sim/demo/service.py     DemoService / DemoResult        │
│ src/steering_sim/demo/scenario.py    DemoScenario / 预设 / 范围校验    │
│ src/steering_sim/demo/batch.py       CSV/XLSX 导入导出 + 准稳态能力预测 │
│ src/steering_sim/demo/assessment.py  运行前检查 + 运行后一致性         │
│ src/steering_sim/demo/plots.py       六张结果图 + 十二轮数值表          │
└───────────────┬─────────────────────────────────────────────────────┘
                │
┌─ 联合仿真层 ──▼─────────────────────────────────────────────────────┐
│ src/steering_sim/j0_coupling/runner.py     J0Runner  (多速率闭环积分) │
│ src/steering_sim/j0_coupling/config.py     J0Config / J0CaseConfig    │
│ src/steering_sim/j0_coupling/geometry.py   J0GeometryAdapter          │
│ src/steering_sim/j0_coupling/road_load.py  道路载荷 / 附着 / 实际曲率  │
│ src/steering_sim/j0_coupling/authority.py  (仅 L1-Fast 历史路径)       │
│ src/steering_sim/j0_coupling/mechanism.py  build_mechanism_model 工厂 │
└──────┬──────────────────────────────┬───────────────────────────────┘
       │                              │
┌──────▼──────────────┐   ┌───────────▼───────────────────────────────┐
│ 机械模型             │   │ 液压模型                                   │
│ engineering/model.py │   │ hydraulics_engineering/model.py            │
│ EngineeringSteering  │   │ EngineeringHydraulicSystem                 │
│ Model                │   │ parameters.py  EngineHydraulicParameters    │
│ engineering/         │   │ authority.py   极性/力窗口探针              │
│ mechanism.py         │   └───────────────────────────────────────────┘
│ EngineeringMechanism │
└──────────────────────┘
       ▲
       │ 控制
┌──────┴──────────────────────────────────────────────────────────────┐
│ src/steering_sim/control/base.py   Controller / Measurement / …      │
│ src/steering_sim/control/pid.py    PIDController / PIDDiagnostics    │
└─────────────────────────────────────────────────────────────────────┘
```

**数据流（一次工况）**：

```
目标一桥外侧角 → EngineeringSteeringModel.solve_geometry()  → 目标机构坐标 q_ref
q_ref → J0GeometryAdapter.seven_cylinder_strokes()           → 四通道目标行程 x_ref
x_ref → S 曲线指令 + 速度前馈 + PI                            → 阀命令 u
u, x, v, pA, pB → EngineeringHydraulicSystem.evaluate()       → 状态导数（RK4）
x_actual → J0GeometryAdapter.q_from_strokes()                 → 实际 q → 十二轮实际角
实际 q → road_load()                                          → 道路负载力 → 反馈回液压
```

### 1.2 正式机械模型

**文件**：`src/steering_sim/engineering/model.py`
**入口类**：`EngineeringSteeringModel`

```python
EngineeringSteeringModel(geometry_path, config_path, design_path=None)
```

| 用途 | 方法 / 属性 |
|---|---|
| 机构正解（广义坐标 → 十二轮角） | `mechanism_state(q_values) -> EngineeringState` |
| 机构反解（行程 → 广义坐标） | `J0GeometryAdapter.q_from_strokes(x_by_channel)`（见 1.4） |
| 目标角拟合（目标角 → 机构坐标） | `solve_geometry(target_outer_angle_deg)` |
| 理想阿克曼解 | `ideal_ackermann(target_outer_angle_deg)` |
| 机构坐标包络 | `q_envelopes`（`{dof: (low, high)}`，rad） |
| 目标曲率 | `curvature_1pm(target_outer_angle_deg)` |
| 受载静态估计（**J0 起不用于闭环**） | `solve_loaded_case(case, geometry=None)` |

**文件**：`src/steering_sim/engineering/mechanism.py`
**入口类**：`EngineeringMechanism(reference, design)`

| 方法 | 说明 |
|---|---|
| `solve_swing(key, swing_angle_rad)` | 单组闭式正解（摆臂角 → 齿条 → 十二轮角），返回 `GroupState` |
| `solve_continuous(key, q_rad, step_rad=…)` | **装配分支连续跟踪**：从上一步小步走过去，避免跳分支 |
| `solve(q_values)` | 四组一起解，返回 `{key: GroupState}` |
| `rack_jacobian(key, swing_angle_rad, delta=…)` | 齿条传动比 |
| `reset_group(key, swing_angle_rad)` / `reset()` | 复位装配分支状态 |

**几何数据**：`configs/j1/engineering_mechanism.json`（新设计尺寸，`ENGINEERING_DESIGN_ASSUMPTION`）
用 `load_design(path) -> EngineeringDesign` / `save_design(design, path)` 读写。
结构：`EngineeringDesign.groups: Mapping[str, GroupDesign]`，每个 `GroupDesign` 有
`key / axles / driven_axle / rack_drive_point / racks / sides / relay / notes`，
每个 `SideDesign` 有 `arm_tip / swing_pickup / rack_end`。

**模型配置**：`configs/j1/engineering_config.json`（用 `load_config(path)` 读）
关键键：`geometry.q_envelopes_rad`、`geometry.third_axle_locked`、
`geometry.third_axle_point20_mm`（客户坐标校验）、`ground_load.*`、
`front_cylinder_interface.stroke_per_q_mm_per_rad`（= 250，即 x = 0.25·q_front）。

**四组自由度 ↔ 十二轮映射**（权威来源 `codex_interface_map.json`）

| 通道 | DOF | 驱动桥 | 随动桥 | 三桥 |
|---|---|---|---|---|
| `channel_front` | `q_front` | 1 | 2（中间拉杆耦合） | — |
| `channel_rear_1` | `q4` | 4 | — | — |
| `channel_rear_2` | `q5` | 5 | — | — |
| `channel_rear_3` | `q6` | 6 | — | — |
| （锁止） | `q3` 不存在 | 3 桥恒为 0° | | |

方向约定：一、二桥与目标同向；**四、五、六桥反向**；三桥恒 0°。
`q_envelopes_rad`（弧度，对称；`model.q_envelopes` 直接取）：
`q_front ±0.78723`（±45.105°）、`q4 ±0.36399`（±20.855°）、
`q5 ±0.30473`（±17.460°）、`q6 ±0.52482`（±30.070°）。
**这是数值连续延拓得到的可解区间，不是甲方机械限位。**

### 1.3 正式液压模型

**文件**：`src/steering_sim/hydraulics_engineering/model.py`
**入口类**：`EngineeringHydraulicSystem(parameters)`

**状态向量（22 维）**——`CHANNEL_STATE_SIZE = 5`：

| 通道 | 偏移 | 状态 |
|---|---|---|
| `channel_front` | 0 | `[pA, pB, x, v, u_valve_spool]` |
| `channel_rear_1` | 5 | 同上 |
| `channel_rear_2` | 10 | 同上 |
| `channel_rear_3` | 15 | 同上 |
| 供油轨 `front` | 20 | `[p_supply]` |
| 供油轨 `rear` | 21 | `[p_supply]` |

用 `state_layout(parameters) -> dict[str, int]` 取布局，不要手写偏移。

| 方法 | 说明 |
|---|---|
| `neutral_state()` | 零位健康初值（两腔预充压相等；供压取泵/溢流平衡点，**t=0 是真正的平衡点**） |
| `working_point()` | 兼容 J0 命名，返回 `(neutral_state(), (0,0,0,0))` |
| `pump_speeds_rad_s` | 四通道对应的泵转速（**当前取自参数常量**） |
| `evaluate(t, state, inputs)` | 返回 `(d_state, EngineeringOutput)`；`inputs` 只需鸭子类型地提供 `valve_commands` 与 `external_load_forces_n` |

模块级函数：`evaluate_hydraulic_engineering(system, t, state, inputs)`（与
`hydraulics_lumped.evaluate_hydraulic` **同签名**，runner 通过 `self._evaluate` 切换）。

**两条共用供油轨**（`SUPPLY_ORDER = ("front", "rear")`）

| 供油轨 | 挂载通道 | 泵排量 `displacement_m3_per_rad` | 额定转速 `nominal_speed_rad_s` | 溢流 `relief_pressure_pa` | 蓄能器 `plenum_volume_m3` |
|---|---|---|---|---|---|
| `front` | `channel_front` | 2.2652148e-06 | 157.08 (=1500 r/min) | 21.0e6 | 2.0e-3 |
| `rear` | `channel_rear_1/2/3` | 3.6707659e-06 | 157.08 | 21.0e6 | 2.0e-3 |

**流量分配关系**（源码 `model.py` 的供油轨循环）：

```
节流口软流量（model.py::_soft_orifice）
    F(Δp, A) = Cd · A · √(2/ρ) · Δp / √(√(Δp² + ε²))          ε = 1e5 Pa
    （Δp 大时退化为标准薄壁孔口 Cd·A·√(2|Δp|/ρ)·sign(Δp)；Δp→0 时线性、导数有界）

每通道从供油轨的取用流量
    supply_flow = F(ps − pA, A_max·u⁺) + F(ps − pB, A_max·u⁻)      u⁺ = max(u,0), u⁻ = max(−u,0)

供油轨方程（逐轨一个状态 ps）
    d(ps)/dt = (β_plenum / V_plenum) · (Q_pump − Q_relief − Σ supply_flow)
    Q_pump   = displacement · nominal_speed · pump_volumetric_efficiency
               − pump_internal_leakage_m3_s_per_pa · ps          （再 max(0, ·)）
    Q_relief = max(0, F(ps − relief_pressure_pa · supply_pressure_scale, relief_area))
```

油液：`fluid_bulk_modulus_pa = 1.0e9`、`fluid_density_kg_m3 = 850`、
`tank_pressure_pa = 5.0e5`、`precharge_pressure_pa = 2.0e6`（两腔相等 ⇒ 零位无净力）。
前组缸示例：`area_a_m2 = area_b_m2 = 3.1172453e-3`、`stroke_m = 0.393615`、
`stroke_offset_m = 0.0`、`dead_volume_m3 = 1.9631912e-4`、`mass_kg = 440.46`、
`viscous_damping_n_s_per_m = 4361.96`、`coulomb_friction_n = 622.91`、
`end_stop_stiffness_n_per_m = 1.79989290e8`、`end_stop_damping_n_s_per_m = 2.180982e5`；
前组阀：`maximum_area_m2 = 8.2660775e-6`、`discharge_coefficient = 0.62`、
`lag_time_s = 0.002`、`deadband = 0.0`、`velocity_per_unit_command_m_s = 0.141541`。

即：**同一供油轨上的所有通道共享一个流量池**；需求超过泵能力时 `ps` 真实下跌，
不是无限流量。`EngineeringOutput.demand_flow_m3_s` / `pump_flow_m3_s` /
`pump_capacity_margin_m3_s` / `pump_capacity_insufficient` 逐轨给出。

**缸模型**：对称双出杆（`area_a_m2 == area_b_m2`），腔容积用**相对活塞中位**的位移
`xc = x − stroke_offset_m`：`V_A = dead + A·(half + xc)`、`V_B = dead + A·(half − xc)`；
`|xc| > half` 时启用缓冲限位（`end_stop_stiffness_n_per_m`、`end_stop_damping_n_s_per_m`）。
腔容积非正会抛 `EngineeringHydraulicError`，**不静默裁剪**。

**参数类**（`src/steering_sim/hydraulics_engineering/parameters.py`）

| 类 | 关键字段 |
|---|---|
| `CylinderParameters` | `area_a_m2` `area_b_m2` `stroke_m` `stroke_offset_m` `dead_volume_m3` `bore_mm` `mass_kg` `viscous_damping_n_s_per_m` `coulomb_friction_n` `end_stop_stiffness_n_per_m` `end_stop_damping_n_s_per_m` `mass_source`；属性 `half_stroke_m` `stroke_min_m` `stroke_max_m` `symmetric` |
| `ValveParameters` | `maximum_area_m2` `discharge_coefficient` `lag_time_s` `deadband` `velocity_per_unit_command_m_s` |
| `PumpParameters` | `displacement_m3_per_rad` `nominal_speed_rad_s` `relief_pressure_pa` `plenum_volume_m3` `bulk_modulus_pa` `relief_area_m2`；属性 `ideal_flow_m3_s` |
| `ChannelParameters` | `name` `dof` `cylinder` `valve` `supply` `polarity` `kp` `ki` `kd` `kff` `command_limit` `reference_peak_velocity_m_s` `notes` |
| `DegradationParameters` | 见 §3 |
| `EngineeringHydraulicParameters` | `schema_version` `tag` `fluid_bulk_modulus_pa` `fluid_density_kg_m3` `tank_pressure_pa` `precharge_pressure_pa` `orifice_pressure_regularisation_pa` `supplies` `channels` `degradation` `assumptions` `provenance` `notes`；属性 `supply_names` `channel_names`；方法 `channel(name)` `to_dict()` |

IO：`load_parameters(path)` / `save_parameters(parameters, path)` /
`parameters_from_dict(raw)` / `with_degradation(parameters, **updates)`。
参数文件 `configs/j1r2/engineering_hydraulics.json`（`schema_version = "J1R2.0"`）。

**作动能力探针**：`probe_engineering_authority(system, *, force_samples=…,
polarity_duration_s=…, settle_duration_s=…) -> tuple[EngineeringAuthority, ...]`
实测命令极性与静态力窗口；`assert_engineering_authority(...)` 在实测与配置矛盾时显式失败。

### 1.4 联合仿真层

**文件**：`src/steering_sim/j0_coupling/runner.py`，类 `J0Runner`

```python
J0Runner(config, geometry_model, *, probe_authority=True, mechanical_mode=None)
```

| 成员 | 说明 |
|---|---|
| `hydraulic_model` | `"ENGINEERING_HYDRAULIC_V1"` 或 `"L1_FAST"`（后者仅历史对照） |
| `hydraulic` | `EngineeringHydraulicSystem` 实例 |
| `engineering_parameters` | 本次装载的参数对象（**退化注入的落点**，见 §3.6） |
| `geometry` | `J0GeometryAdapter` |
| `state_stride` | 每通道状态个数（工程模型 = 5） |
| `neutral_commands` / `state0` / `speeds` | 零命令、零位状态、泵转速 |
| `authority_records` | 极性/力窗口实测记录（dict） |
| `reference_time(case) -> float` | 指令斜坡时间 = `max(0.4 s, |目标角| / 12 °/s)` |
| `channel_gains(name, override=None)` / `channel_limit(name)` | 增益取 `engineering_hydraulics.json`，**不散落硬编码** |
| `command_from_pid(position, pid_output)` | 极性 + 限幅映射 |
| `run_case(case, *, diagnostic_damping_n_s_per_m=0.0, gains=None, road_load_scale=1.0, on_progress=None, profile=None) -> J0CaseResult` | 真实多速率积分 |

时间步长（`configs/j0/j0_config.json`）：`dt_hydraulic_s = 0.0005`（0.5 ms，RK4）、
`dt_control_s = 0.01`（10 ms）、`sample_stride_hydraulic_steps = 4`（记录 2 ms）。
**采样步长已做收敛检查**（0.5 ms 与 0.25 ms 的末值行程差为 0）。

`J0CaseResult` 字段：`case` `samples: dict[str, np.ndarray]` `summary: dict`
`completed` `failure_time_s` `failure_reason` `diagnostic_damping_n_s_per_m`。

**行程 ↔ 机构坐标映射**：`src/steering_sim/j0_coupling/geometry.py`，类 `J0GeometryAdapter`

| 方法 | 说明 |
|---|---|
| `target(target_outer_angle_deg)` | → 模型的 `solve_geometry` 结果（含 `q_rad`、`theoretical_angle_deg`、`ideal_ackermann_angle_deg`） |
| `representative_stroke(dof, q_value)` / `stroke_jacobian(dof, q_value)` | 代表行程与其雅可比 `dx/dq` |
| `q_from_stroke(dof, x) -> (q, MappingStatus)` | 行程反解；**`MAPPING_AT_ENVELOPE_LIMIT` 只表示缸走到了机构包络端点（非致命，逐点计数）；`MAPPING_OUT_OF_ENVELOPE` / `MAPPING_SINGULAR` / `MAPPING_NON_MONOTONIC` 是停止条件** |
| `q_from_strokes(x_by_channel)` | 四通道一起反解 |
| `wheel_angles_deg(q_values)` | 十二轮角（表插值，快） |
| `exact_linkage(q_values) -> ExactLinkage` | 精确闭链复核（残差/条件数） |
| `seven_cylinder_strokes(q_values)` | 七只缸几何行程 |
| `table_quality()` | 每 DOF 的表质量（残差、单调性、雅可比下限） |

**控制**：`src/steering_sim/control/pid.py`

```python
PIDController(kp, ki=0.0, kd=0.0, limit=1.0)
step(measurement, reference, dt, *, feedforward=None) -> Command
```
`u = kp·e + ki·∫e + kd·ė + feedforward`，再限幅到 `±limit`。
`self.diagnostics: PIDDiagnostics` 逐周期给出 `unclipped_request` / `clipped_command` /
`at_limit` / `anti_windup_active` / `margin` —— **饱和统计必须用它，不能拿限幅后的命令再比限幅**。
速度前馈增益 `kff = 1 / ValveParameters.velocity_per_unit_command_m_s`，取自参数文件。

**道路载荷与附着**：`src/steering_sim/j0_coupling/road_load.py`

```python
road_load(adapter, q_values, *, speed_kmh, friction_coefficient, axle_mass_t,
          curvature_1pm, singular_threshold_m_per_rad,
          use_actual_curvature=True, target_curvature_1pm=None) -> RoadLoad
actual_curvature_1pm(angles_deg, centers) -> (curvature, x_icr, y_icr, residual)
```
* **目标曲率**只用于工况要求与附着可行性评价；
* **实际曲率**由当前**实际车轮转角**的十二条纯滚动方向线最小二乘求交（ICR）得到，
  用于承载与受载反馈 —— 绝不把目标轨迹当成已实现的运动；
* `|Fy| ≤ μ·Fz` 始终成立，超限只记录 `flags`（`ADHESION_INFEASIBLE` /
  `OUTSIDE_LINEAR_TIRE_RANGE`），**不中断积分**；只有 `LOAD_CONVERSION_SINGULAR`
  这类数值问题才停止。
* 广义力矩 → 缸力换算：`F_load = Q_road / (dx/dq)`（虚功），极性由映射决定，
  由 `F_load·ẋ = Q_road·q̇` 恒等式校验。

### 1.5 演示服务层与 IO

**文件**：`src/steering_sim/demo/service.py`，类 `DemoService`

```python
DemoService(config_path=…, spec_path=…, mech_config_path=…, redesign_config_path=…,
            engineering_config_path=…, engineering_design_path=…, output_dir=…,
            probe_authority=False, mechanical_mode=None, hydraulic_model=None)
```

| 方法 | 说明 |
|---|---|
| `assess(scenario) -> PreflightAssessment` | 运行前检查（不积分） |
| `run(scenario, *, progress=…, on_fraction=…, export=True) -> DemoResult` | **唯一的实时计算入口** |
| `replay_preset(key)` / `store_preset(key, result)` / `build_preset_cache(*)` | 预设回放（明确标 `PRESET_REPLAY`，不冒充实时仿真） |
| `export_csv(result, target)` / `write_report(result)` | 导出 |
| `set_mode(mode)` / `mode_label` / `is_redesign` | 历史机构对照（**界面已不提供入口**） |

`DemoResult` 字段：`scenario` `preflight` `samples` `summary` `consistency`
`figures` `csv_path` `report_path` `provenance`（`LIVE_RUN` / `PRESET_REPLAY`）
`provenance_note` `completed` `failure_reason` `duration_wall_s`。

**批量与 Excel/CSV IO**：`src/steering_sim/demo/batch.py`

| 函数 | 说明 |
|---|---|
| `build_context(adapter=None, parameters_path=None) -> BatchContext` | 一次性建好批量上下文（复用 `J0GeometryAdapter` 与 `engineering_hydraulics.json` 的**同一套能力边界**） |
| `estimate_case(context, scenario, axle_mass_t=None) -> dict` | 单工况**准稳态**能力预测 |
| `run_batch(context, scenarios, *, on_progress=None, should_stop=None)` | 批量（`should_stop` 支持界面取消） |
| `read_cases(path) -> list[DemoScenario]` | **CSV / XLSX 导入** |
| `write_csv(rows, path)` / `write_xlsx(rows, path)` / `write_template(path)` | 导出与模板 |
| `columns_of(rows)` | 列顺序 |

导入列约定：必需 `target_outer_angle_deg`、`speed_kmh`；可选
`friction_coefficient`、`duration_s`、`case_id`、`axle_mass_1_t` … `axle_mass_6_t`。
非法数值**显式抛错并带行号**，不静默跳过。

`estimate_case` 的算法（**有来源的准稳态预测，不是理想角表**）：沿指令构型路径
`q(s) = s·q_ref`（`PATH_STEPS = 24`）逐级求道路负载，用
`F_available = (relief_pressure_pa − tank_pressure_pa) · area_a_m2` 比对；
某通道需求首次超过可用推力就停在那里，该级就是它的预测行程与预测轮角。

### 1.6 启动、测试与打包命令

```bash
# 一键启动中文界面（BAT 内部调用 scripts/j0_demo/start_demo.py）
start_steering_demo.bat

# 单工况（命令行）
python -m steering_sim.demo.cli run --angle 30 --speed 10 --duration 3.75
python -m steering_sim.demo.cli assess --angle 30 --speed 10
python -m steering_sim.demo.cli checks --output outputs/j0_demo/demo_checks.json

# 全仓测试
python -m pytest -q

# 3111 批量
python scripts/j1r2/run_j1r2_batch.py
# 代表工况真实动态积分
python scripts/j1r2/run_j1r2_dynamic.py
```

脚本清单：`scripts/j1r2/`（`design_engineering_hydraulics.py`、
`retune_front_follower.py`、`run_j1r2_batch.py`、`run_j1r2_dynamic.py`、
`check_step_convergence.py`、`make_j1r2_figures.py`、`capture_ui_screenshot.py`、
`write_j1r2_report.py`、`finalize_status.py`、`package_phase_j1r2.py`）；
`scripts/j1/`（`build_engineering_config.py`、`check_gate1_geometry.py`）；
`scripts/handoff/`（本交接包）。

---

## 2. J1-R2 正式基线

权威数据：`docs/handoff/codex_handoff_baseline.json` 与
`handoff_to_chatgpt/phase_J1_R2.zip`。报告：`docs/integration/phase_J1_R2_report.md`。

### 2.1 机械（61 个目标角，`outputs/j1/gate1_summary.json`）

| 检查项 | 结果 |
|---|---|
| 车轮方向正确 | 61/61 |
| 同桥左右轮同向 | 61/61 |
| 左右转镜像 | 30/30 |
| 三桥恒为 0° | 61/61 |
| 一桥外侧轮跟随目标 | 最大误差 0.0001° |
| 相邻档最大角跳变 | 1.4504° |
| 后三桥对理想阿克曼最大 RMS | 1.8255° |
| 最大车轮转角 | 38.446° |
| 机构坐标随目标角单调 | 四组全部 true |

### 2.2 工程液压参数（`configs/j1r2/engineering_hydraulics.json`）

| 通道 | 缸径 [mm] | 全行程 [mm] | 中位偏置 [mm] | 折算质量 [kg] | 固有频率 [Hz] | 阀口面积 [mm²] | kp | ki | kff |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `channel_front` | 63.0 | 393.6 | 0.00 | 440 | 26.3 | 8.266 | 176.63 | 2207.85 | 7.065 |
| `channel_rear_1` | 63.0 | 163.4 | −2.15 | 1106 | 25.7 | 1.078 | 1354.07 | 16925.92 | 54.163 |
| `channel_rear_2` | 80.0 | 139.3 | −7.03 | 1790 | 27.8 | 5.315 | 442.91 | 5536.40 | 17.716 |
| `channel_rear_3` | 63.0 | 267.9 | −20.57 | 501 | 29.8 | 7.001 | 208.53 | 2606.64 | 8.341 |

| 通道 | 最不利需求推力 [N] | 溢流压力下可用推力 [N] | 静力裕度 | 峰值流量 [L/min] | ±30° 行程余量 [mm] |
|---|---:|---:|---:|---:|---|
| `channel_front` | 21562 | 63904 | 2.96× | 17.08 | −30° 44.6 / +30° 55.4 |
| `channel_rear_1` | 24733 | 63904 | 2.58× | 2.23 | −30° 64.0 / +30° 60.3 |
| `channel_rear_2` | 48624 | 103044 | 2.12× | 10.98 | −30° 16.0 / +30° 19.4 |
| `channel_rear_3` | 27557 | 63904 | 2.32× | 14.47 | −30° 263.5 / +30° 242.3 |

供油轨：`front` 泵 21.35 L/min、`rear` 泵 34.60 L/min，溢流 21.0 MPa，
四通道同时按设计速度动作时**各有 20% 余量**。选型判据：`F = M/(ds/dδ)`（虚功）、
安全系数 1.30、机械效率 0.90、最不利工况 = 0/5/10/20 km/h × ±30° × μ=0.8 × 11.5 t/轴。

### 2.3 3111 工况批算（`outputs/j1r2/j1r2_full_cases.csv` / `.xlsx`）

| 指标 | 值 |
|---|---|
| 计算方式 | `FAST_BATCH_ESTIMATE`（准稳态，**不做时间积分**） |
| 工况总数 | 3111（17 车速 × 61 目标角 × 3 摩擦系数） |
| 结构完整 | 3111 / 3111 |
| 求解异常 | 0 |
| 四通道作动能力 OK | 3111 / 3111（四个通道分别统计） |
| 综合状态 `OK` | 561 |
| 综合状态 `ACKERMANN_TARGET_MISMATCH` | 1580 |
| 综合状态 `VEHICLE_DYNAMIC_INFEASIBLE` | 970 |
| 耗时 | 26–29 s |

### 2.4 代表工况真实动态积分（18 个）

| 指标 | 值 |
|---|---|
| 数值完成 | 18 / 18 |
| 稳态跟踪达标 | 18 / 18 |
| 过渡段达标 | 18 / 18 |
| 目标轨迹物理不可行 | 3 / 18（60 km/h +20°、80 km/h ±30°） |
| 稳态误差最差 | 0.00102° |
| 过渡段峰值最差 | 0.2201° |
| 控制饱和比例最大 | 0.00% |
| 末段速度 RMS 最大 | ≈1.8e-5 m/s |
| 末段阀换向率 | 0（无颤振） |
| 最高腔压 | 19.3 MPa（< 溢流 21.0 MPa） |
| 泵需求比最大 | 1.15（仅多段反向回零瞬间，由蓄能器补上、供压下跌） |

工况集合：`低速5_{0,±2,±5,±10,±20,±30}deg`、`静止0_±30deg`、
`中速40_+20deg`、`高速60_+20deg`、`高速80_±30deg`、`连续指令_+10_-10_0`
（0→+10°→−10°→0 三段连续指令与反向回零）。

### 2.5 尚未解决的真实局限

1. **机构对理想阿克曼的固有偏差**：后三桥最大 RMS 1.8255°（六桥在 ±30° 目标上
   需要 ±40° 而机构只能到约 ±38°）。这是齿条—梯形拓扑的属性，液压闭环不负责消除，
   也**不计入**跟踪误差判定。
2. **目标轨迹超附着的工况在物理上不可行**：80 km/h + 30° 的目标路径附着比 5.76。
   软件照常完成计算并标 `VEHICLE_DYNAMIC_INFEASIBLE`；**"计算完成"不等于"实际车辆安全可行"**。
3. **多段连续指令的稳态窗**：稳态指标取末 20% 采样窗，对末段回到 0 的多段轨迹，
   该窗需完全落在最后一个保持段内（`run_j1r2_dynamic.py` 已按此设置时长）。
4. **全部液压参数为工程选型值**（`ENGINEERING_DESIGN_ASSUMPTION`），未经甲方实测验证。
5. **前组缸全行程偏长**（393.6 mm）：包络按机构单调可达区间取，属保守取法；
   流量按 ±30° 工作行程选，所以并未把泵选大。
6. 摩擦系数、轴荷、折算惯量、油液体积弹性模量等均为工程假设。

### 2.6 已修复、**不允许重新引入**的历史问题

| # | 历史问题 | 修复位置 |
|---|---|---|
| 1 | 机构延拓表零位行被**前置**到数组第 0 位 → q 网格非单调、0° 最优点落在下标 0 被当成"撞包络边界" | `engineering/model.py::_q_table`（按序插入 + 严格递增断言） |
| 2 | 包络按"±35° 车轮角需求 ×1.02"硬裁 → 六桥在 −30° 上工作点正好落在端点，一有超调整段 `MAPPING_OUT_OF_ENVELOPE` | `scripts/j1/build_engineering_config.py`（改为按机构单调可达区间取） |
| 3 | 机构行程区间不对称而缸中位居中 → 一侧够不着 | `CylinderParameters.stroke_offset_m` + `EngineeringHydraulicSystem.evaluate` 用 `xc = x − offset` |
| 4 | 饱和统计拿**限幅后**的值再比限幅 → 永远报 0% | `PIDDiagnostics`（`unclipped_request` / `at_limit` / `anti_windup_active`） |
| 5 | 道路负载用**目标曲率**当已实现运动 | `road_load(..., use_actual_curvature=True)` 与 `actual_curvature_1pm()` |
| 6 | 附着不足被当成程序失败而中断积分 | 只有 `LOAD_CONVERSION_SINGULAR` 才是停止条件 |
| 7 | 跟踪判据取「对瞬时指令角」与「对最终机构角」两者较大值 → 多段轨迹下凭空产生十几度假误差 | `runner.py::_summarise`（只用瞬时指令角） |
| 8 | 二桥跟着一桥转同样角度，对理想阿克曼偏差 13.56° | `scripts/j1r2/retune_front_follower.py --scale 1.39`（改二桥转向臂有效半径，**未改甲方坐标**） |
| 9 | 界面用一个红色 FAIL 代表所有状态 | `ui.py::_update_lights`（三盏独立指示灯） |
| 10 | 旧 L1-Fast 液压模型有阻断级缺陷（负阻尼、前端静力仅约 33 N） | 正式模型改为 `ENGINEERING_HYDRAULIC_V1`；L1-Fast 仅保留为历史对照 |

### 2.7 甲方确认数据 vs 工程假设的边界

| 类别 | 内容 | 能不能改 |
|---|---|---|
| **甲方确认（CUSTOMER）** | `mechanical_model_input_spec_v1.0.yaml` 的旋转副、铰点、车轮中心、车桥位置；`third_axle_point20_mm` | **绝对不能改**（`EngineeringSteeringModel._validate()` 会校验） |
| **工程假设（`ENGINEERING_DESIGN_ASSUMPTION`）** | 转向臂/齿条/边拉杆/中间拉杆尺寸（`engineering_mechanism.json`）；全部液压参数（`engineering_hydraulics.json`）；`ground_load.*`；折算惯量；指令斜坡参数 | 可以改，但**必须保持标记与出处** |
| **数值包络（非机械限位）** | `q_envelopes_rad` | 由连续延拓实测得到，改它等于改模型能力边界，需重新出全套证据 |

---

## 3. 退化模型接口审计

**审计对象**：`src/steering_sim/hydraulics_engineering/`
**权威清单**：`docs/handoff/degradation_interface_audit.csv`（含源码行号）、
`docs/handoff/degradation_feature_sources.csv`

### 3.1 结论摘要（六条）

1. **7 个退化量全部已经真正接入动力学**，没有一个是"只是配置字段"。
2. **但作用范围是"整机统一"**：`EngineeringHydraulicParameters.degradation` 是
   **单一实例**，7 个量里有 6 个是**全局乘子**——前桥与后桥、四个通道共用同一个值。
   唯一真正**部件级**的退化字段是 `ValveParameters.deadband`（每通道独立）。
   → **当前无法表达"前桥泵磨损、后桥泵仍健康"这类部件级差异。**
3. 但 `PumpParameters` / `ChannelParameters` / `CylinderParameters` **本身就是按实例的**
   （2 条供油轨、4 个通道各一份）。可以直接修改某个部件的**额定参数**
   （例如把 `front` 轨的 `displacement_m3_per_rad` 调小）来表达部件级差异；
   缺的只是"在额定值之上再叠加一个磨损增量"的分层结构。
4. **尚未完成物理映射的缺口**（需新增字段，不是现有字段没接好）：
   泵转速不是状态也不是输入、无部件级泵容积效率/内泄漏字段、无阀芯内泄漏与滞环
   （死区是**对称**的）、无缸外泄漏、无齿轮泵特有的流量脉动/困油。
5. **已经能用退化后的参数重跑同一套联合仿真**：`with_degradation()` 生成副本 →
   `save_parameters()` 写到**新文件** → `dataclasses.replace(J0Config,
   engineering_parameters_path=新文件)` → `J0Runner`。健康配置一行不用改。
6. **`src/steering_sim/demo/degradation.py` 是过时的占位模块，必须先处理**：
   它的 `INTERFACE_MAP` 指向**已停用的 L1-Fast**（`hydraulics_lumped.*`），
   而且它的 `DegradationParameters` 与 `hydraulics_engineering.parameters.DegradationParameters`
   **同名**（前者 12 个因子、后者 7 个），极易混淆。`ui.py` 与 `cli.py` 仍在导入它。

### 3.2 逐个参数的作用点

| 参数 | 部件 | 单位 | 作用点（源码） | 作用范围 | 进入动力学 |
|---|---|---|---|---|---|
| `pump_volumetric_efficiency` | 泵 | — | `model.py:159` `_supply_equilibrium_pressure`；`model.py:316` `evaluate` | **GLOBAL** | 是 |
| `pump_internal_leakage_m3_s_per_pa` | 泵 | m³/s/Pa | `model.py:318` `evaluate` | **GLOBAL** | 是 |
| `supply_pressure_scale` | 泵/供油轨 | — | `model.py:158`（溢流设定）、`model.py:225`（供压状态） | **GLOBAL** | 是 |
| `valve_flow_coefficient_scale` | 阀 | — | `model.py:240` `evaluate` | GLOBAL 乘子 × 每通道阀参数 | 是 |
| `valve_lag_scale` | 阀 | — | `model.py:234` `evaluate` | GLOBAL 乘子 × 每通道阀参数 | 是 |
| `cylinder_internal_leakage_m3_s_per_pa` | 缸 | m³/s/Pa | `model.py:259` `evaluate` | GLOBAL 乘子 × 每通道缸参数 | 是 |
| `cylinder_friction_scale` | 缸 | — | `model.py:281` `evaluate` | GLOBAL 乘子 × 每通道缸参数 | 是 |
| `ValveParameters.deadband` | 阀 | — | `ValveParameters`（每通道字段） | **PER_CHANNEL** | 是 |
| `ValveParameters.lag_time_s` | 阀 | s | 每通道字段 | PER_CHANNEL | 是 |
| `ValveParameters.discharge_coefficient` | 阀 | — | 每通道字段 | PER_CHANNEL | 是 |
| `CylinderParameters.coulomb_friction_n` | 缸 | N | 每通道字段 | PER_CHANNEL | 是 |
| `CylinderParameters.viscous_damping_n_s_per_m` | 缸 | N·s/m | 每通道字段 | PER_CHANNEL | 是 |
| `CylinderParameters.area_a_m2 / area_b_m2` | 缸 | m² | 每通道字段 | PER_CHANNEL | 是 |
| `PumpParameters.displacement_m3_per_rad` | 泵 | m³/rad | 每条供油轨字段 | **PER_SUPPLY_RAIL** | 是 |
| `PumpParameters.relief_pressure_pa` | 泵/溢流阀 | Pa | 每条供油轨字段 | PER_SUPPLY_RAIL | 是 |
| `PumpParameters.relief_area_m2` | 溢流阀 | m² | 每条供油轨字段 | PER_SUPPLY_RAIL | 是 |
| `PumpParameters.nominal_speed_rad_s` | 泵 | rad/s | 每条供油轨字段，**常量** | PER_SUPPLY_RAIL | 是（常量） |

**另一处已生效**：`src/steering_sim/demo/assessment.py:299-306`
（`_assess_supply_engineering`）读 `degradation.pump_volumetric_efficiency`
折算泵流量 → **运行前检查里的供油余量会随退化变化**。

**一处小瑕疵**：`_supply_equilibrium_pressure()` 只用了 `pump_volumetric_efficiency`，
**没有减去 `pump_internal_leakage_m3_s_per_pa`**。内泄漏非零时，零位初值会比真实平衡点
略高，产生一段几毫秒的充液瞬态。健康模型（内泄漏 = 0）不受影响。

### 3.3 两条供油轨在工程模型里的定义

`EngineeringHydraulicParameters.supplies: Mapping[str, PumpParameters]`，
键为 `"front"` / `"rear"`（`SUPPLY_ORDER = ("front", "rear")`）。
通道通过 `ChannelParameters.supply` 挂到某条轨上：
`channel_front → front`；`channel_rear_1/2/3 → rear`。
每条轨一个状态 `p_supply`，状态向量偏移见 §1.3（用 `state_layout()` 取，不要手写）。

### 3.4 退化参数如何影响各部件（物理映射现状）

| 目标 | 现有可用的量 | 缺什么 |
|---|---|---|
| **泵容积效率下降** | `pump_volumetric_efficiency`（全局）；或直接改 `PumpParameters.displacement_m3_per_rad`（按轨） | 按轨的独立效率字段 |
| **泵内泄漏增大** | `pump_internal_leakage_m3_s_per_pa`（全局） | 按轨的独立泄漏字段 |
| **阀流量系数变化** | `valve_flow_coefficient_scale`（全局）× `ValveParameters.discharge_coefficient` / `maximum_area_m2`（按通道） | — （已够用，只是全局乘子要拆细） |
| **阀死区** | `ValveParameters.deadband`（**按通道**，已生效） | 非对称死区；温漂 |
| **阀响应迟滞** | `valve_lag_scale`（全局）× `ValveParameters.lag_time_s`（按通道）—— 只有**一阶滞后** | 真正的**滞环**（开度上行/下行不同曲线）；阀芯内泄漏面积 |
| **缸内泄漏** | `cylinder_internal_leakage_m3_s_per_pa`（全局） | 按通道字段 |
| **缸摩擦** | `cylinder_friction_scale`（全局）× `CylinderParameters.coulomb_friction_n` / `viscous_damping_n_s_per_m`（按通道） | 按通道的摩擦倍率；Stribeck 效应 |
| （缸外泄漏） | **无** | `external_leakage_m3_s_per_pa` 字段与腔外漏项 |
| （齿轮泵脉动/困油） | **无** | 啮合频率流量脉动、齿顶间隙温变 |

**关于实际采用齿轮泵**：当前 `PumpParameters` 是**理想定量泵 + 溢流阀 + 蓄能器**，
`ideal_flow_m3_s = displacement_m3_per_rad · nominal_speed_rad_s`，**没有任何脉动项**。
齿轮泵的主要退化机制（齿顶/端面间隙增大 → 容积效率下降、内泄漏上升、
低压区流量脉动幅值变化）中，**前两项已有承载字段，第三项没有**。
`displacement_m3_per_rad` 对齿轮泵应理解为**每弧度排量的等效值**。

### 3.5 退化驱动特征如何提取

**逐采样点直接可得**（`runner._row` 已写入时间序列 CSV，共 230 列）：

| 部件 | 特征 | 列名 |
|---|---|---|
| 泵 | 供油压力 | `supply_pressure_front_mpa_g` / `supply_pressure_rear_mpa_g` |
| 泵 | 流量余量 | `pump_capacity_margin_front_m3_s` / `pump_capacity_margin_rear_m3_s` |
| 泵 | 供油不足标志 | `pump_capacity_insufficient_front` / `pump_capacity_insufficient_rear` |
| 阀 | 阀芯位置（命令） | `<channel>_valve_command` |
| 阀 | 未限幅请求 / 贴限幅 / 抗饱和 | `<channel>_pid_unclipped_request` / `_pid_at_limit` / `_pid_anti_windup` |
| 阀 | 两侧流量 | `<channel>_flow_a_m3_s` / `<channel>_flow_b_m3_s` |
| 缸 | 位移 / 速度 | `<channel>_x_m` / `<channel>_v_m_s` |
| 缸 | 两腔压力 | `<channel>_pA_mpa_g` / `<channel>_pB_mpa_g` |
| 缸 | 液压力 / 负载力 | `<channel>_hydraulic_force_n` / `<channel>_load_force_n` |
| 缸 | 广义道路力矩 | `<channel>_Q_road_nm` |
| 缸 | 行程雅可比 / 机构坐标 | `<channel>_dx_dq_m_per_rad` / `<channel>_q_actual_rad` |
| 系统 | 目标/实际行程 | `<channel>_x_ref_eff_m` / `<channel>_x_m` |
| 系统 | 十二轮角 | `wheel_<axle>_<side>_actual_deg` / `_command_deg` / `_target_mechanism_deg` |

`<channel>` ∈ {`channel_front`, `channel_rear_1`, `channel_rear_2`, `channel_rear_3`}；
`<axle>_<side>` ∈ `1_left` … `6_right`。

**只在 `EngineeringOutput` 里、未写入 CSV**（需要的话在 runner 里加列即可）：
`pump_flow_m3_s`、`demand_flow_m3_s`（逐轨），
`ChannelOutput.supply_flow_m3_s` / `friction_force_n` / `end_stop_force_n` /
`stroke_utilisation` / `at_stroke_limit`。

**尚无来源、必须新增的缺口**：

| 缺口 | 说明 | 建议 |
|---|---|---|
| **泵转速** | `PumpParameters.nominal_speed_rad_s` 是常量，不是状态也不是输入 | `HydraulicInput` 已有 `pump_speeds_rad_s` 字段；让 `evaluate` 从 `inputs` 读即可（约 3 行） |
| **泵压差** | 无独立输出 | 现算：`supply_pressures_pa_g[j] − tank_pressure_pa` |
| **泄漏流量** | 已并入 `flow_a_m3_s` / `flow_b_m3_s`，不单独给出 | 在 `ChannelOutput` 加 `leakage_flow_m3_s` |
| **累计行程 / 累计流量 / 循环数** | 模型不做累计 | 在调用方对时间序列积分即可，不必进模型 |
| **阀芯滞环** | 无 | 需新增状态或滞环映射 |

### 3.6 如何在不修改健康模型默认值的前提下创建退化副本

```python
from dataclasses import replace
from pathlib import Path
import json

from steering_sim.hydraulics_engineering import (
    load_parameters, with_degradation, save_parameters, EngineeringHydraulicSystem)
from steering_sim.j0_coupling.config import load_j0_config
from steering_sim.j0_coupling.runner import J0Runner
from steering_sim.engineering.model import EngineeringSteeringModel

healthy_path = Path("configs/j1r2/engineering_hydraulics.json")
healthy = load_parameters(healthy_path)              # 健康默认值，全程只读

worn = with_degradation(                            # 返回副本，不动 healthy
    healthy,
    pump_volumetric_efficiency=0.72,
    pump_internal_leakage_m3_s_per_pa=6.0e-11,
    valve_flow_coefficient_scale=0.85,
    cylinder_internal_leakage_m3_s_per_pa=2.0e-11,
    cylinder_friction_scale=1.6,
)
tmp = Path("outputs/wear/pump_wear_step_0007.json")
save_parameters(worn, tmp)                          # 写到新文件

config = replace(load_j0_config("configs/j0/j0_config.json"),
                 engineering_parameters_path=tmp)   # 只改路径
runner = J0Runner(config, EngineeringSteeringModel(...), probe_authority=False)
```

要点：

* `with_degradation()` 用 `dataclasses.replace`，`healthy` 对象**不可变**，天然安全；
* `J0Runner.__init__` 通过 `load_parameters(config.engineering_parameters_path)`
  装载参数 —— **`J0Config.engineering_parameters` 字段目前存在但 runner 并不读它**；
  想完全在内存里注入，需要给它加一个分支（约 3 行），或如上走临时文件；
* 健康基线文件 `configs/j1r2/engineering_hydraulics.json` **不要改**。

### 3.7 接入建议（不写算法，只给结构）

建议把"整机统一退化"保留为快捷方式（**向后兼容，现有 576 个测试全部继续通过**），
在其之上增加**部件级** wear：

```python
# 建议新增（示意，本轮不实现）
@dataclass(frozen=True, slots=True)
class PumpWearState:
    volumetric_efficiency: float = 1.0        # 乘到 ideal_flow_m3_s
    internal_leakage_m3_s_per_pa: float = 0.0 # 加到供油轨方程
    displacement_scale: float = 1.0

@dataclass(frozen=True, slots=True)
class ValveWearState:
    flow_coefficient_scale: float = 1.0
    lag_scale: float = 1.0
    deadband_delta: float = 0.0               # 加到 ValveParameters.deadband
    leakage_area_m2: float = 0.0              # 【新物理】

@dataclass(frozen=True, slots=True)
class CylinderWearState:
    internal_leakage_m3_s_per_pa: float = 0.0
    friction_scale: float = 1.0
    external_leakage_m3_s_per_pa: float = 0.0 # 【新物理】
```

挂载点（只碰 `hydraulics_engineering/parameters.py` 与 `model.py` 两个文件）：

* `EngineeringHydraulicParameters` 增 `supply_wear: Mapping[str, PumpWearState]`
  与 `channel_wear: Mapping[str, ValveWearState | CylinderWearState]`；
* `EngineeringHydraulicSystem.evaluate` 里**优先取部件级、缺省回落到现有全局乘子**；
* 需要新增的物理项只有三处：阀芯泄漏面积、缸外泄漏、泵转速改为从 `inputs` 读。

**其它模块一行都不用改**：`J0Runner`、`J0GeometryAdapter`、`road_load`、
`EngineeringSteeringModel`、`PIDController`、`DemoService`、`ui.py`
都不读 `degradation`（唯一例外是 `demo/assessment.py::_assess_supply_engineering`
读 `pump_volumetric_efficiency` 折算泵流量，属**期望行为**，无需改）。

---

## 4. 下一阶段最小实现建议

目标链条：
**30 天分段 Excel 任务谱 → 快速载荷特征提取 → 齿轮泵/阀/缸退化更新 → 参数回写 →
系统性能评估 → 重复任务循环寿命**

### 4.1 每步复用什么

| 步骤 | 复用 | 需要新增 |
|---|---|---|
| ① 任务谱录入 | `demo.batch.read_cases(path)` 已能读 CSV/XLSX → `DemoScenario` 列表；`write_template()` 出模板 | Excel 加一列表示**该段持续时长或循环次数**（`duration_s` 现在是"单次仿真时长"，语义不同，建议新增 `segment_duration_s` / `repeats`），读入后由调用方展开 |
| ② 快速载荷特征提取 | `demo.batch.build_context()` + `estimate_case()`：已给出每通道**需求推力、可用推力、力裕度、预测行程、预测轮角、附着比**；准稳态路径 24 级 | 由需求推力派生工作压力 `p = F_req / area_a_m2`、由预测行程派生行程循环幅值；累计量在调用方积分 |
| ③ 退化更新 | `with_degradation()` / 新的部件级 wear | **纯函数** `wear_step(wear_state, features, dt) -> wear_state`，不碰健康配置。**标定数据没有，必须由甲方提供** |
| ④ 参数回写 | `save_parameters()` + `replace(J0Config, engineering_parameters_path=…)` | 一个薄封装 `make_runner(wear_state) -> J0Runner` |
| ⑤ 系统性能评估 | `J0Runner.run_case()`（真实动态）或 `run_batch()`（准稳态）；指标从 `summary` 取：`TRACKING_PASS`、`steady_max_tracking_error_vs_command_deg`、`control_saturation_fraction`、`max_pressure_mpa_g`、`max_pump_demand_ratio` | 退化前后对比表 |
| ⑥ 循环寿命 | 无 | 磨损率 → 阈值 → 循环数的映射。**必须有甲方标定的磨损率/S-N 数据**；没有数据时只能输出"达到阈值所需循环数的**假设值**"，且必须显式标注为假设 |

### 4.2 60 秒预算

3111 个工况的准稳态批算实测 **26–29 s**。30 天分段任务谱的段数远少于 3111，
因此"任务谱 → 特征 → 一次退化更新 → 性能评估"整轮在**秒级**完成；
即使每天做一次退化更新（30 轮）也在预算内。
**注意**：真实动态积分单个代表工况约 10–30 s，所以"性能评估"这一步应默认走
`FAST_BATCH_ESTIMATE`，只在需要展示时间序列时用 `FULL_DYNAMIC`。

### 4.3 不需要改的代码

`src/steering_sim/engineering/**`（机械）、`src/steering_sim/j0_coupling/geometry.py`、
`road_load.py`、`authority.py`、`src/steering_sim/control/**`、
`src/steering_sim/demo/plots.py`、`batch.py`、`scenario.py`。

### 4.4 必须新增的接口

1. 部件级 wear 结构（见 §3.7）；
2. `PumpParameters.internal_leakage_m3_s_per_pa`（把全局乘子下沉到部件）；
3. `ChannelOutput.leakage_flow_m3_s`（泄漏可观测）；
4. 泵转速从 `HydraulicInput.pump_speeds_rad_s` 读（字段已存在，改 3 行）；
5. 阀芯泄漏面积、缸外泄漏两个新物理项；
6. 任务谱的"段时长/循环数"列与展开逻辑；
7. `wear_step` 纯函数与 `make_runner(wear_state)` 薄封装。

**再次强调：本轮不实现上述任何一条，只提供清单。**

---

## 5. 用户界面迁移说明

### 5.1 现有 Tkinter GUI

**唯一 UI 文件**：`src/steering_sim/demo/ui.py`
**启动**：`start_steering_demo.bat` → `scripts/j0_demo/start_demo.py`（环境自检 + 中文错误提示）

| 组件 | 说明 |
|---|---|
| `DemoApp(root, service)` | 主窗口 |
| `TAB_LAYOUT` | 五个标签页：机械转向结果 / 液压结果 / 控制结果 / 工况与限制 / 十二轮角度数值表 |
| `ImagePane` | 可滚动图片面板（显示 `plots.py` 生成的 PNG） |
| `_ProgressDialog` | 模态进度窗（**单线程**，避免 Tk + 后台线程的进程级崩溃） |
| `_update_lights(summary)` | 三盏独立指示灯：① 计算状态 ② 液压跟踪 ③ 目标轨迹物理可行性 |
| `_fill_wheel_table(result)` | 十二轮数值表（理想 / 机构 / 实际 / 跟踪偏差 / 阿克曼偏差 / 状态） |
| `_on_import_cases` / `_on_run_batch` / `_on_export_template` | CSV·XLSX 批量导入、批量计算并导出（可取消） |
| `_on_export_csv` / `_on_export_report` | 导出时间序列与报告 |
| `_show_degradation()` | 现在弹的是 `demo/degradation.py::describe_interfaces()`（**过时占位，见 §3.1 第 6 条**） |

### 5.2 数据来源与依赖

* **计算**：全部经 `DemoService.assess/run/replay_preset/export_csv/write_report`；
* **批量**：`demo.batch.build_context / run_batch / read_cases / write_*`；
* **绘图**：`demo.plots.plot_all(result, centers, out_dir)` 产出 7 张 PNG，
  `ui.py` 只负责显示；
* **`ui.py` 没有直接 import `steering_sim.j0_coupling.runner`**（已核对）——
  这条边界是迁移的关键资产。

**唯一越界处**：`DemoApp._batch_context()` 里
`build_context(adapter=self.service.runner.geometry)` 读了 `runner.geometry`。

### 5.3 迁移到 PySide6 的建议

1. **只重写 `ui.py` 一个文件**。计算内核、服务层、批量、绘图、场景定义全部复用。
2. 先做 **"Qt 壳 + 复用现有 PNG"**：把 `ImagePane` 换成 `QLabel + QScrollArea` 显示
   同一批 PNG，风险最低、可当天跑通。是否换成 Qt 原生绘图（pyqtgraph / QtCharts）
   是**可选项**，与退化建模无关，建议放到最后。
3. 把 `_batch_context()` 里的 `self.service.runner.geometry` **下沉为
   `DemoService.batch_context()`**，这样 UI 与 runner 彻底解耦。
4. `_on_run_batch` 现在是**同步阻塞 + 模态进度窗**；Qt 下应改为工作线程
   （`QThread` 或 `QTimer` 分片），`run_batch(..., on_progress=…, should_stop=…)`
   这两个回调已经预留好，不需要改内核。
5. 三盏指示灯、十二轮表、批量按钮的语义与文案应**原样保留**（它们是验收项）。
6. **PySide6 当前未安装**。安装属于"自动安装依赖"，**需要甲方明确授权**；
   且项目要求离线环境，需确认离线安装包来源。
7. 保留 `start_steering_demo.bat` 的启动方式（纯 ASCII + CRLF，中文输出交给 Python）。

---

## 6. 测试与复现

### 6.1 环境核验

```bash
E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe -c "import sys, numpy, scipy, pandas, openpyxl, matplotlib; print(sys.version); print(numpy.__version__, scipy.__version__, pandas.__version__, openpyxl.__version__, matplotlib.__version__)"
```
实测：Python 3.11.16 / numpy 2.4.6 / scipy 1.17.1 / pandas 3.0.5 / openpyxl 3.1.5 / matplotlib 3.11.2。
**PySide6 / PyQt5 未安装。**

### 6.2 安装依赖

依赖声明在 `pyproject.toml`：`numpy>=1.24`、`scipy>=1.10`、`pandas>=2.0`、
`openpyxl>=3.1`；可选 `test = [pytest>=7.4]`、`plot = [matplotlib>=3.7]`。
当前环境**已全部满足**，**不需要安装任何东西**。
后续如需 PySide6，请甲方先确认离线包来源后再执行。

### 6.3 运行单工况

```bash
cd E:\15_project
# 命令行
E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe -m steering_sim.demo.cli run --angle 30 --speed 10 --duration 3.75
# 图形界面
start_steering_demo.bat
```

### 6.4 运行测试

```bash
E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe -m pytest -q
```
**基线：576 passed, 0 failed**（约 17 分钟）。
只跑与工程模型相关的部分：

```bash
python -m pytest tests/hydraulics_engineering tests/engineering tests/j0_coupling -q
```

### 6.5 运行 3111 批量工况

```bash
python scripts/j1r2/run_j1r2_batch.py                 # 标准 3111 网格
python scripts/j1r2/run_j1r2_batch.py --cases 我的工况.xlsx   # 自定义 CSV/XLSX
```

### 6.6 主要结果路径

| 内容 | 路径 |
|---|---|
| J1-R2 报告 | `docs/integration/phase_J1_R2_report.md` |
| 61 角覆盖表 | `outputs/j1/gate1_angle_table.csv`、`gate1_summary.json` |
| 液压选型核算 | `outputs/j1r2/hydraulic_sizing.json` |
| 3111 结果 | `outputs/j1r2/j1r2_full_cases.csv` / `.xlsx`、`j1r2_full_cases_summary.json` |
| 18 工况动态结果 | `outputs/j1r2/dynamic/j1r2_dynamic.json` |
| 时间序列（230 列） | `outputs/j1r2/dynamic/<工况>_timeseries.csv` |
| 步长收敛 | `outputs/j1r2/step_convergence.json` |
| 状态块 | `outputs/j1r2/j1r2_status_block.txt`、`j1r2_status.json` |
| 图 | `outputs/j1r2/fig_r2_1..8_*.png` |
| 界面运行产物 | `outputs/j0_demo/<工况签名>/`（`timeseries.csv`、`summary.json`、`fig*.png`） |
| 上一阶段交付包 | `handoff_to_chatgpt/phase_J1_R2.zip` |

---

## 7. 风险和禁止事项

### 7.1 数据保护（硬约束）

1. **不得修改甲方确认的原始坐标**：`mechanical_model_input_spec_v1.0.yaml`、
   `configs/j1/engineering_config.json` 里的 `third_axle_point20_mm`。
   `EngineeringSteeringModel._validate()` 会在加载时校验，改了就抛错。
2. 不得删除或覆盖 `qh1_1.ame`、`qh1_1_MCP_AUDIT.ame`、`source_materials/`、
   `.snapshots/` 下的历史快照、以及 `handoff_to_chatgpt/` 下已有交付 ZIP。
3. 禁止未经授权的 `git reset / clean / stash / commit / push`。

### 7.2 模型与结论（硬约束）

1. **不回退到旧 Amesim / L1-Fast 作为正式模型**。`L1-Fast`（`src/steering_sim/hydraulics_lumped/`）
   已被实测确认存在阻断级缺陷：四通道 `dF_hyd/dv > 0`、`dF_hyd/dx > 0`
   （负阻尼 + 负刚度）。J0-R1 修掉前阀的中立点后，其实测静态力窗口为
   前组 ±6200 N、后三组约 +6040 / −10690 N，**低于当时机构的需求
   （8478 / 7418 / 14583 / 5588 N）**，这正是 J1 阶段动态跟踪只有 1/15 的根因。
   它现在只保留为**历史对照与回归测试**，仅在显式传 `hydraulic_model="L1_FAST"`
   时可构造（见 `DemoService.__init__` 与 `tests/demo/conftest.py` 的 `demo_service`
   夹具）。任何新开发都不得把它当作正式模型。
2. **不直接用目标轮角替代液压实际轮角**。实际角必须由真实缸位移经机构映射反求
   （`J0GeometryAdapter.q_from_strokes(x)` → `wheel_angles_deg(q)`）。
   禁止引入任何"显示专用"的第二套角度计算。
3. **不把 3111 准稳态批算描述为 3111 次完整动态积分**。
   它是 `FAST_BATCH_ESTIMATE`，逐行已标注；完整动态积分只有 18 个代表工况 +
   单工况实时运行。
4. **不把高速超附着工况标记为真实车辆安全可行**。`NUMERICAL_COMPLETED` /
   `TRACKING_PASS` / `VEHICLE_DYNAMIC_INFEASIBLE` 三者必须分开报告，
   §2.4 里 3/18 个工况属于"算得完但车走不了"。
5. **不把假设退化系数描述成经过实验标定**。退化试验数据**目前没有**，
   将来由甲方提供；在有标定数据之前，任何退化/寿命数字都必须显式标注为假设。
6. **不破坏现有健康联合仿真基线**。改动后必须重跑 `python -m pytest -q`
   （基线 576 passed）并重跑 §2.3/§2.4 的两条验收，确认数字没有回退。

### 7.3 已知的、需要 Codex 先处理的技术债

| # | 问题 | 建议 |
|---|---|---|
| 1 | `src/steering_sim/demo/degradation.py` 是**过时占位模块**，`INTERFACE_MAP` 指向已停用的 L1-Fast；其 `DegradationParameters`（12 因子）与 `hydraulics_engineering.parameters.DegradationParameters`（7 因子）**同名** | 重写 `INTERFACE_MAP` 指向 `hydraulics_engineering`，或把该模块整体退役并把"待开发"提示改由新接口生成；**务必消除同名冲突** |
| 2 | `J0Config.engineering_parameters` 字段存在但 `J0Runner` 不读 | 要么删掉，要么在 `J0Runner.__init__` 里加分支支持内存注入 |
| 3 | `_supply_equilibrium_pressure()` 未减去 `pump_internal_leakage` | 内泄漏非零时会有一段毫秒级充液瞬态（健康模型无影响） |
| 4 | `demo/assessment.py::_assess_supply_engineering` 读全局 `pump_volumetric_efficiency` | 一旦引入部件级 wear，这里要同步改为按轨读取 |
| 5 | `ui.py::_batch_context()` 触到 `service.runner.geometry` | 迁移 PySide6 时下沉为 `DemoService.batch_context()` |
| 6 | `tools/Simcenter-Amesim-MCP` 子模块一直显示为修改 | 与本项目无关，勿动 |

---

## 附：本交接包文件清单

| 文件 | 内容 |
|---|---|
| `CODEX_HANDOFF_20261012.md` | 本文件（主交接文档） |
| `codex_interface_map.json` | 关键模块类/方法/字段签名、配置键、液压状态布局、机械映射、230 个时间序列列名（`ast` 提取） |
| `degradation_interface_audit.csv` | 退化参数逐个的作用点、源码行号、作用范围、是否进入动力学 |
| `degradation_feature_sources.csv` | 退化驱动特征在现有模型里的来源，并显式标出缺口 |
| `codex_handoff_baseline.json` | J1-R2 正式基线实测数字（61 角、选型、3111、18 工况、步长收敛、状态块） |
| `README.md` | 附加资料说明 |
| `CONFIG_SNAPSHOT.json` | 四份正式配置的**原文快照**（便于对照，以仓库文件为准） |
| `REPRODUCE.md` | 精简复现命令与主要结果路径 |
| `SOURCE_INDEX.csv` | 最小源码索引：30 个关键文件的用途、行数、字节数、sha256、是否随包附带源码 |
| `key_sources/hydraulics_engineering/*.py` | **随包附带源码**：下一阶段要直接扩展的液压工程模块（4 个文件） |
| `key_sources/demo/degradation.py` | **随包附带源码**：需先处理的过时占位模块 |
| `build_handoff_pack.py` | 生成上述机器可读资料的脚本（只读，不改仿真） |
| `package_codex_handoff.py` | 打包脚本 |
| `SHA256SUMS.txt` | 包内每个文件的 sha256 |

**不随包附带**（按任务书要求避免重复打包）：Amesim 原始文件、
Conda 环境、历史输出、以及上一阶段 `phase_J1_R2.zip` 里已经交付过的
3111 结果 CSV 与 18 条时间序列 —— 那些请从
`handoff_to_chatgpt/phase_J1_R2.zip` 取。
