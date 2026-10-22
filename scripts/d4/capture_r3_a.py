"""One actual 0→2 degree reference-step Qt run, then display-only replay."""
from pathlib import Path
import sys,json,time
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/'src')]
assert Path(sys.executable)==Path(r'E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe')
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from steering_sim.desktop.app import MainWindow,STYLE
from steering_sim.desktop.services import DesktopCalculationService
OUT=ROOT/'outputs/desktop/r3/a_live';OUT.mkdir(parents=True,exist_ok=True)
app=QApplication([]);app.setStyleSheet(STYLE);w=MainWindow();w.service=DesktopCalculationService(OUT/'calculation');w.showMaximized()
page=w.pages[0];page.command_type.setCurrentIndex(1);page.angle.setValue(2);page.hold_observation.setValue(5)
started=time.perf_counter();evidence=[]
def shot(name):
    app.processEvents();path=OUT/f'{name}.png';assert app.primaryScreen().grabWindow(int(w.winId())).save(str(path));evidence.append(str(path))
def run():
    shot('01_尚未计算');page._run()
def done(task,result):
    if task!='simulation':return
    result['samples']['time_s'] # ensure real service return, never a canned picture
    steps=[('02_车辆起点',0,0),('03_车辆中间',0,6),('04_车辆终点',0,page.replay.end),('05_四缸同屏',1,6),('06_共同滑块游标',1,8.5),('07_轮角详情',6,8.5),('08_到位稳态表',2,page.replay.end)]
    def next_step():
        if steps:
            name,tab,t=steps.pop(0);page.tabs.setCurrentIndex(tab);page.replay.seek(t)
            QTimer.singleShot(150,lambda:(shot(name),next_step()))
        else:
            w._sync_project();w.project.save(OUT/'实时两度斜坡.d4project.json')
            data=dict(status='PASS',source='LIVE_QT_QTHREAD_FULL_22_STATE',input=page._scenario(),
                core_runtime_s=result['runtime_s'],service_runtime_s=result['service_runtime_s'],
                gui_total_wall_s=time.perf_counter()-started,csv_path=result['csv_path'],
                command_completion_s=result['response']['command_completion_s'],system_settled_s=result['response']['system_settled_s'],
                screenshots=evidence,playback_interpolation='显示插值；正式响应指标仍由原始时序计算')
            (OUT/'acceptance.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(data,ensure_ascii=False),flush=True);w.close();app.quit()
    next_step()
def fail(task,message,detail):
    (OUT/'failure.txt').write_text(detail,encoding='utf-8');print(detail,flush=True);app.exit(2)
w.controller.finished.connect(done);w.controller.failed.connect(fail)
QTimer.singleShot(700,run);raise SystemExit(app.exec())
