# Python Phase 2-C2A — Pressure-Control Targeted Calibration

## Executive result

Phase 2-C2A is **partially successful but does not meet the pump-pressure acceptance target**.

- Pressure reference audit: PASS.
- TK000 tank boundary: PASS; implemented as an exact `p = 0 Pa gauge` effort boundary.
- Runtime pressure-control binding: PASS, 31/31 hydraulic ports match IR V3.
- CV010 source law and SI gradient: PASS.
- RV010 source law and SI gradient: PASS at element level, but system opening schedule remains FAIL because pressure does not reach the RV high-pressure ports.
- Pump displacement flow regression: PASS; all four pump flow time series are unchanged to numerical precision.
- FAST state contract: unchanged at 109 states; FAST line states remain 67.
- IR V3: unchanged.

The accepted C2A changes improve the 154-variable comparison from 48 GOOD / 8 ACCEPTABLE / 98 POOR to **63 GOOD / 5 ACCEPTABLE / 86 POOR**, but maximum Python pump pressure remains **241.181 MPa**, versus **18.662 MPa** in Amesim (ratio 12.923).

`READY FOR SC1 / LINE CALIBRATION = NO` under the requested gate because the high-pressure anomaly is not resolved. The remaining causal evidence points to the frozen FAST line/path resistance representation, not PU001 or an RV cracking-pressure parameter.

## Frozen comparison setup

All stages reused the Phase 2-C1 oracle and setup:

- Amesim baseline: `20E_amesim_baseline_timeseries.csv` / `20_amesim_raw_1s.json`.
- Identical input replay from `20_amesim_request.json`.
- Identical 109/109 mapped initial states from `20D_initialization_alignment.csv`.
- Duration 1.0 s and 1001-point comparison grid.
- Dense BDF with exact algebraic cache; rejected sparse Jacobian remained disabled.
- No Amesim model was opened, modified, or saved in this phase.

## Findings and accepted fixes

### 1. Pressure convention and tank boundary

Amesim hydraulic port variables are gauge pressures. `TK000.c` defines a fixed tank pressure in bar and validates its lower limit against negative atmospheric pressure. CV010/RV010 use `p2-p1`; absolute pressure is formed only where property/energy functions require `p + patm`.

The Python runtime previously used 100 kPa as both the initial algebraic reference and tank target. It now uses 0 Pa gauge. TK000 was also corrected from a large finite conductance to an exact algebraic pressure-source constraint. This removed the duplicated atmospheric offset without altering pressure-difference laws.

### 2. Runtime binding

The V3 hydraulic ports and compiled runtime ports agree for CV010, RV010, RV011, HYDPRV0, and CV012. The audit correctly handles non-contiguous physical port IDs such as RV011 hydraulic ports 0 and 2. There is no runtime topology/binding fault.

### 3. CV010

Source evidence gives:

\[
\Delta p_h = p_2-p_1-p_{crack},\qquad
q_1 = G\max(\Delta p_h,0),\qquad q_2=-q_1
\]

with

\[
G = grad\times 1.66666666666667\times 10^{-10}
\quad [\mathrm{m^3\,s^{-1}\,Pa^{-1}}].
\]

For `grad = 500 L/min/bar`, `G = 8.3333333333e-8 m^3/s/Pa`. The old runtime used `8e-11`, about 1042 times smaller, plus a nonzero smooth pre-opening flow. All model CV010 instances have zero hysteresis, so the accepted implementation uses the deterministic zero-hysteresis lower limit.

### 4. RV010

RV010 uses the same directed pressure and SI gradient conversion, with its frozen cracking pressure. No cracking-pressure fitting was performed. The element law is corrected, but `presscontrol01` and `presscontrol01_3` remain closed in the system run because their `p2` pressures remain far below 16 MPa and 15 MPa respectively.

## Staged results

| Stage | Change | Max pump pressure | GOOD / ACCEPTABLE / POOR | RV opening |
|---|---|---:|---:|---|
| C2A-0 | Frozen C1 baseline | 241.604 MPa | 48 / 8 / 98 | both NEVER |
| C2A-1 | Gauge reference + exact tank boundary | 241.618 MPa | 62 / 5 / 87 | both NEVER |
| C2A-2 | CV010 source gradient/law | 241.182 MPa | 62 / 5 / 87 | both NEVER |
| C2A-3 | RV010 source gradient/law | 241.181 MPa | 63 / 5 / 86 | both NEVER |
| C2A-4 trial | HYDORT0/HYDORF0 path R replacement | rejected | not accepted | 0.1 s passed; 1 s developed NaN/Inf |

