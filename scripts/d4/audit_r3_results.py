"""Audit actual R3 protected inputs, Qt/BAT evidence and result provenance."""
from pathlib import Path
from datetime import datetime
import sys,json,hashlib,re,platform,os
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'outputs/desktop/r3'
assert Path(sys.executable)==Path(r'E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
baseline=json.loads((OUT/'baseline.json').read_text('utf-8'))
protected={name:dict(before=value,after=sha(ROOT/name),unchanged=sha(ROOT/name)==value) for name,value in baseline['protected'].items()}
core={name:sha(ROOT/name)==value for name,value in baseline['source_hashes'].items() if '/hydraulics_engineering/' in name or '/j0_coupling/' in name}
assert all(v['unchanged'] for v in protected.values()) and all(core.values())
changes=[name for name,value in baseline['source_hashes'].items() if sha(ROOT/name)!=value]
new=['src/steering_sim/desktop/replay.py','src/steering_sim/desktop/rul_view.py','tests/desktop/test_d4_r3.py']
audit=dict(status='PASS',protected=protected,hydraulic_and_coupling_source_unchanged=core,changed_since_local_r2=changes,new_r3_source=new,
    python=sys.executable,platform=platform.platform(),processor=platform.processor(),logical_cpu_count=os.cpu_count())
(OUT/'baseline_final_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
logs=[]
for p in sorted((ROOT/'outputs/desktop/logs').glob('desktop_startup*.log')):
    text=p.read_text('utf-8')
    if 'outputs\\desktop\\r3\\bat_' not in text and 'outputs\\\\desktop\\\\r3\\\\bat_' not in text:continue
    shown=re.search(r'^(.*?) INFO .*main window shown; pages=5',text,re.M)
    closed=re.search(r'^(.*?) INFO .*Qt event loop exited code=0',text,re.M)
    assert shown and closed and 'normal Qt exit code=0' in text
    seconds=(datetime.strptime(closed[1],'%Y-%m-%d %H:%M:%S,%f')-datetime.strptime(shown[1],'%Y-%m-%d %H:%M:%S,%f')).total_seconds()
    logs.append(dict(log=str(p),window_visible_s=seconds,normal_qt_exit_code=0,
        health_simulation_finished='startup probe task finished=simulation' in text,pages_visited=sorted({int(v) for v in re.findall(r'startup probe page=(\d)',text)})))
assert len(logs)==2 and logs[0]['window_visible_s']>=30 and logs[0]['health_simulation_finished'] and logs[1]['pages_visited']==[1,2,3,4,5]
bat=dict(status='PASS',invocation='cmd.exe /d /c E:/15_project/start_steering_desktop.bat',working_directory='C:/Windows/Temp',
    conda_prefix_and_default_env_cleared=True,qt_plugin_overrides_cleared=True,launches=logs,
    manual_explorer_doubleclick_simulated=False,method='真实正式BAT独立调用；Qt自动化探针，不声称人工资源管理器双击',
    host_message='退出后命令宿主打印Access is denied；两次应用/命令退出码均0，未将该宿主提示冒称已修复')
(OUT/'formal_bat_acceptance.json').write_text(json.dumps(bat,ensure_ascii=False,indent=2),encoding='utf-8')
gui=json.loads((OUT/'gui/acceptance.json').read_text('utf-8'));assert gui['status']=='PASS'
print(json.dumps(dict(protected=len(protected),core_files=len(core),changes=changes,bat=bat),ensure_ascii=False,indent=2))
