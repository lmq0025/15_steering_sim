# PHASE J0 handoff package

**Verdict: the J0 joint-commissioning layer is built, runs, and is tested; the
four-channel closed loop is blocked by a defect in the delivered L1-Fast V1
hydraulic plant, not by anything in this layer.**

Read first: `handoff/05_J0_PLANT_DEFECT_AND_KNOWN_RISKS.md`
Then: `report/phase_J0_report.md`

## Blocking defects

| ID | Defect | Evidence |
|---|---|---|
| F1 | All four channels have `dF_hyd/dv > 0` and `dF_hyd/dx > 0` (negative hydraulic damping and stiffness) | `report/j0_diagnostics.json` -> `plant_characterisation`, `report/plant_characterisation.png` |
| F2 | `channel_front` static force authority is ~33 N over the whole command range; the front group needs ~6.2 kN | same, plus `data/J0-02_+2deg_5kmh_timeseries.csv` |

Neither can be compensated by PID: see `report/gain_study_J0-02.csv`
(19 of 20 tested gain sets diverge within 0.03-0.18 s; the only set that runs is
`kp=ki=kd=0`, which does nothing).

## Recorded case outcomes

| Case | Target | Speed | Status |
|---|---|---:|---|
| J0-01 | 0 deg | 0 km/h | **PASS** (exact fixed point, zero residuals) |
| J0-02 | +2 deg | 5 km/h | FAIL, stopped at 0.080 s |
| J0-03 | -2 deg | 5 km/h | FAIL, stopped at 0.082 s |
| J0-04 | +5 deg | 10 km/h | FAIL, stopped at 0.075 s |

## Reproduce

```powershell
$py = 'E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe'
& $py scripts/j0/run_j0.py                 --output outputs/j0
& $py scripts/j0/run_j0_diagnostics.py     --output outputs/j0/diagnostics
& $py scripts/j0/run_j0_gain_study.py      --output outputs/j0/gain_study
& $py scripts/j0/run_j0.py --output outputs/j0_diag --diagnostic-damping 1.5e6 --duration 6.0
& $py -m pytest -q tests/j0_coupling -p no:cacheprovider
```

`--diagnostic-damping` adds a fictitious mechanical damper so that the J0
pipeline can be exercised independently of the plant defect.  Those results are
**not** operating-case results and are never reported as a PASS.

## Layout

```
handoff/      defect register
report/       J0 conclusion report, summaries, diagnostics, gain study, figures
source/       J0 coupling source, J0 configuration, entry scripts, tests
data/         per-case time series CSV and figures (J0-01..J0-04)
data/diagnostic/  diagnostic-damped runs (structure verification only)
```