The C2A-4 trial was not activated in the production defaults. No clipping or hard pump-pressure limit was introduced.

## Where the remaining error starts

The first remaining pressure mismatch is before the first retained FAST line pressure cell:

- Python pump01 outlet junction at 1 s: about 241.18 MPa.
- Python first `hydraulic/HL012` retained pressure state: about 229.94 MPa.
- Artificial interface drop: about 11.24 MPa.
- Amesim pump outlet and physical-line inlet are essentially coincident near 18.662 MPa; the corresponding line-end drop is only about 1.18 kPa.

Downstream, the accepted generic R surrogates compound the separation. At 1 s in the first pump path, the Python `filter/HYDORT0` surrogate drops roughly 181 MPa and `flowcontrol01_1/HYDORF0` roughly 23 MPa, while the Amesim path drops only several bar before pressure reaches `presscontrol01.p2`. Consequently:

- Amesim `presscontrol01.p2` reaches about 17.172 MPa and opens at 0.084 s.
- Python `presscontrol01.p2` reaches only about 2.99 MPa and never opens.
- Amesim `presscontrol01_3` opens at 0.748 s.
- Python `presscontrol01_3.p2` reaches only about 1.78 MPa and never opens.

Therefore the incorrect valve schedule is a downstream symptom: the high pressure is stranded upstream by the FAST line-interface and path-resistance representation.

## RV011 and HYDPRV0

They are classified `NOT_PRIMARY`. Neither is the first cause of the divergence, and neither law was changed. Retuning them would conceal the upstream pressure-propagation error.

## Regression protection

- Pump speed/displacement law: unchanged.
- Pump qout: exact match before versus after for all four pumps (`max_abs_difference = 0`).
- Input replay: unchanged.
- Initial-state mapping: unchanged.
- State counts: unchanged.
- IR V3 SHA-256 values are recorded in `21O_phase2C2A_results.json`.
- No hard pressure clamp, artificial leakage, or relief-pressure retuning was used.

## Required next action

Do not proceed to SC_1 calibration yet. The next targeted task should isolate and correct the FAST line endpoint/interface resistance and the pressure-control-path HYDORT0/HYDORF0 evaluation while preserving the 67 line states. The rejected combined C2A-4 trial shows that replacing both nonlinear R laws at once is numerically unsafe; they should be introduced independently with local algebraic convergence tests and 0.1 s → 1.0 s gates.

## Artifact index

The complete evidence set is `hydraulic_audit/21A` through `21O`; plots are in `outputs/hydraulics/phase2C2A/`.

## Final status

**PRESSURE-CONTROL ELEMENT CORRECTIONS = ACCEPTED**

**PUMP HIGH-PRESSURE TARGET = FAIL**

**READY FOR SC1 / LINE CALIBRATION = NO**

---

## C2A continuation: isolated line/path calibration

This continuation started from the accepted C2A-3 workspace. It did not repeat C2A-0 through C2A-3 and did not change IR V3, the 109-state vector, or the 67 line states.

Final full-suite verification: **190 passed in 108.19 s**. The earlier single failure was an execution-sandbox permission denial while a legacy mechanics test wrote `outputs/test_tmp`; it was not a stale tank-boundary assertion. Re-running with normal workspace write permission passed without changing that test or reverting the exact TK000 boundary.

### FAST line-interface audit

The audit confirms a structural approximation error in the runtime reduction. Phase 2-B assigned fixed interface conductances (`5e-10` for HL0000 and `2e-11 m^3/s/Pa` for the other line families), independent of diameter, length, viscosity, or the frozen line-reduction map. For a one-cell line this creates two complete interface resistances. For multi-cell lines the internal conductance was additionally divided by cell count, so total loss was not derived from the original total line resistance.

Using the model metadata (`d_h=25 mm`, `L=1 m`) and fluid data (`rho=883 kg/m^3`, `nu=56.47 cSt`) gives a laminar total resistance around `5.2e6 Pa/(m^3/s)`, consistent with the Amesim baseline line drop. The former one-cell HL012 runtime resistance was `1e11 Pa/(m^3/s)`, about four orders of magnitude larger. HL0000 is a pure C source model and should have no pipe resistance at all.

