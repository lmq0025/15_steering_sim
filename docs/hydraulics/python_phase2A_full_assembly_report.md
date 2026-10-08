# Python Phase 2-A — Full Assembly Report

## Outcome

- Bond Graph IR Freeze V3: **PASS**
- Full model assembly: **PASS**
- Ready for full FAST simulation: **YES**

## IR V3 structural correction

IR V3 restores all 65 stateful Amesim hydraulic lines as two-port power
elements. DIRECT lines remain ideal connectivity. The original 323 line states
are fully traceable, and `variableorifice_14` is no longer classified as an
ideally shorted branch.

## Assembly inventory

- Original physical states: **365**
- Original line states: **323**
- FAST total states: **109**
- FAST line states: **67**
- Power elements instantiated: **194**
- Junctions: **179**
- Power ports: **408**
- Signal links: **192**
- SC_1 composites: **10**
- Algebraic groups: **49**
- Unsupported active elements: **0**

## FAST architecture

CSV data is parsed only during initialization. Runtime objects hold frozen
element, junction, state and signal registries. State indices, port connections,
local algebraic groups and SI-converted parameter values are precomputed.
`FullHydraulicModel.rhs(t, x, inputs)` and `solve_algebraic(...)` are executable
interfaces; Phase 2-A intentionally does not perform full-system integration.
Phase 2-B will replace the current per-state neutral fallback with compiled flow
balance and local Newton kernels.

SC_1 uses the frozen signal graph with `spooldyn=1`. Feedback-shaped internal
signal wiring is registered explicitly as a static algebraic mapping and does
not introduce spool ODE states.

## Line reduction

Each physical line retains one equivalent pressure state in FAST mode. Total
volume is preserved. HL0002 retains the R-C-R interpretation, while HL011 and
HL012 retain total laminar-plus-quadratic steady pressure loss around the
equivalent compliance. No line is removed.

## Assembly checks

- every_power_element_instantiated: **PASS** — 194 active elements
- every_power_port_connected: **PASS** — 408/408
- every_referenced_junction_exists: **PASS** — 179 junctions
- no_duplicate_state_index: **PASS** — 109 unique indices
- no_missing_parameter: **PASS** — known parameter-free exact sources: FORC, PM000, TK000
- signal_graph_acyclic_or_explicitly_handled: **PASS** — 51 cyclic nodes in explicit static SC_1 algebraic mappings
- all_SC_1_modulation_inputs_resolvable: **PASS** — 28/28 internal HYDVORF0 targets
- no_unsupported_active_physical_element_silently_dropped: **PASS** — 0 unsupported
- every_C_I_state_has_RHS_provider: **PASS** — 109/109 FAST states
- every_FAST_reduced_line_has_reduction_record: **PASS** — 65/65

## Test result

`166 passed in 228.37s (0:03:48)`

## Phase 2-B entry plan

1. Compile explicit pump, source, restriction and transformer evaluations.
2. Solve only the 49 preidentified local algebraic groups.
3. Accumulate junction flows into the 109-state FAST RHS.
4. Run short BDF smoke integrations before any Amesim comparison work.
