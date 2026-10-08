# Python Phase 2-B.5 Runtime Profile

The accepted runtime is dense BDF plus exact dependency-signature caching for local algebraic groups. The 1 s profile used the full 109-state steering-like scenario. Caller-edge collection was disabled because full caller tracing exhausted the Windows process while serializing millions of repeated calls; per-function call counts, total time, and cumulative time were retained.

| Metric | Fresh-model baseline | Accepted optimized |
|---|---:|---:|
| Median 1 s simulation | 54.328722 s | 27.190209 s |
| Phase 2-B reported wall time | 150.886670 s | 27.190209 s |
| Accepted speedup | 1.000x | 1.998x |
| Speedup vs Phase 2-B report | 1.000x | 5.549x |
| Algebraic evaluations | 894,830 | 894,830 |
| Actual local solves | 894,830 | 107,467 |

The profiling run took 42.863178 s under profiler overhead and executed 24,678,741 function calls. The dense numerical Jacobian remains the dominant architectural cause: SciPy's reported `nfev` excludes many internal finite-difference RHS evaluations, while the profiler observed 20,703 `rhs` calls.

## Top 20 hotspots

| Rank | Calls | Total s | Cumulative s | Function |
|---:|---:|---:|---:|---|
| 1 | 3,191,014 | 8.175 | 8.396 | `_safe_float` |
| 2 | 20,703 | 7.060 | 42.381 | `FastHydraulicModel.rhs` |
| 3 | 3,289,847 | 6.166 | 7.426 | `_flow_and_derivative` |
| 4 | 20,708 | 5.782 | 23.832 | `solve_algebraic` |
| 5 | 216,749 | 4.824 | 7.676 | `residual_jacobian` |
| 6 | 2,649,984 | 1.543 | 9.872 | `_param` |
| 7 | 2,616,859 | 1.376 | 1.534 | `_branch_pairs` |
| 8 | 3,414,065 | 0.885 | 0.885 | `_command` |
| 9 | 290,172 | 0.808 | 1.136 | NumPy `_mean` |
| 10 | 310,545 | 0.760 | 10.181 | `_cylinder_geometry` |
| 11 | 103,119 | 0.758 | 5.713 | `LocalAlgebraicSolver.solve` |
| 12 | 331,427 | 0.630 | 0.785 | NumPy `_wrapreduction` |
| 13 | 1,532,022 | 0.420 | 0.420 | line-state list comprehension |
| 14 | 290,172 | 0.396 | 1.532 | NumPy `mean` |
| 15 | 1,231,908 | 0.343 | 0.409 | switching-parameter generator |
| 16 | 290,172 | 0.328 | 0.328 | NumPy `_count_reduce_items` |
| 17 | 289,912 | 0.274 | 0.274 | explicit-node pressure list comprehension |
| 18 | 330,545 | 0.208 | 0.988 | NumPy `max` |
| 19 | 103,119 | 0.196 | 0.196 | local junction dictionary construction |
| 20 | 1,035,400 | 0.164 | 0.164 | mass/stroke generator |

The cache reduced actual local solves by 87.99%, but dense finite-difference evaluation still invokes the full RHS many times. The automatic sparse pattern has 987 nonzeros and 27 colors, yet SciPy colored sparse finite differences failed the physics-regression gate and are disabled.