`21P_fast_line_interface_audit.csv` records all 65 instances. `21Q_line_pressure_drop_comparison.csv` records the pump-path line drops at 0.010, 0.020, 0.028, 0.050, 0.084, and 0.100 s.

### Family-isolated trials

| Stage | Enabled correction | Peak pressure | GOOD / ACCEPTABLE / POOR | Algebraic failures | Decision |
|---|---|---:|---:|---:|---|
| C2A-5A | HL0000 | 241.179 MPa | 63 / 5 / 86 | 0 | stable; negligible system effect |
| C2A-5B | + HL0002 | 241.169 MPa | 63 / 5 / 86 | 0 | stable; negligible effect |
| C2A-5C | + HL011 | 241.155 MPa | 63 / 5 / 86 | 0 | stable; negligible effect |
| C2A-5D | + HL012, conservative FAST cap | 227.892 MPa | 58 / 6 / 90 | 0 | rejected: only 5.5% pressure reduction and accuracy regression |

HL012 is the largest contributor. Direct source-equivalent resistance mapping makes the single-cell pole microsecond-scale and causes NaN/Inf through the coupled HA001 state before 0.1 s. A conservative fivefold conductance trial is stable, but it remains far from the Amesim drop and worsens comparison counts. It is retained only as evidence and is not enabled in the accepted runtime defaults.

### HYDORT0

`21S_HYDORT0_dp_q_evidence.csv` records the exact knots from `q_dP_coolant_sym.data`. The former fixed-conductance surrogate can create about 181 MPa drop in the first pump path where the table implies only several bar.

HYDORT0 was isolated after the line trials. Replacing it with its piecewise table law passes 0.1 s, but the 1 s run causes an HA001-coupled pressure-state overflow/NaN. A square-root extrapolation outside the table range did not remove the structural instability. The change is rejected; no flow or pressure clipping was added.

### HYDORF0

`21T_HYDORF0_dp_q_evidence.csv` records the frozen area/Cd/density engineering law versus the old generic conductance. Per the staged gate, HYDORF0 was not enabled after isolated HYDORT0 failed its 1 s stability gate. It therefore remains `NOT_RUN`, not falsely reported as calibrated.

## Final answers

1. The gauge/tank correction improved the classification from 48/8/98 to 62/5/87, but changed peak pump pressure by only about +0.014 MPa; it fixed the reference convention, not the high-pressure cause.
2. CV010/RV010 SI-law corrections moved the accepted result to 63/5/86 and reduced peak pressure by about 0.437 MPa relative to the tank-only stage. They did not open the RVs because pressure still does not propagate to their high-pressure ports.
3. Yes, the FAST line interface contains a large artificial resistance not derived from line parameters.
4. HL012 contributes the largest line-family effect; it is present directly after all four pump outlets.
5. HYDORT0 is a major remaining path-pressure suspect by static `dp-q` evidence, but its isolated correction is not numerically acceptable with the current HA001 coupling.
6. HYDORF0 also needs eventual correction, but it was not allowed past the failed HYDORT0 gate.
7. Final **accepted** Python maximum pump pressure is **241.181 MPa**. The stable but rejected capped-line trial reached 227.892 MPa.
8. Accepted Python/Amesim peak ratio is **12.923**.
9. `presscontrol01` and `presscontrol01_3` remain `NEVER`; Amesim opens them at 0.084 s and 0.748 s.
10. Final accepted comparison is **GOOD 63 / ACCEPTABLE 5 / POOR 86**.
11. No topology or sign issue remains; the identified CV/RV unit issue is fixed. Remaining errors are reduced-model resistance distribution and coupled numerical structure.
12. The model is **not ready for SC_1 branch calibration**. The line/path correction hits the explicit stop condition: source-equivalent resistance causes structural instability, while the stable cap fails the accuracy regression.

## Continuation final status

**FAST LINE INTERFACE AUDIT = PASS**

**FAST LINE CALIBRATION = FAIL (REJECTED)**

**HYDORT0 CALIBRATION = FAIL (REJECTED)**

**HYDORF0 CALIBRATION = NOT RUN (GATE FAILED)**

**READY FOR SC1 CALIBRATION = NO**
