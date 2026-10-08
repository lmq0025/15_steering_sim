# Python Phase 2-C1 Amesim Baseline Equivalence Comparison

## Executive result

Both native Amesim and Python FAST completed the same 1.0 s case. Amesim produced 1001 samples in 11.078 s; Python used the accepted dense BDF + exact algebraic cache path and completed in 33.167 s. Sparse Jacobian remained disabled.

The comparison contains **154** comparable variables: **48 GOOD**, **8 ACCEPTABLE**, and **98 POOR**. All 109 FAST initial states were derived from Amesim t=0 data; no engineering-default state remained.

## Input and initialization equivalence

The Python run did not use the generic Phase 2-B scenario. It replayed 41 measured Amesim input-port traces: individual SC_1 commands, PV00022 commands, top-level HYDVORF0 inputs, four pump speeds, and six mechanical force-source outputs. This makes the external excitation identical without modifying the Amesim model.

The audit model was closed with `AMECloseCircuit(False)`. Its SHA-256 was identical before and after both Amesim runs. The formal initial-state mapping and values are in `20C` and `20D`.

## Pump high-pressure finding

- Amesim maximum pump outlet pressure: **1.86623e+07 Pa** (186.623 bar).
- Python maximum pump outlet pressure: **2.41604e+08 Pa** (2416.036 bar).
- Classification: **PYTHON_ONLY**, not the same order of magnitude.
- First >2x / >20 MPa divergence: pump01/pump01_1 at **0.028 s**; pump01_2/pump01_3 at **0.028 s**.
- First observed locations: **V3_HJ_066, V3_HJ_068, V3_HJ_108, and V3_HJ_110**, the four pump outlet junctions.

Pump speed and ideal displacement flow agree essentially exactly, while outlet pressure and torque are POOR. This localizes the discrepancy downstream of PU001's ideal TF relation, in the pressure-control/check/relief and reduced resistance network rather than pump displacement or speed conversion. No bar-to-Pa or L/min-to-m^3/s multiplier error was detected.

## Pressure-control and CV/RV direction audit

All available CV010/RV010/RV011/HYDPRV0/PV00022 instances were evaluated using the frozen directed pressure **p2 - p1**. Opening times below are deterministic threshold diagnostics, not parameter changes:

- `pprv_1` (HYDPRV0, p2-p1): threshold 1e+06 Pa; Amesim first open NEVER s; Python first open NEVER s.
- `pprv_2` (HYDPRV0, p2-p1): threshold 1e+06 Pa; Amesim first open NEVER s; Python first open NEVER s.
- `pprv_3` (HYDPRV0, p2-p1): threshold 1e+06 Pa; Amesim first open NEVER s; Python first open NEVER s.
- `presscontrol01` (RV010, p2-p1): threshold 1.6e+07 Pa; Amesim first open 0.084 s; Python first open NEVER s.
- `presscontrol01_1` (RV010, p2-p1): threshold 9e+06 Pa; Amesim first open NEVER s; Python first open NEVER s.
- `presscontrol01_3` (RV010, p2-p1): threshold 1.5e+07 Pa; Amesim first open 0.748 s; Python first open NEVER s.
- `presscontrol02` (CV010, p2-p1): threshold 0 Pa; Amesim first open 0.001 s; Python first open 0.001 s.
- `presscontrol02_1` (CV010, p2-p1): threshold 0 Pa; Amesim first open 0.001 s; Python first open 0.001 s.
- `presscontrol02_4` (CV010, p2-p1): threshold 0 Pa; Amesim first open 0.001 s; Python first open 0.001 s.
- `presscontrol02_5` (CV010, p2-p1): threshold 0 Pa; Amesim first open 0.001 s; Python first open 0.001 s.
- `presscontrol02_8` (CV010, p2-p1): threshold 0 Pa; Amesim first open 0.001 s; Python first open 0.124 s.
- `presscontrol02_9` (CV010, p2-p1): threshold 0 Pa; Amesim first open 0.001 s; Python first open 0.182 s.
- `springcheckvalve` (CV012, p2-p1): threshold 9e+06 Pa; Amesim first open NEVER s; Python first open NEVER s.
- `valve02` (PV00022, p2-p1): threshold 200000 Pa; Amesim first open NEVER s; Python first open NEVER s.
- `valve02_1` (PV00022, p2-p1): threshold 200000 Pa; Amesim first open NEVER s; Python first open NEVER s.
- `valve02_2` (PV00022, p2-p1): threshold 200000 Pa; Amesim first open NEVER s; Python first open NEVER s.
- `valve02_3` (PV00022, p2-p1): threshold 200000 Pa; Amesim first open NEVER s; Python first open NEVER s.
- `valve02_4` (PV00022, p2-p1): threshold 200000 Pa; Amesim first open NEVER s; Python first open NEVER s.
- `valve02_5` (PV00022, p2-p1): threshold 200000 Pa; Amesim first open NEVER s; Python first open NEVER s.

