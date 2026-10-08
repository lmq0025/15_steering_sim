# Python Phase 2-B Runtime Profile

Profiled run: 1.0 s physical time, full 109-state RHS, zero-flow hold input.

- Success: yes
- Wall time: 57.2704 s
- nfev: 608
- Total calls observed by cProfile: 40,911,961

## Top cumulative hotspots

| Rank | Calls | Cumulative time (s) | Hotspot |
|---:|---:|---:|---|
| 1 | 1 | 57.295 | `FastHydraulicModel.simulate` |
| 2 | 1 | 57.270 | `scipy.integrate.solve_ivp` |
| 3 | 4,910 | 57.050 | SciPy `fun_wrapped` |
| 4 | 4,910 | 57.034 | FAST RHS lambda |
| 5 | 4,910 | 57.012 | `FastHydraulicModel.rhs` |
| 6 | 198 | 56.547 | SciPy integration step |
| 7 | 198 | 56.546 | BDF `_step_impl` |
| 8 | 39 | 50.065 | BDF numerical Jacobian wrapper |
| 9 | 39 | 49.591 | SciPy `num_jac` |
| 10 | 39 | 49.588 | SciPy dense numerical Jacobian |

The dominant cost is the dense numerical Jacobian: each of 39 Jacobian builds
perturbs the 109-state RHS repeatedly. CSV parsing, DataFrames and graph
construction do not occur inside the simulation loop. The next optimization
should be an analytic/block Jacobian or a corrected dependency-coloring matrix;
numba/jax is not yet justified because dispatch is not the dominant hotspot.
