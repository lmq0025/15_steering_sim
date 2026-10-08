# Python Hydraulic Phase 1 Report

## 1. IR Freeze V2

**BOND GRAPH IR FREEZE V2 = PASS**

All ten entry gates in `hydraulic_audit/14A_BONDGRAPH_IR_FREEZE_V2.md` pass. The original Amesim models and the frozen 08A–08E / 10–14 V1 artifacts were not modified.

The following exact-equivalence boundaries remain intentionally open: `q0top_`, `pcdyn*`, `pipefr1_`, `orif3f_`, and related runtime event/property helpers. Phase 1 uses explicitly labelled LEVEL C surrogates.

## 2. Junction additions and corrections

- Added 13 translational mechanical 1-junctions (`TMJ_001`…`TMJ_013`).
- Added 4 rotational mechanical 1-junctions (`RMJ_001`…`RMJ_004`).
- No mechanical port is left with a placeholder `MECH_NET_*` reference.
- No external mechanical boundary was required by the present connection metadata.
- Audited all 10 SC_1 Level-2 parents for direct component/component or component/topology-node hflow connections. None exist; every parent has an explicit PASS row in `12G_level2_direct_connection_audit.csv`.
- `12C_bondgraph_junctions_v2.csv` contains Level-1 hydraulic 0-junctions, Level-2 SC_1 hydraulic junctions, translational 1-junctions, and rotational 1-junctions.
- Every row in `12B_bondgraph_ports_v2.csv` references an existing V2 junction.

Signal direction was rebuilt from component causality rather than CSV endpoint ordering. The V2 registry contains 192 verified output-to-input links. All 10 SC_1 graphs have a reachable chain from the external command through fractional-position mapping and VALVEDYNAMICS0 to every internal HYDVORF0 modulation input.

## 3. Python package structure

Phase 1 adds these layers under `src/steering_sim/hydraulics` while preserving the earlier R03-B1 evidence wrappers:

```text
hydraulics/
    units.py
    fluid.py
    states.py
    surrogates.py
    elements/
        sources.py
        pump.py
        accumulator.py
        cylinder.py
        line.py
        restriction.py
        valves.py
        mechanics.py
    graph/
        junctions.py
        topology.py
        ir_loader.py
    equations/
        residuals.py
        rhs.py
    solver/
        model.py
```

All core calculations use SI: Pa, m³/s, N, m/s, N·m, rad/s, m, m², m³ and Pa bulk modulus. Amesim conversions are confined to `units.py` and parameter/IO construction.

## 4. Implemented elements

READY_EXACT Phase-1 primitives:

- hydraulic 0-junction pressure equality and flow balance;
- translational/rotational mechanical 1-junction common-flow and effort balance;
- TK000 constant-pressure source;
- PM000 constant-angular-speed source;
- FORC modulated force source;
- MAS001 translational inertia and displacement kinematics.

READY_APPROX primitives:

- PU001 fixed-displacement transformer with `q0top=1`;
- HA001-style polytropic gas accumulator core;
- HJ020, HJ021 and HJ0022 cylinder geometry, force, leakage and two chamber pressure states;
- HL0000 lumped compliance, HL0002 R-C-R form, and multi-cell HL011/HL012 skeletons;
- HYDORF0 fixed restriction and HYDVORF0 modulated restriction;
- calibrated laminar-plus-quadratic pipe loss.

Complex valve hysteresis, complementarity, cavitation and exact Amesim event surfaces are deferred.

## 5. Surrogate policy

All substitutes are centralized in `surrogates.py`:

- `q0top(p) = 1`;
- chamber/line compliance: `dp/dt = beta_eff*q_net/V`;
- smooth orifice:

  \[
  q=C_d A\sqrt{\frac{2}{\rho}}\frac{\Delta p}{(\Delta p^2+\epsilon_p^2)^{1/4}},
  \]

  which is finite and differentiable at zero and asymptotically approaches the standard signed square-root law;
- pipe loss: `Delta p = R_lam*q + R_quad*q*abs(q)` with an analytical inverse.

