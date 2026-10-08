# Python Phase 2-B Full FAST Simulation Report

## Outcome

- FAST initialization: **PASS**
- 0.01 s run: **PASS**
- 0.1 s run: **PASS**
- 1.0 s run: **PASS**
- Physical sanity checks: **PASS**
- Ready for Amesim comparison: **YES**

## Frozen runtime contract

- FAST states: **109**
- FAST line states: **67**
- Algebraic groups: **49**
- Group classification: 9 explicit, 0 linear, 32 small nonlinear, 8 switching
- Unsupported active elements: **0**

The state ordering is exactly `16E_full_state_index_FAST.csv`. IR V3 was not
modified. All pressures, flows, displacement, velocity and source quantities
are represented in SI units inside the runtime.

## Numerical formulation

The model uses direct pump/source evaluation, direct regularized resistance and
orifice laws, reduced R-C line dynamics, cylinder chamber compliance, mechanical
inertia, and local warm-start algebraic solves. CV/RV direction follows the
frozen `p2-p1` convention. The main integrator is BDF with `rtol=1e-4` and
per-state absolute tolerances from `18D_state_scaling.csv`.

No state-wide clipping is used. End-stop force is applied only to physical
mechanical travel. Switching relations are deterministic.

## Initialization

- Maximum hydraulic residual: 5.7461e-08 m^3/s
- Maximum mechanical constraint residual: 0
- Algebraic initialization failures: 0

Pressure states without numeric Amesim initialization metadata use a documented
1 bar engineering seed and are then projected toward their connected algebraic
boundaries. Every LEVEL C default is listed in `18B_fast_initial_conditions.csv`.

## Measured performance

| Physical duration | Median wall time | Real-time factor | nfev | njev | nlu |
|---:|---:|---:|---:|---:|---:|
| 0.01 s | 1.2823 s | 128.23 | 62 | 1 | 8 |
| 0.1 s | 42.9925 s | 429.925 | 624 | 49 | 157 |
| 1 s | 150.887 s | 150.887 | 2371 | 169 | 656 |

Each duration was measured three times; the table reports the median. The 1 s
run is stable but not yet fast enough for the final product target. Profiling
shows the dense BDF numerical Jacobian is the main bottleneck. This is an
optimization blocker, not a physics/sanity failure.

## Algebraic solver

- Recorded solve calls: 972359
- Failures: 0
- Maximum iterations: 4
- Mean iterations: 1.01093
- Warm-start hit rate: 99.985%

## Physical sanity

All 36 checks passed across the three required runs: finite states,
valid pressure range, positive chamber volumes, actuator travel, bounded
pressure, hydraulic mass balance, mechanical constraints, algebraic
convergence, active-element coverage, and 109/109 RHS coverage.

## Tests

`176 passed in 283.95s (0:04:43)`

## Phase 2-C interface

The scenario input functions, 109-state SI vector, algebraic diagnostics,
key-output sampler and compact time series are ready for later Amesim
comparison. No Amesim simulation or parameter fitting was performed here.
