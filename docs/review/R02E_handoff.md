# R02-E handoff — six-axle vehicle steering coordinator

## 1. Environment and Git

- Required environment: steering_sim
- Python executable:
  E:ProgramDatacondaDataenvs_dirssteering_simpython.exe
- Delivery branch: r02-vehicle-steering-coordinator
- R02-D branch was merged into main with history preserved before this branch
  was created.
- Final delivery commit: use the commit containing this handoff; the immutable
  hash is reported in the final delivery message.

No system PATH or other Conda environment was changed.

## 2. Delivered external chain

    target Axle1 mean angle + SteeringMode
                    |
                    v
    MultiAxleSteeringCoordinator
                    |
        ideal ICR wheel directions
                    |
                    v
    bounded fit of frozen five-DOF q
                    |
                    v
    required actuator positions
                    |
                    v
    MechanicalSteeringIOModel.solve_from_actuators
                    |
                    v
        actual frozen-mechanism wheel angles

The command is target_axle1_mean_angle_deg, not a steering-wheel angle. R02-E
is a low-speed geometric coordinator, not PID control, hydraulic dynamics, or
vehicle lateral dynamics. R02-B geometry and the R02-D formal I/O contract are
unchanged.

## 3. Generalized-Ackermann / ICR geometry

All twelve wheel steering-axis centers (x_i, y_i) are read automatically from
the pivots of the frozen WHEEL_i_POS_Y and WHEEL_i_NEG_Y bodies.

For an ICR (x_ICR, y_ICR), each ideal wheel axis is tangent to the circle about
the ICR. In the existing +X-forward, +Y coordinate system:

    delta_i = axis_equivalent(
        atan2(x_i - x_ICR, y_ICR - y_i)
    )

axis_equivalent maps the unoriented rolling axis to [-pi/2, pi/2]. This
construction creates both the front/rear phase reversal about x_ICR and the
POS_Y/NEG_Y Ackermann difference without hard-coded per-axle signs.

Given a preset x_ICR, a bounded scalar root solve finds y_ICR such that the
mean of the two ideal Axle1 wheel angles equals the requested Axle1 target.
Tests cover phase signs, inner/outer geometry, left/right symmetry, and the
increase of ideal demand with longitudinal distance from the ICR.

## 4. Baseline presets

Configuration:
configs/mechanics/multi_axle_steering_baseline.yaml

PUBLIC_6AXLE_BASELINE:

- x_ICR is computed at fraction 0.5 between frozen Axles 3 and 4;
- ideal phase pattern is Axles 1/2/3 versus Axles 4/5/6;
- source LITERATURE_BASELINE, confidence low_to_medium;
- NOT CUSTOMER CALIBRATED.

CUSTOMER_HINT_BASELINE:

- x_ICR is computed at fraction 0.5 between frozen Axles 2 and 3;
- ideal phase pattern is Axles 1/2 versus Axles 3/4/5/6;
- source CUSTOMER_HINT_UNCONFIRMED, confidence low;
- requires CUSTOMER confirmation/calibration.

An explicit x_icr_m can replace interpolation when configured. Explicit
x_icr_m takes priority. Preset ICR fraction and per-axle coordination gains are
centralized; CUSTOMER hardpoints remain frozen.

## 5. Steering modes

- LOW_SPEED_COUNTER_PHASE: fully implemented through generalized Ackermann.
- CRAB: minimum baseline implementation; all axle targets have one phase.
- FRONT_GROUP_ONLY: Axles 1/2 participate; Axles 3–6 target zero.
- CUSTOM: accepts an explicit gain for every axle.

No speed-dependent state machine or steering controller is implemented.

## 6. Frozen-mechanics target fit

Each rear axle minimizes its two-wheel squared target error over its existing
single q_i. q_front jointly minimizes the four-wheel target error for Axles 1
and 2. All solves are bounded to [-0.08, +0.08] rad, which remains only the
R02-B numerical verification interval, not a mechanical or operating limit.

The scalar search samples all local branches and uses the candidate nearest
the previous q when costs tie. The selected local monotonic direction,
interval, branch-continuity flag, q, strokes, and residual are exposed,
especially for Axles 5 and 6.

The fitted q is converted to front baseline position and eight rear cylinder
strokes, then passed back through MechanicalSteeringIOModel. Reported actual
angles therefore come from the formal R02-D actuator-position route rather
than directly reusing the theoretical q result.

## 7. Feasibility semantics

Feasible means the frozen mechanism remains valid and no materially mismatched
fit is pinned at the numerical verification boundary. A material residual away
from the boundary is reported as baseline_mismatch without pretending that the
ideal target was achieved. A material residual at the boundary is reported as
geometry_limited and makes the request infeasible.

