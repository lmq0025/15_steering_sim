# Bond Graph Physics Freeze Report

**FREEZE STATUS = CONDITIONAL PASS**

## 1. Executive summary

The frozen V4 Level-1 hydraulic topology is preserved as the baseline (59 canonical hydraulic 0-junctions, 174 line-mediated component edges, 0 pump same-junction errors). A new read-only sanity check found top-level direct hflow connections without an intervening line object; 12B/12C apply a traceable correction without modifying 08A–08E. This audit adds source-backed family constitutive definitions, active physical states, a level-separated Bond Graph IR, and explicit Amesim-runtime implementation boundaries. No Amesim model was modified, saved, or simulated.

The model metadata contains **47 unique submodel identifiers**. After separating connections, topology, signal and configuration objects, the physical implementation is conditionally ready: simple sources/topology/mechanics are exact, while real-fluid pressure dynamics, line friction and orifice laws depend on non-shipped Amesim runtime functions. Engineering surrogates are specified but are not presented as source truth.

## 2. Actual submodel population

- Unique submodels: 47
- Source-matched exact-name submodels: 45 (SC_1 is a model-defined supercomponent; DIRECT is connection metadata)
- Physical power-family element instances in IR: 129
- Signal-family instances: 153
- Non-power objects: 3

## 3. Fully determined families

Source-closed or algebraically closed families include hydraulic topology nodes, TK000 reservoir, HYDPG0 gauge, constant/sine/step/splitter/sum/remote signal blocks, FORC, PM000, and MAS001. Their exact equations are in 13A.

## 4. Partially determined families

PU001, accumulators, cylinders, hydraulic lines, restrictions, check/relief/reducing/proportional valves and MAS004 have direct source-level wrapper equations but call Amesim runtime functions whose ordinary source definitions were not found. They are READY_APPROX, with exact call-level equations preserved and explicit engineering surrogates separated as LEVEL C.

## 5. Unresolved / blocked boundary

- No whole submodel is left without a strategy; exact equivalence remains blocked at registered runtime functions.

## 6. Level 1 system topology

- Status: PASS WITH TRACEABLE DIRECT-CONNECTION CORRECTION.
- Frozen V4 top-level hydraulic nets: 177
- Frozen V4 canonical hydraulic junctions: 59
- Frozen V4 line-mediated component edges: 174
- Corrected IR Level-1 junctions/connectors: 60
- Corrected IR hydraulic component ports: 188
- Direct-connection evidence rows: 13
- Pump merged-port errors in corrected IR: 0
- Actuator merged-chamber errors in corrected IR: 0

The correction merges two pairs of directly connected topology-node junctions, adds component ports directly attached to topology nodes, and creates a two-bond zero-junction for the direct springreturnactuator_1–variableorifice_6 connection. Details are in 10D; 08A–08E remain unchanged for provenance.

## 7. Level 2 SC_1 supercomponents

- Status: PASS for layer separation and internal mapping; constitutive exactness remains conditional on HYDVORF0 runtime functions.
- Instances: 10
- Structural variants: 4
- SC_1_structure_A: dirvalve_1, dirvalve_8, dirvalve_11
- SC_1_structure_B: dirvalve_2, dirvalve_9, dirvalve_12
- SC_1_structure_C: dirvalve_6
- SC_1_structure_D: dirvalve_3, dirvalve_10, dirvalve_13
- Fully parameterized variants: 10
- SC_1_variant_A: dirvalve_1
- SC_1_variant_B: dirvalve_2
- SC_1_variant_C: dirvalve_6
- SC_1_variant_D: dirvalve_3
- SC_1_variant_E: dirvalve_8
- SC_1_variant_F: dirvalve_9
- SC_1_variant_G: dirvalve_10
- SC_1_variant_H: dirvalve_11
- SC_1_variant_I: dirvalve_12
- SC_1_variant_J: dirvalve_13

All wrappers are represented only as COMPOSITE at Level 1. Their internal VALVEDYNAMICS0, tables, MR branches and internal hydraulic 0-junctions occur only at Level 2. Current wrapper and internal metadata use `spooldyn=1`; source array sizing proves no active spool ODE state for these SC_1 instances. Instances within one structural template can still have different lookup expressions or parameter values; 10C records both signatures.

## 8. Physical states

- TOTAL NUMBER OF PHYSICAL STATES: 365
- Hydraulic states: 339
- Mechanical states: 14
- Control states: 12

Amesim activity/energy accounting integrals, linked constants, fixed tank pressure, fixed prime-mover speed, the gauge's identically-zero flow, zero-sized optional state arrays, and SC_1 wrapper aliases of internal variables are excluded from the physical ODE/DAE state count. The complete instance-level registry is 11A.

