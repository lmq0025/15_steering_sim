# Phase L1-R3 — 集中参数供油网络与 SC_1 四孔口映射修复

## Executive conclusion

Phase L1-R3 completed the requested structural repair without returning to the legacy 109-state model. The runtime remains **4 channels / 16 dynamic states / 0 pipe states**. The former Python-only chamber-pressure failure fell from **384.663 MPa** to **2.065 MPa**, naturally, with no pressure clamp or artificial leakage. The comparable Amesim maximum across all four actuator chambers and S0/S1/S2 is **1.672 MPa**.

The structural result is successful, but the validation result remains **CONDITIONAL**: only **10/54** deduplicated direct observations meet the 10% dynamic NRMSE gate. Therefore this delivery is **not ready for mechanical integration** and is conservatively marked **not ready for L2 calibration** until the remaining zero-to-pressure transient and low-flow `orif3f_` boundary are explicitly accepted.

## 1. What caused the hundreds-of-MPa chamber pressure

The failure was not pump displacement and was not fixed by clipping. Four structural transcription errors compounded:

1. The old valve used one area and a sign switch instead of four independent P-A/P-B/T-A/T-B tables.
2. It used `max(flow, 0)` on supply branches even though HYDVORF0 is bidirectional.
3. It assumed local SC_1 `P` was supply and `T` was tank. Direct Amesim port extraction proves the installed wrappers are reverse-fed in these scenarios: local `T` is the high rail and local `P` is the low return rail.
4. Most importantly, HJ020/HJ021 continuity was transcribed with the mechanical terms reversed. Amesim source uses `q1 + A1*v` and `q2 - A2*v`, with internal travel `xact=c2-x`. The old code used the opposite signs and opposite chamber-volume direction. Prescribed Amesim motion therefore compressed the wrong chamber against a missing discharge path.

Correcting these relations reduced the S1 pressure failure before any broad parameter fit. Evidence is retained in `33A`, `33H`, HJ020 source evidence, and the new tests.

## 2. Actual SC_1 four-port mapping

Level-2 IR gives:

- `orifice_14`: external port 0 ↔ 3, P-A;
- `orifice_13`: external port 0 ↔ 2, P-B;
- `orifice_24`: external port 1 ↔ 3, T-A;
- `orifice_23`: external port 1 ↔ 2, T-B.

`dirvalve_1/8/11` share the transferred four-table family, `dirvalve_6` has the crossed table family, and `dirvalve_2/9/12` contain only P-A and T-B. Each branch is evaluated separately and preserves reverse flow. The seven-instance mapping is in `33B`; reverse-flow evidence is in `33C`.

The metadata characteristic is 1 L/min at 1 bar, but the private `orif3f_` body is unavailable. S0 directly identifies an operating-range scale of 1.425; S1/S2 validate the main branches. Of 66 measured endpoint comparisons, **63 pass** and **3 fail**. All three failures are the 10%-open P-B branch in S1, where laminar-transition behavior is not reproduced. This is why SC_1 port-flow validation is `CONDITIONAL`, not a false exact pass.

## 3. Supply algebraic network

The new state-free network distinguishes:

- pump outlet sensor;
- RV010 high-pressure inlet / HYDPRV0 upstream rail;
- each HYDPRV0 regulated SC_1 T rail;
- SC_1 P / relief outlet return rail;
- tank at 0 Pa gauge.

Pressure losses are not one universal `R_eq`. Front and rear pump-outlet paths and returns use separate S0-identified resistances, with S1/S2 reserved for validation. The rear group also includes a measured 4.47 L/min macro auxiliary flow: `pump - Σpprv - relief`, stable across S0/S1/S2. It represents real omitted control/spring-return branches and is reported explicitly rather than hidden as leakage.

All sampled pump, relief, and return node balances pass. Worst dimensional residual is **8.383e-10 m³/s**. There is no pressure hard clip; root failure is explicit.

## 4. Paired S0/S1/S2 validation

All Amesim scenarios are frozen successful oracles. Python uses their measured commands, pump speeds, initial chamber states, and prescribed HJ020/HJ021 mechanical boundary. Position and velocity are therefore inputs, not independent predictions.

Evidence was reclassified and deduplicated. Shared pump pressure is counted once per supply group; hydraulic force and P/T totals are derived consistency, not extra independent samples. Direct independent observations are the eight chamber pressures, two group pump-outlet sensors, and two work-port flows per primary valve for each scenario.

- `pA`: 0/12 within 10%
- `pB`: 0/12 within 10%
- `pump_outlet_pressure`: 0/6 within 10%
- `q_A`: 1/12 within 10%
- `q_B`: 9/12 within 10%

Steady S1 rear chamber errors are much smaller than full-transient NRMSE, but the algebraic supply pressure rises immediately whereas Amesim contains omitted supply compliance. That zero-to-pressure transient is the main remaining macro mismatch. Adding a supply state is not done here because its volume/time-constant evidence has not yet been frozen.

## 5. Performance

With cached input replay and 0.5 ms RK4, actual 1 s paired runs were:

- S1: 4.469 s wall time;
- S2: 4.512 s wall time.

The actual 100 s periodic S2 run took **458.563 s**, reached 100 s physical time, and remained finite with maximum chamber pressure **2.074 MPa**. This is only 0.218× realtime. Performance is therefore not an R3 pass and should be optimized only after the remaining physics boundary is accepted.

## 6. Regression and safety

- Pump displacement/speed law unchanged; pump-flow regression PASS.
- Dynamic state count 16; pipe dynamic states 0.
- IR V3 unchanged.
- Protected model SHA-256 remained `7613615723973d66a7122c74956c5161f720a64b243139fe9736cb270303b767` for both protected files.
- Amesim runs used isolated copies and closed without saving protected models.
- Full repository: **222 passed**.

## 7. Remaining issues and next decision

1. Resolve or accept a low-flow `orif3f_` surrogate for the three small P-B observations.
2. Decide whether a single evidence-backed supply compliance state is necessary to reproduce the 0–0.1 s pump-pressure rise. This would be a documented macro structural change, not a pipe-state rollback.
3. Only after that decision, perform small-parameter L2 identification; do not fit Cd, bulk modulus, mass, damping, and all path resistances simultaneously.
4. Mechanical integration remains blocked because motion is replayed from Amesim and not independently predicted.

## Final status

- SC1 AREA TABLE TRANSFER: **PASS**
- SC1 PORT FLOW VALIDATION: **CONDITIONAL**
- SUPPLY ALGEBRAIC MAPPING: **PASS**
- ALL NODE FLOW BALANCES: **PASS**
- S0/S1/S2 DYNAMIC REGRESSION: **CONDITIONAL**
- READY FOR L2 TARGETED CALIBRATION: **NO**
- READY FOR MECHANICAL INTEGRATION: **NO**
