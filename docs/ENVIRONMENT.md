# Python environment

The only supported Python/Conda environment for this project is:

```text
name: steering_sim
path: E:\ProgramData\condaData\envs_dirs\steering_sim
executable: E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe
```

Before any install, run, example or test command, verify the active terminal:

```powershell
& "$env:CONDA_PREFIX\python.exe" -c "import sys; print(sys.executable)"
```

The printed path must be exactly the executable above. If `CONDA_PREFIX` is
unset or points elsewhere, activate `steering_sim` in the current terminal or
set that terminal's `CONDA_PREFIX` to the path above and repeat verification.
Do not modify the system PATH or any other Python environment.

All project commands use the verified executable explicitly:

```powershell
& "$env:CONDA_PREFIX\python.exe" -m pip install -e . --no-deps --no-build-isolation
& "$env:CONDA_PREFIX\python.exe" -m pytest -q
& "$env:CONDA_PREFIX\python.exe" examples/run_mechanical_dynamics_demo.py
```

Bare `python`, `pip`, and `pytest` commands are not supported project commands.
