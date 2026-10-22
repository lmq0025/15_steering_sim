"""Final full repository run with frozen source hashes and retained prior log."""
from pathlib import Path
import sys,os,subprocess,time,json,hashlib,shutil
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'outputs/desktop/r2'
EXPECTED=Path(r'E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe')
if Path(sys.executable).resolve()!=EXPECTED.resolve():raise RuntimeError('Wrong engineering Python')
OUT.mkdir(parents=True,exist_ok=True)
for suffix in ('.xml','.log'):
    old=OUT/f'full_repository{suffix}';retained=OUT/f'full_repository_pre_ui_optimization{suffix}'
    if old.exists() and not retained.exists():shutil.copyfile(old,retained)

def hashes():
    files=list((ROOT/'src/steering_sim').rglob('*.py'))+list((ROOT/'tests').rglob('*.py'))+list((ROOT/'configs').rglob('*.json'))
    for name in ('d1','d2','d3','j1r2'):
        files.extend((ROOT/'scripts'/name).rglob('*.py'))
    files.append(ROOT/'start_steering_desktop.bat')
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}

before=hashes();temporary=(OUT/f'full_final_temp_{time.time_ns()}').resolve()
if temporary.parent!=OUT.resolve():raise RuntimeError('Unexpected pytest temporary target')
command=[sys.executable,'-m','pytest','-v','--basetemp',str(temporary),
         '--junitxml',str(OUT/'full_repository.xml')]
status={'status':'RUNNING','python':sys.executable,'command':command,'source_hashes_before':before}
path=OUT/'full_repository_run_status.json'
path.write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
started=time.perf_counter()
class Tee:
    def __init__(self,terminal,log):self.terminal,self.log=terminal,log
    def write(self,value):
        self.log.write(value);self.log.flush();return self.terminal.write(value)
    def flush(self):self.log.flush();self.terminal.flush()
    def isatty(self):return False
    @property
    def encoding(self):return 'utf-8'
    def fileno(self):return self.terminal.fileno()
with (OUT/'full_repository.log').open('w',encoding='utf-8') as stream:
    import pytest,contextlib
    os.chdir(ROOT)
    with contextlib.redirect_stdout(Tee(sys.stdout,stream)),contextlib.redirect_stderr(Tee(sys.stderr,stream)):
        code=int(pytest.main(command[3:]))
after=hashes();unchanged=before==after
status.update(status='PASS' if code==0 and unchanged else 'FAIL',returncode=code,
              wall_s=time.perf_counter()-started,source_hashes_unchanged=unchanged,
              source_hashes_after=after)
path.write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
if not unchanged:print('SOURCE_CHANGED_DURING_RUN',flush=True)
raise SystemExit(code if unchanged else 3)
