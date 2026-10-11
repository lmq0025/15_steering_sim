# L1-Fast hydraulic I/O contract

The interface is implemented by `HydraulicInput`, `HydraulicOutput`, and
`evaluate_hydraulic()` in `interface.py`. All quantities use SI units.

## Input

| field | shape | unit | meaning |
|---|---:|---|---|
| valve_commands | 4 | 1 | primary commands for dirvalve_6, 1, 8, 11 |
| pump_speeds_rad_s | 4 | rad/s | pump01, pump01_1, pump01_2, pump01_3 |
| external_load_forces_n | 4 | N | load opposed by each actuator |
| redundant_valve_commands | alias map | 1 | independent dirvalve_2, 9, 12 commands |
| prescribed_motion_by_alias | alias map | m, m/s, m/s2 | optional Amesim/mechanical boundary |

## Output

Each of four channel outputs contains position [m], velocity [m/s], hydraulic
force [N], A/B gauge pressure [Pa], and A/B flow [m3/s]. System output also
contains the two pump-outlet boundary pressures [Pa(g)], capacity margins
[m3/s], and one capacity-insufficient flag per supply group.

## Call example

```python
from steering_sim.hydraulics_lumped import (
    HydraulicInput, LumpedHydraulicSystem, evaluate_hydraulic)

model = LumpedHydraulicSystem.fast_engineering()
x = model.initial_state()
u = HydraulicInput(
    valve_commands=(1.0, 0.0, 0.0, 0.0),
    pump_speeds_rad_s=tuple(c.pump.nominal_speed for c in model.channels),
    external_load_forces_n=(0.0, 0.0, 0.0, 0.0),
    redundant_valve_commands={"dirvalve_2": 0.0,
                              "dirvalve_9": 0.0,
                              "dirvalve_12": 0.0},
)
dx, y = evaluate_hydraulic(model, 0.0, x, u)
```

The present autonomous local-mass model is not a substitute for the vehicle
steering mechanics. The mechanical integration must supply consistent load
forces, or an explicit motion boundary during hydraulic-only validation.