## 9. Bond Graph element statistics

- C: 2
- I: 1
- MR: 44
- R: 24
- Se: 11
- Sf: 4
- TF: 4
- composite subgraph: 39
- environment/configuration object: 1
- non-power property object: 2
- signal block: 153

## 10. Exact versus simplified boundary

Exact wrapper equations and SI conversions are transcribed from source. Engineering equations replace q0top_ by 1 only where pressure-dependent reference-volume correction is acceptably small; pcdyn functions by beta_eff/V compliance; orif3f_ by a regularized incompressible orifice; pipefr1_ by calibrated laminar/Darcy loss; and proprietary valve/friction helpers by mode-specific state equations. These substitutions require later Amesim comparison before claiming equivalence.

For the model's elementary hydraulic fluid, the metadata gives density 850 kg/m^3, bulk modulus 17000 bar, 0.1% gas content, polytropic index 1.4, and saturation pressure 1000 bar for dissolved gas. Under a constant-bulk, single-phase LEVEL C estimate, mass conservation suggests `q0top(p) ≈ rho(p)/rho(0) ≈ exp(p/B)`: about 1.006 at 100 bar and 1.012 at 200 bar. Thus q0top≈1 is typically a sub-percent-to-about-one-percent approximation over 0–200 bar for the liquid-only constant-bulk estimate, but it is not valid evidence near cavitation/aeration transitions and is not frozen as Amesim's actual implementation. A later numeric probe should sample at least -1, 0, 1, 10, 50, 100 and 200 bar and store raw values as NUMERIC SURROGATE data.

## 11. External Amesim dependencies

- `q0top_`: volume-flow correction between local pressure and reference-pressure volume — BLOCKED_BY_LIBRARY_FUNCTION
- `pcdyn2_`: hydraulic pressure derivative with real-fluid compressibility/cavitation — BLOCKED_BY_LIBRARY_FUNCTION
- `pcdyn02_`: line pressure derivative with wall compliance — BLOCKED_BY_LIBRARY_FUNCTION
- `pcdyn03_`: line pressure derivative with tabulated hose properties — BLOCKED_BY_LIBRARY_FUNCTION
- `pipefr1_`: quasi-steady hydraulic line friction/flow — BLOCKED_BY_LIBRARY_FUNCTION
- `orif3f_`: real-fluid laminar/turbulent orifice flow — BLOCKED_BY_LIBRARY_FUNCTION
- `valvedyn_/valvedyn2_`: limited/hysteretic optional first/second-order spool law — READY_WITH_APPROXIMATION
- `linert_`: translational inertia with friction/stiction — READY_WITH_APPROXIMATION
- `getatp_`: atmospheric absolute pressure — READY_WITH_APPROXIMATION

## 12. Special finding: variableorifice_14

**EXPLAINED.** V4 maps both HYDVORF0 hydraulic ports to SHJ_003 because the raw model contains an ideal parallel path `hydraulic_165 -> hydrnode4_1 -> hydraulic_166 -> hydrnode3_21 -> hydraulic_164`. Source HYDVORF0 computes passive orifice flow from `p3-p2`; the ideal parallel connection enforces zero pressure difference, hence this branch is statically shorted and carries zero constitutive flow (apart from numerical regularization). It is retained in the IR as a modulated R with both ports on the same 0-junction and flagged as model-construction redundancy/bypassed branch; no dynamic test is required to establish the topology.

## 13. Open issues

- q0top_ implementation remains an explicit library boundary. The most plausible reconstruction route is a density/reference-volume ratio, but this is not frozen as truth until a numeric probe or authoritative definition confirms it.
- pcdyn2_/pcdyn02_/pcdyn03_, pipefr1_, orif3f_ and several event/hysteresis helpers are DLL/runtime dependencies.
- Exact event surfaces and cavitation behavior require numeric probing if exact Amesim reproduction is demanded.
- No simulation probe was run because source and topology evidence were sufficient for classification; probing is deferred to the equivalence-validation stage.

## 14. Acceptance

- Level 1 topology: PASS
- Level 2 supercomponents: CONDITIONAL
- Sanity checks: 10/10 PASS
- READY_EXACT families: 10
- READY_APPROX families: 21
- BLOCKED families: 0
- SIGNAL_ONLY families: 12
- NON_POWER families: 4

**FREEZE STATUS = CONDITIONAL PASS**

This is sufficient to hand off a traceable Bond Graph implementation plan, but not to claim bitwise Amesim equivalence. Exact equivalence is conditional on resolving or numerically characterizing the registered runtime functions.
