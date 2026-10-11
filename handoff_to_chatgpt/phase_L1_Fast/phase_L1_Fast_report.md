# Phase L1-Fast regulated-source hydraulic kernel

## Outcome

The model now has an explicit `regulated_constant_pressure` mode. It keeps the
R3 SC_1 four-port maps and HJ020/HJ021 equations but removes the supply-network
Newton/Brent loop from every RHS call. Front and rear pump-outlet boundaries
remain distinct at 18.6623 MPa(g) and 16.8685 MPa(g). Their SC_1 high and
return rails also remain distinct physical locations.

No chamber-pressure clamp was introduced. Pump flows are still evaluated per
pump. Demand above available flow raises a capacity warning while the ideal
regulated boundary remains unchanged; such a run is outside the validated
capacity envelope.

## Numerical result

The requested 2 ms step was rejected. In the prescribed step it produced a
2.581% worst normalized error, and the uncoupled
autonomous actuator became unstable. The retained 0.5 ms step agrees with the
0.25 ms numerical reference within 0.455% on
the stated pressure/force/position/velocity normalization.

## Required tests

- Healthy steady: PASS.
- Small autonomous step (50 ms direction test): PASS.
- 1 Hz prescribed-motion hydraulic sine: PASS.
- Pressure range across evidence runs: 0.819610 to 0.830386 MPa(g).
- Pump capacity: PASS.

## Runtime

All timings are actual runs on this machine with the dynamic 1 Hz scenario:

| physical duration | wall time | real-time factor |
|---:|---:|---:|
| 1 s | 0.684020 s | 0.684020 |
| 10 s | 6.972516 s | 0.697252 |
| 100 s | 68.794948 s | 0.687949 |

The 100 s under 1 s target is FAIL.
No further performance architecture was introduced after this measurement.

Relative to the retained L1-R3 100 s baseline of 458.563 s, the measured
speedup is 6.67x.

## Regression verification

The complete repository test suite passed: **230 passed in 111.47 s**. The
regulated mode keeps 16 dynamic states and zero pipe states. The legacy supply
solvers and their tests remain in the repository as explicitly separate modes;
they are not called by the regulated constant-pressure RHS.

## Scope and limitations

This is a prepressurized engineering candidate, not a zero-pressure startup
model. The constant pressure boundaries are normal-point transfers, not exact
pressure predictions for every duty cycle. Independent Amesim macro accuracy
in this new working mode is NOT_VERIFIED. The autonomous actuator was checked
only for short-time direction because the standalone local mass lacks the
vehicle steering load that will provide the real mechanical constraint.

The package is ready for mechanical interface review. It does not modify or
couple the existing mechanical model, controller, degradation, rainflow, or
quality-assessment code.