The Amesim and Python opening schedules and flows do not generally coincide. The dominant attribution is the existing LEVEL C switching/pressure-control surrogate, including its reduced conductance and static opening representation. Relief thresholds themselves were read unchanged from Amesim metadata.

## SC_1 variants

Structures A/B/C/D were represented by `dirvalve_1`, `dirvalve_2`, `dirvalve_6`, and `dirvalve_3`. External command and frozen static spool position match the Amesim traces for these native inputs. Individual Amesim MR branch flows do not match the Python aggregate two-pair SC_1 flow representation; these are explicit Phase 2-C2 targets, not evidence of input reversal.

## Actuators and network

Actuator rod forces are often ACCEPTABLE while chamber pressures, displacement, and velocity are mostly POOR. Several displacement correlations retain the correct trend, but amplitude and sometimes sign differ. The error chain is consistent with upstream pressure-control/SC_1 flow mismatch. The current comparison found no new IR V3 topology contradiction; `TOPOLOGY` attribution count is zero.

The largest POOR entries include:

- `frod@springreturnactuator__vs__springreturnactuator.force_n`: NRMSE 287, correlation 0.
- `frod@springreturnactuator_1__vs__springreturnactuator_1.force_n`: NRMSE 275, correlation 0.
- `frod@springreturnactuator_2__vs__springreturnactuator_2.force_n`: NRMSE 247, correlation 0.
- `pout@pump01_3__vs__pump01_3.pout_pa`: NRMSE 7.91, correlation 0.982.
- `pout@pump01_2__vs__pump01_2.pout_pa`: NRMSE 7.91, correlation 0.982.
- `torque@pump01_3__vs__pump01_3.torque_nm`: NRMSE 7.9, correlation 0.982.
- `torque@pump01_2__vs__pump01_2.torque_nm`: NRMSE 7.9, correlation 0.982.
- `p2@hydraulic_35__vs__hydraulic_35.p2_pa`: NRMSE 7.32, correlation 0.982.
- `p2@hydraulic_34__vs__hydraulic_34.p2_pa`: NRMSE 7.32, correlation 0.982.
- `p1@hydraulic_35__vs__hydraulic_35.p1_pa`: NRMSE 7.32, correlation 0.982.
- `p1@hydraulic_34__vs__hydraulic_34.p1_pa`: NRMSE 7.32, correlation 0.982.
- `p2@presscontrol02_5__vs__presscontrol02_5.p2_pa`: NRMSE 7.1, correlation 0.981.

## Error attribution and next calibration targets

- LEVEL_C_SURROGATE records: 83 across 36 component aliases.
- INITIALIZATION records: 11. These primarily reflect algebraic boundary/reference-pressure differences even though physical storage states were aligned.
- FAST_LINE_REDUCTION records: 8.
- UNIT_OR_SIGN records: 0.
- TOPOLOGY records: 0.

Recommended Phase 2-C2 order: pressure-reference convention and tank boundary; CV/RV/HYDPRV0 conductance/opening laws; SC_1 individual MR branch flow; then line resistance/reduction. Pump q0top is not the first target because pump flow already agrees.

## Sanity and readiness

Sanity checks: **15/15 PASS**. Amesim was not saved, IR V3 and the Python physics model were not modified, 109 states remained intact, and algebraic failures were zero.

**READY FOR TARGETED CALIBRATION = YES.** No calibration was performed in Phase 2-C1.
