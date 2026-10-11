# 退化预测 / 质量评估 参数接口说明（本轮不实现算法）

本轮（PHASE J0-DEMO）**只预留接口，不开发任何退化预测或质量评估算法**。
本文档说明预留了什么、放在哪里、后续怎么接。

---

## 1. 现状

```python
from steering_sim.demo import degradation

info = degradation.describe_interfaces()
info["status"]      # 'RESERVED'
info["implemented"] # False
```

- 界面可以显示「性能退化与质量评估（待开发）」；
- **不得输出任何未实现的寿命或质量预测值**；
- 未实现的入口显式抛 `DegradationNotImplementedError`，绝不返回占位数字。

```python
degradation.predict_life()    # -> DegradationNotImplementedError
degradation.assess_quality()  # -> DegradationNotImplementedError
```

---

## 2. 预留参数（健康值一律 1.0）

| 参数 | 默认 | 物理含义 |
|---|---:|---|
| `pump_volumetric_efficiency` | 1.0 | 泵容积效率 |
| `pump_displacement` | 1.0 | 泵排量 |
| `valve_discharge_coefficient` | 1.0 | 阀流量系数 |
| `valve_response_speed` | 1.0 | 阀响应速度 |
| `valve_leakage` | 1.0 | 阀零位泄漏 |
| `cylinder_internal_leakage` | 1.0 | 液压缸内泄漏 |
| `cylinder_external_leakage` | 1.0 | 液压缸外泄漏 |
| `cylinder_friction` | 1.0 | 液压缸摩擦 |
| `cylinder_damping` | 1.0 | 液压缸阻尼 |
| `controller_proportional_gain` | 1.0 | PID 比例增益 |
| `controller_integral_gain` | 1.0 | PID 积分增益 |
| `controller_derivative_gain` | 1.0 | PID 微分增益 |
| `controller_command_limit` | 1.0 | 控制命令限幅 |

**健康工况下所有因子保持 1.0，不改变任何现有默认参数。**
把因子设成 0 或负数会被 `DegradationParameters.__post_init__` 拒绝。

---

## 3. 参数在模型中的落点

| 参数 | 落点 |
|---|---|
| `pump_volumetric_efficiency` | `hydraulics_lumped.pump.pump_flow` — 容积效率修正泵流量 |
| `pump_displacement` | `hydraulics_lumped.parameters.PumpParameters.displacement` |
| `valve_discharge_coefficient` | `hydraulics_lumped.valve.characteristic_orifice_flow` 的流量系数 |
| `valve_response_speed` | `hydraulics_lumped.valve` 的 SC_1 阀口开度曲线 |
| `valve_leakage` | `hydraulics_lumped.valve` 四孔口的零位泄漏面积 |
| `cylinder_internal_leakage` | `hydraulics_lumped.actuator` 的 A/B 腔间泄漏（当前为 0） |
| `cylinder_external_leakage` | `hydraulics_lumped.actuator` 的腔外泄漏 |
| `cylinder_friction` | `hydraulics_lumped.actuator` 的库仑摩擦力 |
| `cylinder_damping` | `hydraulics_lumped.actuator` 的粘性阻尼系数 |
| `controller_*_gain` | `control.pid.PIDController` 的 kp / ki / kd（四通道） |
| `controller_command_limit` | `j0_coupling.config.ChannelControlConfig.command_limit` |

---

## 4. 后续模块位置

以下模块名已预留，尚未创建：

```
steering_sim.demo.degradation        # 本文件所在模块，参数接口已就绪
steering_sim.demo.quality_assessment # 质量评估（未实现）
steering_sim.demo.prediction         # 剩余寿命预测（未实现）
```

---

## 5. 接入时的约定

1. **乘性修正**：退化因子一律作为乘性系数施加到上表对应的物理参数上，
   不新造物理量。
2. **不改默认值**：健康（全 1.0）时仿真结果必须与当前结果逐位一致；
   建议为此写一条回归测试。
3. **不越过演示层**：退化参数由 `steering_sim.demo` 层注入，
   不写进 `hydraulics_lumped` / `mechanics_ackermann_v2` 的默认参数。
4. **保持显式失败**：任何未实现的预测路径继续抛
   `DegradationNotImplementedError`，不允许用插值或经验公式先凑一个数字。
