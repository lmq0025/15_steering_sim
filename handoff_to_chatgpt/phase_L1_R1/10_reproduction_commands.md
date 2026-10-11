# Phase L1-R1 reproduction commands

Use only the project Python:

```powershell
cd E:\15_project
& "E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe" .\scripts\hydraulics\run_phase_l1_r1_validation.py
& "E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe" -m pytest -q
```

The Amesim extraction worker is retained for audit. It copies `qh1_1_MCP_AUDIT.ame` to a temporary model, closes every circuit with `AMECloseCircuit(False)`, deletes the temporary `.ame`, and verifies the audit model SHA-256 before/after. S0 succeeded; S1/S2 parameter-modified runs failed and are intentionally marked `NOT_COMPARABLE`.

```powershell
& "E:\Simcenter\2021.1\Amesim\win64\AMEPython.exe" .\scripts\hydraulics\run_phase_l1_r1_amesim.py --output .\hydraulic_audit_lumped\31_amesim_paired_raw.json
```
