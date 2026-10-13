"""Offline D4 dependency and model-input diagnostic."""
from __future__ import annotations

import importlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
required = ("PySide6", "pyqtgraph", "pandas", "openpyxl", "numpy")
files = (
    ROOT / "configs/j0/j0_config.json",
    ROOT / "configs/j1r2/engineering_hydraulics.json",
    ROOT / "configs/degradation/d1_degradation_models.json",
    ROOT / "configs/degradation/d2_quality_thresholds.json",
    ROOT / "configs/degradation/d3_rul_models.json",
    ROOT / "data/degradation/task_spectrum_30day_example.csv",
)
result = {
    "python": sys.executable,
    "expected_python": r"E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe",
    "modules": {}, "files": {}, "ready": True,
}
for name in required:
    try:
        module = importlib.import_module(name)
        result["modules"][name] = getattr(module, "__version__", "installed")
    except Exception as exc:
        result["modules"][name] = f"MISSING: {exc}"
        result["ready"] = False
for path in files:
    result["files"][str(path.relative_to(ROOT))] = path.exists()
    result["ready"] &= path.exists()
result["ready"] &= Path(sys.executable).resolve() == Path(result["expected_python"]).resolve()
print(json.dumps(result, ensure_ascii=False, indent=2))
raise SystemExit(0 if result["ready"] else 1)
