"""One final full-repository run, with source freeze and exact log/XML."""
from pathlib import Path
import sys,os,time,json,hashlib,contextlib
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'outputs/desktop/r3'
assert Path(sys.executable)==Path(r'E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe')
OUT.mkdir(parents=True,exist_ok=True)
# Preserve any interrupted attempt separately; it is never counted as a full pass.
import shutil
if (OUT/'full_repository_run_status.json').exists():
    stamp=time.time_ns()
    for suffix in ('run_status.json','log','xml'):
        old=OUT/f'full_repository{("_" if suffix=="run_status.json" else ".")}{suffix}'
        if old.exists():shutil.copyfile(old,OUT/f'full_repository_interrupted_{stamp}_{suffix}')
def hashes():
    files=list((ROOT/'src/steering_sim').rglob('*.py'))+list((ROOT/'tests').rglob('*.py'))+list((ROOT/'configs').rglob('*.json'))
    for name in ('d1','d2','d3','j1r2'):files.extend((ROOT/'scripts'/name).rglob('*.py'))
    files.append(ROOT/'start_steering_desktop.bat')
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}
class Tee:
    def __init__(self,terminal,log):self.terminal,self.log=terminal,log
    def write(self,value):self.log.write(value);self.log.flush();return self.terminal.write(value)
    def flush(self):self.log.flush();self.terminal.flush()
    def isatty(self):return False
    @property
    def encoding(self):return 'utf-8'
    def fileno(self):return self.terminal.fileno()
before=hashes();temporary=(OUT/f'full_temp_{time.time_ns()}').resolve()
assert temporary.parent==OUT.resolve()
args=['-v','--basetemp',str(temporary),'--junitxml',str(OUT/'full_repository.xml')]
status=dict(status='RUNNING',python=sys.executable,command=[sys.executable,'-m','pytest',*args],source_hashes_before=before)
target=OUT/'full_repository_run_status.json';target.write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
started=time.perf_counter();os.chdir(ROOT)
with (OUT/'full_repository.log').open('w',encoding='utf-8') as stream:
    import pytest
    with contextlib.redirect_stdout(Tee(sys.stdout,stream)),contextlib.redirect_stderr(Tee(sys.stderr,stream)):code=int(pytest.main(args))
after=hashes();unchanged=before==after
status.update(status='PASS' if code==0 and unchanged else 'FAIL',returncode=code,wall_s=time.perf_counter()-started,source_hashes_unchanged=unchanged,source_hashes_after=after)
target.write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
raise SystemExit(code if unchanged else 3)
