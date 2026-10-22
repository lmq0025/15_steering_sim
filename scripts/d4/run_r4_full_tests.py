"""One complete R4 regression invocation with frozen source/config evidence.

No earlier XML is combined with this run. A retry must be explicit and preserves
the prior log, XML and status under a separate directory.
"""
from __future__ import annotations
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
import traceback
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'outputs/desktop/r4'
EXPECTED_PYTHON=Path(r'E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe')


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_hashes():
    files=set()
    extensions={'.py','.json','.yaml','.yml','.csv','.svg','.qss','.ui','.toml'}
    for folder in ('src/steering_sim','tests','scripts','configs',
                   'mechanics_ackermann_v2','mechanics_ackermann_redesigned'):
        files.update(path for path in (ROOT/folder).rglob('*')
                     if path.is_file() and path.suffix.lower() in extensions)
    files.update(path for path in (ROOT/'data/degradation/r2').rglob('*')
                 if path.is_file() and path.suffix.lower() in {'.json','.csv','.xlsx'})
    for name in ('start_steering_desktop.bat','mechanical_model_input_spec_v1.0.yaml','pyproject.toml','requirements-desktop.txt'):
        path=ROOT/name
        if path.is_file():files.add(path)
    return {path.relative_to(ROOT).as_posix():digest(path) for path in sorted(files) if '__pycache__' not in path.parts}


def protected_hashes():
    baseline=json.loads((OUT/'baseline.json').read_text('utf-8'))['source_hashes']
    return {name:value for name,value in baseline.items()
        if name.startswith(('configs/','src/steering_sim/mechanics/','src/steering_sim/engineering/',
                            'src/steering_sim/ackermann/','src/steering_sim/control/',
                            'src/steering_sim/quality_assessment/'))
        or name in ('mechanical_model_input_spec_v1.0.yaml','start_steering_desktop.bat',
                    'src/steering_sim/degradation/damage.py','src/steering_sim/degradation/multimode.py',
                    'src/steering_sim/degradation/stochastic.py',
                    'src/steering_sim/degradation/forecast.py','src/steering_sim/degradation/prediction.py',
                    'src/steering_sim/degradation/rainflow.py','src/steering_sim/degradation/spectrum.py',
                    'src/steering_sim/j0_coupling/angle_reference.py',
                    'src/steering_sim/desktop/response_analysis.py')}


def junit_counts(path):
    if not path.is_file():return None
    cases=list(ET.parse(path).getroot().iter('testcase'))
    counts=dict(tests=len(cases),passed=0,skipped=0,failed=0,errors=0)
    for case in cases:
        key='errors' if case.find('error') is not None else 'failed' if case.find('failure') is not None else 'skipped' if case.find('skipped') is not None else 'passed'
        counts[key]+=1
    return counts


class Tee:
    def __init__(self,terminal,log):self.terminal,self.log=terminal,log
    def write(self,value):self.log.write(value);self.log.flush();return self.terminal.write(value)
    def flush(self):self.log.flush();self.terminal.flush()
    def isatty(self):return False
    def fileno(self):return self.terminal.fileno()
    @property
    def encoding(self):return 'utf-8'


def main():
    if Path(sys.executable).resolve()!=EXPECTED_PYTHON.resolve():raise RuntimeError('请使用唯一工程Python')
    parser=argparse.ArgumentParser()
    parser.add_argument('--allow-retry',action='store_true',help='Preserve the prior attempt, then start a new complete run')
    args=parser.parse_args();OUT.mkdir(parents=True,exist_ok=True)
    names=('full_repository_run_status.json','full_repository.log','full_repository.xml')
    if any((OUT/name).exists() for name in names):
        if not args.allow_retry:raise RuntimeError('已有全仓记录；如确需重跑请明确--allow-retry，历史记录不会合并或删除')
        archived=OUT/'prior_full_attempts'/str(time.time_ns());archived.mkdir(parents=True)
        for name in names:
            if (OUT/name).exists():shutil.copy2(OUT/name,archived/name)
    protected=protected_hashes()
    if not protected:raise RuntimeError('缺少R4真实基线保护哈希')
    changed=[name for name,value in protected.items() if not (ROOT/name).is_file() or digest(ROOT/name)!=value]
    if changed:raise RuntimeError('受保护配置/坐标/退化参数源码已改变：'+', '.join(changed))
    before=source_hashes();temporary=(OUT/f'full_temp_{time.time_ns()}').resolve()
    assert temporary.parent==OUT.resolve()
    pytest_args=['-v','--basetemp',str(temporary),'--junitxml',str(OUT/'full_repository.xml')]
    status=dict(status='RUNNING',phase='D4-R4',python=sys.executable,started_at=time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        command=[sys.executable,'-m','pytest',*pytest_args],source_hashes_before=before,
        protected_hashes=protected,test_scope='one complete repository invocation; no selection/filter flags',
        prior_attempts_combined=False)
    target=OUT/'full_repository_run_status.json'
    target.write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
    started=time.perf_counter();started_wall_ns=time.time_ns();os.chdir(ROOT);code=2;error=None
    with (OUT/'full_repository.log').open('w',encoding='utf-8') as log:
        with contextlib.redirect_stdout(Tee(sys.stdout,log)),contextlib.redirect_stderr(Tee(sys.stderr,log)):
            try:
                import pytest
                code=int(pytest.main(pytest_args))
            except BaseException:
                error=traceback.format_exc();print(error)
    after=source_hashes();unchanged=before==after
    protected_unchanged=all((ROOT/name).is_file() and digest(ROOT/name)==value for name,value in protected.items())
    xml_path=OUT/'full_repository.xml'
    xml_fresh=xml_path.is_file() and xml_path.stat().st_mtime_ns>=started_wall_ns
    counts=junit_counts(xml_path) if xml_fresh else None
    passed=code==0 and unchanged and protected_unchanged and counts and counts['tests']>0 and not counts['failed'] and not counts['errors']
    status.update(status='PASS' if passed else 'FAIL',returncode=code,wall_s=time.perf_counter()-started,
        source_hashes_unchanged=unchanged,source_hashes_after=after,protected_hashes_unchanged=protected_unchanged,
        actual_test_counts=counts,junit_written_during_this_run=xml_fresh,error=error,finished_at=time.strftime('%Y-%m-%dT%H:%M:%S%z'))
    target.write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({key:status[key] for key in ('status','returncode','wall_s','actual_test_counts','source_hashes_unchanged','protected_hashes_unchanged')},ensure_ascii=False),flush=True)
    return 0 if passed else code or 3


if __name__=='__main__':raise SystemExit(main())
