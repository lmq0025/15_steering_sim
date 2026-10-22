"""Actual Qt acceptance. Replay explicitly loads this round's live 22-state record."""
import sys,json,time,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/'src')]
assert Path(sys.executable)==Path(r'E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe')
from PySide6.QtWidgets import QApplication,QFileDialog,QTextBrowser
from PySide6.QtCore import QTimer,Qt
from PySide6.QtGui import QFont
from steering_sim.desktop.app import MainWindow,STYLE
from steering_sim.desktop.services import DesktopCalculationService

OUT=ROOT/'outputs/desktop/r3/gui';OUT.mkdir(parents=True,exist_ok=True)
app=QApplication([]);app.setStyleSheet(STYLE);app.setFont(QFont('Microsoft YaHei UI',11))
w=MainWindow();w.service=DesktopCalculationService(OUT/'calculations');w.showMaximized()
records=[];tasks=[];errors=[];started=time.perf_counter();task_start=0.;pending='replay';beats=[]
timer=QTimer(w);timer.timeout.connect(lambda:beats.append((w.controller.task_id if w.controller.busy else None,time.perf_counter())));timer.start(50)

def fail(task,message,detail):
    (OUT/'failure.txt').write_text(str(detail),encoding='utf-8');print(detail,flush=True)
    (OUT/'acceptance.json').write_text(json.dumps(dict(status='FAIL',task=task,message=message),ensure_ascii=False),encoding='utf-8');app.exit(2)
def hook(kind,value,tb):
    text=''.join(traceback.format_exception(kind,value,tb));errors.append(text);print(text,flush=True)
sys.excepthook=hook
def shot(name):
    app.processEvents();p=OUT/(name+'.png');assert app.primaryScreen().grabWindow(int(w.winId())).save(str(p));records.append(str(p))
def later(fn):QTimer.singleShot(300,fn)
def save_dialog(path,fn):
    old=QFileDialog.getSaveFileName;QFileDialog.getSaveFileName=lambda *a,**k:(str(path),'')
    try:fn()
    finally:QFileDialog.getSaveFileName=old
def open_project(path):
    old=QFileDialog.getOpenFileName;QFileDialog.getOpenFileName=lambda *a,**k:(str(path),'')
    try:w.open_project()
    finally:QFileDialog.getOpenFileName=old
def start(task):
    global task_start
    task_start=time.perf_counter();print('START '+task,flush=True)
def done(task,result):
    tasks.append(dict(task=task,wall_s=time.perf_counter()-task_start,output_dir=result.get('output_dir'),sample_count=result.get('sample_count')))
    print('DONE '+task,flush=True);later(lambda:after(task,result))
def run():
    open_project(ROOT/'outputs/desktop/r3/a_live/实时两度斜坡.d4project.json')
    p=w.pages[0];assert p._record_reference
    w.start_task('replay',dict(reference=p._record_reference))
