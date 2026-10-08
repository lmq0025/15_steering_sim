# Python Phase 2-B.5 Performance Optimization Report

## Outcome

- Physics model changed: **NO**
- FAST states: **109**; FAST line states: **67**
- Algebraic groups: **49**; failures: **0**
- Accepted optimization: exact dependency-signature algebraic cache
- Fresh-model baseline median: **54.328722 s** per 1 s physical time
- Accepted median: **27.190209 s** per 1 s physical time
- Speedup against corrected baseline: **1.998x**
- Speedup against the Phase 2-B reported 150.886670 s: **5.549x**
- Physics regression: **PASS**, maximum scaled relative error **0**
- Physical sanity: **14/14 PASS**
- Pytest: **183 passed**

## Baseline correction

The initial 19A capture combined timing from `18E` with a trajectory produced by a different sequential initialization path in `18I`. That capture is retained as `19A_performance_baseline_legacy_capture.json` and is not used as the regression oracle. The authoritative `19A_performance_baseline.json` uses three fresh model instances with identical initial state, steering-like input, BDF settings, tolerances, and 51 output times. All three repeats had identical `nfev=2424`, `njev=157`, and `nlu=665`.

## Jacobian sparsity and stop condition

The automatically generated 109×109 dependency matrix has **987 nonzeros**, **8.307% density**, 13 connected blocks, and **27 colors**. It is derived from state ownership, local algebraic groups, junction adjacency, mechanical 1-junctions, signal inputs, and transitive cross-group hydraulic branches. Sampled finite differences found zero missing structural entries.

However, enabling SciPy `jac_sparsity` changed the 1 s trajectory:

- sparse + exact cache median: 14.192988 s;
- maximum scaled physics error: 0.815403;
- regression: **FAIL**.

This triggered the requested stop condition. Sparse colored finite differences are rejected and disabled by default. P3 local analytic blocks and P4 global sparse assembly were not pursued to conceal the failed equivalence gate.

## Accepted algebraic cache

Each group cache key contains exact bytes for all dependent physical states plus all resolved signal inputs. Dependency sets close transitively across the two cross-group hydraulic branches. A state perturbation therefore invalidates affected groups while unrelated groups reuse their previous solution. The accepted three-run benchmark recorded:

- algebraic evaluations: 894,830;
- actual solves: 107,467;
- cache hits: 787,363;
- cache hit rate: **87.99%**;
- physics regression: **exact match** at all 100 final/peak/RMS/timeseries checks.

## Performance targets

- ≤20× realtime: **FAIL** (27.190×)
- ≤5× realtime: **FAIL**
- ≤1× realtime: **FAIL**

The accepted path is materially faster and numerically equivalent, but it does not reach the minimum runtime target. The remaining bottleneck is dense numerical Jacobian evaluation plus repeated parameter/geometry work inside the RHS. Those are recorded for a future optimization round; no physics, tolerance, state, or line-fidelity changes were made here.

## Verification and readiness

All mandatory correctness gates pass:

- 109/109 RHS entries supplied;
- zero NaN/Inf;
- pressure and stroke checks pass;
- mass-balance check passes;
- zero algebraic failures;
- 100/100 physics-regression checks pass;
- 183/183 tests pass.

**READY FOR AMESIM COMPARISON = YES**, with the unmet runtime target and rejected sparse-Jacobian path explicitly carried forward.

