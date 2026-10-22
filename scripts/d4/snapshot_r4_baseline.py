"""Preserve the actual local R3 source and environment before R4 edits."""
from pathlib import Path
import hashlib, json, platform, shutil, subprocess, sys, time

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'outputs/desktop/r4'
assert Path(sys.executable) == Path(r'E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe')
OUT.mkdir(parents=True, exist_ok=True)
target = OUT / 'baseline.json'
if target.exists():
    raise RuntimeError('R4 baseline already exists; never overwrite')
files = sorted(set(list((ROOT/'src/steering_sim').rglob('*.py'))
    + list((ROOT/'configs').rglob('*.json'))
    + [ROOT/'mechanical_model_input_spec_v1.0.yaml', ROOT/'start_steering_desktop.bat', ROOT/'scripts/d3/run_phase_d3.py']))
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
for source in files:
    dest = OUT/'baseline_r3'/source.relative_to(ROOT)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, dest)
git = lambda *args: subprocess.check_output(['git', *args], cwd=ROOT, text=True, encoding='utf-8', errors='replace')
data = dict(time=time.strftime('%Y-%m-%dT%H:%M:%S%z'), python=sys.executable,
    python_version=sys.version, platform=platform.platform(), processor=platform.processor(),
    branch=git('branch','--show-current').strip(), head=git('rev-parse','HEAD').strip(),
    git_status=git('status','--short'), source_hashes={p.relative_to(ROOT).as_posix():sha(p) for p in files})
target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
(OUT/'baseline_git.diff').write_text(git('diff','--no-ext-diff'), encoding='utf-8')
print(target, len(files))
