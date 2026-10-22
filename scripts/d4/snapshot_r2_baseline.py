"""Record local state before D4-R2 changes; never overwrite the first snapshot."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
out = ROOT / 'outputs/desktop/r2/baseline.json'
if out.exists():
    raise SystemExit('Baseline already exists; preserved.')
paths = ['configs/j1/engineering_mechanism.json', 'configs/j1/engineering_config.json',
         'configs/j1r2/engineering_hydraulics.json', 'mechanical_model_input_spec_v1.0.yaml',
         'configs/degradation/d1_degradation_models.json',
         'configs/degradation/d2_quality_thresholds.json',
         'configs/degradation/d3_rul_models.json', 'start_steering_desktop.bat']
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps({
    'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
    'status': subprocess.check_output(['git', 'status', '--short'], cwd=ROOT, text=True),
    'sha256': {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths},
}, ensure_ascii=False, indent=2), encoding='utf-8')
print(out)