The configured 0.25 deg RMS material-residual threshold is only a display
diagnostic, not an engineering accuracy criterion. An infeasible request
receives a bisection estimate of largest_feasible_scale without expanding the
q interval.

## 8. +2 deg low-speed results

Actual axle mean angles after the complete R02-D round trip:

| Preset | A1 | A2 | A3 | A4 | A5 | A6 | Feasible |
|---|---:|---:|---:|---:|---:|---:|---|
| PUBLIC | +1.963679 | +1.412696 | +0.208671 | -0.208675 | -0.110601 | -0.964268 | true |
| CUSTOMER_HINT | +1.768214 | +1.272112 | -0.949817 | -1.636369 | -0.249076 | -1.493480 | false |

Angles are degrees. PUBLIC x_ICR = -8.14 m and y_ICR = +233.389701 m.
CUSTOMER_HINT x_ICR = -4.94 m and y_ICR = +141.756429 m.

For CUSTOMER_HINT +2 deg, Axle6 reaches q6 = -0.08 rad. The request is marked
geometry_limited; largest_feasible_scale = 0.9560546875, corresponding to an
Axle1 request of approximately +1.912109 deg.

## 9. Axle5 and Axle6 diagnostics at +2 deg

PUBLIC:

| Axle | q [rad] | A stroke [mm] | B stroke [mm] | RMS target residual [deg] | Status | Branch |
|---|---:|---:|---:|---:|---|---|
| 5 | +0.04701760 | -10.86509 | -10.73344 | 1.288218 | baseline_mismatch | decreasing, continuous |
| 6 | -0.05541876 | +14.33138 | +14.52950 | 1.259680 | baseline_mismatch | increasing, continuous |

CUSTOMER_HINT:

| Axle | q [rad] | A stroke [mm] | B stroke [mm] | RMS target residual [deg] | Status | Branch |
|---|---:|---:|---:|---:|---|---|
| 5 | +0.07760424 | -17.99074 | -17.63257 | 3.391246 | baseline_mismatch | decreasing, continuous |
| 6 | -0.08000000 | +20.61305 | +21.02548 | 3.473742 | geometry_limited | increasing, continuous |

These findings are intentionally not hidden or corrected by changing CUSTOMER
geometry. Axle5 remains locally non-monotonic as found in R02-D, while Axle6
is strongly nonlinear and boundary-limited for CUSTOMER_HINT +2 deg.

## 10. Public-source boundary

docs/references/multi_axle_steering_baseline.md records the XCMG XCA500L8
public manual mode patterns plus prior multi-axle kinematics and cylinder
feedback sources. Only steering-mode architecture is borrowed. No external
vehicle hardpoints, ratios, limits, or strokes enter this model.

## 11. CLI and generated artifacts

CLI:
examples/run_vehicle_steering_demo.py

Verified command:

    & "$env:CONDA_PREFIXpython.exe" examples/run_vehicle_steering_demo.py --preset public --axle1-deg 2

Generated files:

- outputs/R02E_low_speed_counterphase_demo.png
- outputs/R02E_baseline_comparison.png
- outputs/R02E_steering_demo.csv

The CSV includes both presets at -2, -1, +1, and +2 deg. geometry_residual is
stored in radians; angle columns and Ackermann error are explicitly in degrees.

## 12. Tests

Command:

    & "$env:CONDA_PREFIXpython.exe" -m pytest -q

Result:

    53 passed in 69.01s (0:01:09)

This includes the previous 43 R01/R02-B/R02-C1/R02-D tests plus 10 R02-E
tests:

- public and customer-hint ICR sign patterns;
- Ackermann inner/outer relationship;
- left/right symmetry;
- coordinator-to-actuator q round trip;
- end-to-end MechanicalSteeringIOModel path;
- crab and front-group-only modes;
- explicit Axle5/Axle6 diagnostics;
- infeasible-request scaling.

## 13. Known issues and required CUSTOMER confirmation

- The real phase-change location/preset is not confirmed.
- No steering-wheel-to-Axle1 mapping exists; the interface intentionally uses
  target Axle1 mean angle.
- Real mechanical travel limits are unknown.
- Front actuator geometry/mapping remains an uncalibrated baseline.
- Rear sensor signs, zero offsets, and scales remain baseline values.
- Per-axle coordination gains and wheel toe/zero offsets need calibration.
- Axle5/Axle6 mismatch shows that ideal ICR targets cannot be treated as
  achieved wheel angles for the frozen mechanism.
- No speed-dependent mode eligibility or safety logic is implemented.

Minimum future synchronized CUSTOMER data should include time, steering mode,
target or measured Axle1 mean/wheel angles, rear actuator positions for Axles
3–6 (both A/B preferred), and measured wheel angles. It must also define units,
sign conventions, sensor zero/scale, calibration-versus-validation split,
vehicle speed, and confirmed mode/phase logic.
