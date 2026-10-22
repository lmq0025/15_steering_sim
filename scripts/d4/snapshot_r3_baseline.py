"""Preserve the local R2 files, not the remote Git state."""
from pathlib import Path
import hashlib,json,subprocess,shutil,sys
ROOT=Path(__file__).resolve().parents[2]; OUT=ROOT/'outputs/desktop/r3'
assert Path(sys.executable)==Path(r'E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe')
OUT.mkdir(parents=True,exist_ok=True)
target=OUT/'baseline.json'
if target.exists():raise RuntimeError('R3 baseline already exists; do not overwrite')
protected=json.loads((ROOT/'outputs/desktop/r2/baseline.json').read_text('utf-8'))['sha256']
files=list((ROOT/'src/steering_sim/desktop').glob('*.py'))+[ROOT/'src/steering_sim/degradation'/name for name in ('forecast.py','stochastic.py','rul.py')]+[ROOT/'scripts/d3/run_phase_d3.py']
for p in files:
    copy=OUT/'baseline_r2'/p.relative_to(ROOT);copy.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,copy)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
all_files=files+list((ROOT/'src/steering_sim/hydraulics_engineering').glob('*.py'))+list((ROOT/'src/steering_sim/j0_coupling').glob('*.py'))
data=dict(python=sys.executable,branch=subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip(),head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),git_status=subprocess.check_output(['git','status','--short'],cwd=ROOT,text=True),protected={k:sha(ROOT/k) for k in protected},source_hashes={p.relative_to(ROOT).as_posix():sha(p) for p in all_files})
target.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
print('Saved local R2 baseline:',target)
