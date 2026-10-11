# Reproduction commands

```powershell
cd E:\15_project
& 'E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe' .\scripts\hydraulics\run_phase_l1_r3_validation.py
& 'E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe' .\scripts\hydraulics\run_phase_l1_r3_100s_benchmark.py
& 'E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe' -m pytest -q -p no:cacheprovider
& 'E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe' .\scripts\hydraulics\finalize_phase_l1_r3.py
```

AMEPython extraction scripts operate only on isolated copies and verify protected SHA-256 hashes.
