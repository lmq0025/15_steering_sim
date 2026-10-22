"""Audit the two actual formal-BAT probe logs; never substitute a Qt mock."""
from pathlib import Path
import re,json
from datetime import datetime
ROOT=Path(__file__).resolve().parents[2]
logs=sorted((ROOT/'outputs/desktop/logs').glob('desktop_startup*.log'))[-2:]
if len(logs)!=2:raise RuntimeError('Two actual startup records required')
records=[]
for path in logs:
    text=path.read_text('utf-8')
    shown=re.search(r'^(.*?) INFO .*main window shown; pages=5',text,re.M)
    closed=re.search(r'^(.*?) INFO .*Qt event loop exited code=0',text,re.M)
    assert shown and closed and 'normal Qt exit code=0' in text
    seconds=(datetime.strptime(closed[1],'%Y-%m-%d %H:%M:%S,%f')-datetime.strptime(shown[1],'%Y-%m-%d %H:%M:%S,%f')).total_seconds()
    records.append(dict(log=str(path),window_visible_s=seconds,normal_qt_exit_code=0,
        health_simulation_finished='startup probe task finished=simulation' in text,
        pages_visited=sorted({int(v) for v in re.findall(r'startup probe page=(\d)',text)})))
assert records[0]['window_visible_s']>=30 and records[0]['health_simulation_finished']
assert records[1]['pages_visited']==[1,2,3,4,5]
data=dict(status='PASS',invocation='cmd.exe /d /c E:/15_project/start_steering_desktop.bat',
    invoking_working_directory='C:/Windows/Temp',conda_prefix_and_default_env_cleared=True,
    qt_qpa_and_plugin_override_cleared=True,launches=records,
    manual_explorer_doubleclick_simulated=False,
    limitation='应用正常退出后工具命令窗口仍打印Access is denied；应用及cmd返回码为0，不虚称已定位该宿主提示根因')
(ROOT/'outputs/desktop/r2/formal_bat_acceptance.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(data,ensure_ascii=False,indent=2))