These are LEVEL C engineering surrogates, not claims about the private Amesim function implementations.

## 6. Unit and integration tests

Required tests were added under `tests/hydraulics`:

- `test_units.py`
- `test_pu001.py`
- `test_hydraulic_junction.py`
- `test_mechanical_junction.py`
- `test_hj020.py`
- `test_orifice.py`
- `test_line_compliance.py`
- `test_ir_integrity.py`

An additional `test_minimal_loops.py` checks both BDF prototypes.

Command executed:

```powershell
& "E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe" -m pytest -q
```

Final result:

```text
150 passed in 81.24s (0:01:21)
```

The first sandboxed full run had 149 tests pass and one unrelated existing test fail because its temporary output directory was denied write access. Re-running the identical command with workspace temporary-file permission produced the clean result above.

## 7. Minimal loop results

Both loops use `scipy.integrate.solve_ivp(method="BDF")`. Raw results are stored in `hydraulic_audit/15A_python_phase1_minimal_loop_results.json`.

### Constant speed → PU001 → compliance/restriction → tank

- Result: PASS
- States: one pressure
- Duration: 0.05 s
- Initial pressure: 100,000 Pa
- Final pressure: 5,005,172.80 Pa
- Solver samples: 143

### Pressure source → orifices → HJ020 → mass/load → tank

- Result: PASS
- States: `[p1, p2, x, v]`
- Duration: 0.02 s
- Initial: `[100000 Pa, 100000 Pa, 0.15 m, 0 m/s]`
- Final: `[1616604.89 Pa, 1219704.58 Pa, 0.150213828 m, 0.0141390 m/s]`
- Solver samples: 169

Both runs remained finite, respected SI units, and exercised pressure, flow, force, leakage, mechanical acceleration and stiff state integration.

## 8. State-vector design

Phase 1 uses explicit, component-owned physical states only:

- hydraulic compliance: pressure;
- HJ cylinders: chamber pressures `p1`, `p2`;
- segmented lines: one pressure per compliance cell;
- mechanical inertia: displacement and velocity;
- second-order valve dynamics, when enabled later: position and velocity.

The frozen full-system registry remains 365 states (339 hydraulic, 14 mechanical, 12 control), but Phase 1 deliberately does not assemble that vector. Activity/energy bookkeeping variables remain excluded.

## 9. Algebraic variables and ODE/DAE form

Current prototypes eliminate local algebraic variables explicitly:

- pump flow and torque are algebraic functions of speed and pressure;
- orifice and pipe flows are algebraic functions of pressure difference/opening;
- cylinder force and leakage are algebraic functions of pressures, position and velocity;
- state derivatives are explicit after those evaluations.

Consequently the two Phase-1 rigs are index-0 explicit ODE systems integrated by BDF. The graph layer also exposes residual functions for hydraulic 0-junctions and mechanical 1-junctions. Full network assembly will generally form a semi-explicit DAE:

\[
\dot x=f(x,z,u), \qquad 0=g(x,z,u),
\]

where `x` holds physical storage/inertia states and `z` holds junction pressures, branch flows and constraint efforts.

## 10. Phase 2 / Amesim comparison plan

1. Load V2 elements, ports and junctions into a full graph assembler without changing the frozen IR.
2. Assemble sparse residual/Jacobian structures and verify component sign conventions on small subgraphs.
3. Probe `q0top_`, pressure-compliance, orifice and pipe behavior using the audit model without saving it; store raw probe data as NUMERIC SURROGATE evidence.
4. Replace centralized surrogates one family at a time and run parameterized component comparisons.
5. Add complex valve hysteresis/event logic and SC_1 variant tables.
6. Only then assemble the 365-state model and compare selected Amesim trajectories.

## Completion summary

```text
BOND GRAPH IR FREEZE V2 = PASS
PHASE 1 TESTS = 150 passed
MINIMAL HYDRAULIC LOOP = PASS
ACTUATOR LOOP = PASS
READY FOR FULL SYSTEM ASSEMBLY = YES
```

“YES” means ready to begin controlled graph/DAE assembly; it does not claim exact Amesim equivalence.
