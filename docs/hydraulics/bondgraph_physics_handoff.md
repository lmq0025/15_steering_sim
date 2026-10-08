# Bond Graph Physics Handoff

Freeze status: **CONDITIONAL PASS**

Start from these frozen artifacts:

1. `hydraulic_audit/08A..08E` — authoritative Level-1 V4 topology.
2. `hydraulic_audit/12A..12D` — level-separated Bond Graph IR.
3. `hydraulic_audit/11A_state_variable_registry.csv` — only active physical ODE states.
4. `hydraulic_audit/13A_constitutive_equations.md` — exact wrapper equations and clearly separated engineering surrogates.
5. `hydraulic_audit/11C_external_function_registry.csv` — exact-equivalence boundaries.
6. `hydraulic_audit/submodels/<SUBMODEL>/` — source paths, excerpts and instance metadata.

Do not mix SC_1 internal aliases into Level 1. Do not count activity/energy bookkeeping variables as physical states. Preserve Amesim port signs from 12B. Treat q0top_, pcdyn*, pipefr1_ and orif3f_ as unresolved exact dependencies until probed or independently specified.

Implementation order: topology/junction equations -> exact sources and mechanical inertia -> hydraulic C states -> R/MR surrogates -> SC_1 Level-2 graphs -> event/hysteresis refinement -> Amesim comparison. Do not start from names alone; every family maps to its evidence directory.
