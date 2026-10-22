"""Run the unchanged formal BAT from an unactivated, non-project directory.

This is an independent cmd.exe launch, not a claim of Explorer double-click.
The existing application's Qt startup probes switch pages and capture itself.
"""
from pathlib import Path
import datetime as dt
import json, os, re, subprocess, sys, time

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'outputs/desktop/r4'
assert Path(sys.executable)==Path(r'E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe')

def main():
    target=OUT/'formal_bat_acceptance.json'
    if target.exists():raise RuntimeError('Preserve prior BAT acceptance; inspect before rerun')
    env=os.environ.copy()
    cleared={name:env.pop(name,None) for name in ('CONDA_PREFIX','CONDA_DEFAULT_ENV',
        'CONDA_PROMPT_MODIFIER','QT_QPA_PLATFORM','QT_PLUGIN_PATH','QT_QPA_PLATFORM_PLUGIN_PATH','PYTHONPATH')}
    env['PATH']=os.pathsep.join([str(Path(os.environ['SystemRoot'])/'System32'),os.environ['SystemRoot']])
    cwd=Path(os.environ['SystemRoot'])/'Temp'
    records=[]
    for index,duration in enumerate((35,8)):
        previous=set((ROOT/'outputs/desktop/logs').glob('desktop_startup*.log'))
        screenshot=OUT/('bat_main.png' if index==0 else 'bat_restart.png')
        arguments=[str(ROOT/'start_steering_desktop.bat'),'--startup-probe-seconds',str(duration),
                   '--startup-probe-pages','--startup-screenshot',str(screenshot)]
        if index==0:arguments.append('--startup-probe-health')
        command=[str(Path(os.environ['SystemRoot'])/'System32/cmd.exe'),'/d','/c',*arguments]
        started=time.perf_counter()
        run=subprocess.run(command,cwd=cwd,env=env,capture_output=True,timeout=240)
        (OUT/f'bat_launch_{index+1}.stdout.log').write_bytes(run.stdout)
        (OUT/f'bat_launch_{index+1}.stderr.log').write_bytes(run.stderr)
        logs=set((ROOT/'outputs/desktop/logs').glob('desktop_startup*.log'))-previous
        if len(logs)!=1:raise RuntimeError(f'Expected one new startup log, got {logs}')
        log=next(iter(logs));text=log.read_text('utf-8')
        shown=re.search(r'^(.*?) INFO .*main window shown; pages=5',text,re.M)
        closed=re.search(r'^(.*?) INFO .*Qt event loop exited code=0',text,re.M)
        assert run.returncode==0 and shown and closed and 'normal Qt exit code=0' in text
        visible=(dt.datetime.strptime(closed[1],'%Y-%m-%d %H:%M:%S,%f')-
                 dt.datetime.strptime(shown[1],'%Y-%m-%d %H:%M:%S,%f')).total_seconds()
        visited=sorted({int(p) for p in re.findall(r'startup probe page=(\d)',text)})
        assert visited==[1,2,3,4,5] and screenshot.is_file()
        health='startup probe task finished=simulation' in text
        if index==0:assert visible>=30 and health
        records.append(dict(log=str(log),command=command,returncode=run.returncode,normal_qt_exit_code=0,
            window_visible_s=visible,wall_s=time.perf_counter()-started,pages_visited=visited,
            health_simulation_finished=health,screenshot=str(screenshot)))
    result=dict(status='PASS',python=sys.executable,launches=records,
        invoking_working_directory=str(cwd),conda_and_qt_overrides_removed=list(cleared),
        conda_prefix_and_default_env_cleared=True,
        launch_path='Unactivated independent cmd.exe /d /c formal BAT; actual Qt window',
        manual_explorer_doubleclick_simulated=False,
        note='Actual formal launcher and restart verified; no claim of manual Explorer mouse double-click.')
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