def after(task,result):
    global pending
    if task=='replay':
        assert result['provenance_kind']=='HISTORICAL_REPLAY'
        p=w.pages[0];steps=[('01_车辆起点_历史积分回放',0,0),('02_车辆中点_历史积分回放',0,6),('03_车辆终点_历史积分回放',0,17),('04_四缸同屏实际响应',1,6),('05_共同时间游标',1,8.5),('06_十二轮到位稳态',2,17)]
        def next_shot():
            global pending
            if steps:
                name,tab,t=steps.pop(0);p.tabs.setCurrentIndex(tab);p.replay.seek(t)
                later(lambda:(shot(name),next_shot()))
            else:
                w.navigation.setCurrentRow(2);d=w.pages[2];d.forecast_mode.setCurrentIndex(1);d.sample_count.setValue(128);d.show_paths.setChecked(True);d.path_count.setCurrentIndex(0);pending='128';d._run()
        next_shot()
    elif task=='degradation':
        p=w.pages[2];p.view_mode.setCurrentIndex(1);p.component.setCurrentIndex(0);p.metric.setCurrentIndex(p.metric.findData('volumetric_efficiency'));p.tabs.setCurrentIndex(0)
        if pending=='128':
            shot('07_128路径_容积效率_五条真实样本');p.path_count.setCurrentIndex(1);shot('08_128路径_十条真实样本')
            p.sample_count.setValue(1000);pending='1000';p._run()
        else:
            assert result['sample_count']==1000
            shot('09_1000路径_全样本预测带');p.tabs.setCurrentWidget(p.path_table)
            save_dialog(OUT/'代表路径数据.xlsx',w.export_current_table);pending='path_export'
    elif task=='export':
        w.navigation.setCurrentRow(3);p=w.pages[3];p.source.setCurrentIndex(3);pending='quality';p._run()
    elif task=='quality':
        p=w.pages[3];p.tabs.setCurrentIndex(1);shot('10_同工况健康当前轮角');p.tabs.setCurrentIndex(2);shot('11_同工况健康当前供压');p.tabs.setCurrentIndex(3);shot('12_同工况指标变化表')
        w.navigation.setCurrentRow(4);p=w.pages[4];p.initial.setCurrentIndex(0);p.samples.setValue(128);p.max_cycles.setValue(240);pending='rul';p._run()
    elif task=='rul':
        p=w.pages[4];p.tabs.setCurrentIndex(0);p.random_view.path_count.setCurrentIndex(1);shot('13_限制部件十路径与首次越限')
        p.tabs.setCurrentIndex(2);shot('14_四级离散质量检查点');p.tabs.setCurrentIndex(3);shot('15_随机寿命含删失说明');p.tabs.setCurrentIndex(0)
        # Export exactly the displayed current results, then restore the project.
        w.pages[0].replay.seek(8.5);w.pages[0].tabs.setCurrentIndex(1)
        w._sync_project();project=OUT/'交互与可视化验收工程.d4project.json';w.project.save(project)
        save_dialog(OUT/'中文综合报告.md',w.export_report)
        browser=QTextBrowser(w);browser.setWindowFlags(browser.windowFlags()|Qt.Window);browser.resize(1200,850);browser.setWindowTitle('本次实际结果中文综合报告');browser.setMarkdown((OUT/'中文综合报告.md').read_text('utf-8'));browser.show();app.processEvents()
        assert app.primaryScreen().grabWindow(int(browser.winId())).save(str(OUT/'16_中文综合报告.png'));records.append(str(OUT/'16_中文综合报告.png'));browser.close()
        summary=dict(result['summary']);scope=p.random_view.scope.text();sample_ids=p.random_view.displayed_ids
        open_project(project);assert not w.results and w.pages[2].path_count.currentData()==10 and w.pages[4].random_view.path_count.currentData()==10
        assert w.pages[0]._saved_replay_time==8.5
        (OUT/'run_details.json').write_text(json.dumps(dict(rul=summary,random_scope=scope,displayed_ids=sample_ids),ensure_ascii=False,indent=2),encoding='utf-8')
        w.navigation.setCurrentRow(0);p=w.pages[0];p.command_type.setCurrentIndex(1);p.angle.setValue(30);pending='cancel';p._run();QTimer.singleShot(150,w.controller.request_cancel)
def cancelled(task,message):
    if pending!='cancel':return
    shot('17_后台安全取消无旧结果')
    if errors:fail('callback','Qt回调异常','\n'.join(errors));return
    data=dict(status='PASS',screenshots=records,tasks=tasks,wall_s=time.perf_counter()-started,project_roundtrip=True,cancellation=True,
        actual_capture='QScreen.grabWindow actual Qt pixels',replay_source='本轮a_live实际0.5ms积分；历史回放，未重新求解',
        maximum_busy_heartbeat_gap_s=max([b[1]-a[1] for a,b in zip(beats,beats[1:]) if a[0] is not None and a[0]==b[0]] or [0]))
    (OUT/'acceptance.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(data,ensure_ascii=False),flush=True);w.close();app.quit()
w.controller.started.connect(start);w.controller.finished.connect(done);w.controller.failed.connect(fail);w.controller.cancelled.connect(cancelled)
QTimer.singleShot(800,run);raise SystemExit(app.exec())
