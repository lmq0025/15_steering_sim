# R01 architecture

```mermaid
flowchart LR
  REF[Reference] --> CTRL[Controller: sampled step]
  MEAS[Measurement] --> CTRL
  CTRL -->|Command| COUPLED[Coupled RHS assembly]
  COUPLED --> HYD[HydraulicModel.rhs]
  COUPLED --> MECH[MechanicalModel.derivative]
  HYD -->|force / torque| MECH
  MECH -->|actuator x / v| HYD
  HYD <-->|p, Q| HP[HydraulicPowerPort]
  MECH <-->|F, v / T, omega| MP[Mechanical power ports]
  SOLVER[Solver] --> COUPLED
  COUPLED --> OBS[observe / measure / future quality hooks]
```

边界原则：控制器离散采样；物理模型提供连续 RHS；solver 不属于任何单一物理模块；耦合在同一次 RHS 评价中双向交换位移/速度与力/力矩。功率残差作为后续守恒测试接口。

## Mechanical routes after R02-D

```mermaid
flowchart LR
  POS[Actuator position] --> IOD[R02-D formal mechanical I/O]
  IOD --> Q[5 internal generalized coordinates]
  Q --> KIN[R02-B frozen geometry / closed-chain kinematics]
  KIN --> ANG[12 wheel angles]

  FORCE[Hydraulic force] -. future transient route .-> DYN[R02-C1 optional reduced dynamics]
  DYN -. q dynamics .-> KIN
```

- R02-B is the geometry and closed-chain kinematics core.
- R02-C1 is an optional reduced dynamics core for future force, transient and load calculations.
- R02-D is the current formal external mechanical I/O layer.

Normal position-to-angle use does not pass through R02-C1. CUSTOMER hardpoints
remain frozen; calibration is limited to explicit sensor/mapping/zero-offset
parameters unless a future bounded level-2 hardpoint-correction decision is approved.
