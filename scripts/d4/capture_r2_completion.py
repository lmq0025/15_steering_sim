"""Real Qt end-to-end acceptance; screenshots are QScreen window pixels.

No generated images. Long-ramp plots replay this continuation's already
integrated reference result, explicitly labelled, rather than reintegrating.
"""
import sys,os,json,time
from pathlib import Path
from dataclasses import asdict
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/'src')]
os.environ.setdefault('MPLBACKEND','Agg')
from PySide6.QtWidgets import QApplication,QFileDialog
from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
import pandas as pd
import pyqtgraph as pg
from steering_sim.desktop.app import MainWindow,STYLE
from steering_sim.desktop.response_analysis import analyze_response,ResponseCriteria
from steering_sim.desktop.reporting import write_report
from steering_sim.desktop.services import DesktopCalculationService

OUT=ROOT/'outputs/desktop/r2/gui'

class Driver:
    def __init__(self,app,window):
        self.app,self.w=app,window;self.records=[];self.results={};self.pending=None
        self.started=time.perf_counter();self.beats=[];self.queue=[]
        self.busy_beats=[];self.task_walls=[];self.task_started=0.
        self.skip_batch='--skip-batch' in sys.argv
        OUT.mkdir(parents=True,exist_ok=True)
        (OUT/'gui_acceptance.json').write_text(json.dumps({'status':'RUNNING','started_at':time.strftime('%Y-%m-%d %H:%M:%S')}),encoding='utf-8')
        window.service=DesktopCalculationService(OUT/'calculations')
        window.controller.finished.connect(self.finished)
        window.controller.failed.connect(self.failed)
        window.controller.cancelled.connect(self.cancelled)
        window.controller.started.connect(self.started_task)
        self.timer=QTimer(window);self.timer.timeout.connect(self.heartbeat);self.timer.start(50)

    def started_task(self,task_id):
        self.task_started=time.perf_counter();print('START '+task_id,flush=True)

    def heartbeat(self):
        now=time.perf_counter();self.beats.append(now)
        self.busy_beats.append((self.w.controller.task_id if self.w.controller.busy else None,now))

    def shot(self,name):
        QApplication.processEvents()
        path=OUT/(name+'.png');pix=QApplication.primaryScreen().grabWindow(int(self.w.winId()))
        assert pix.save(str(path),'PNG')
        self.records.append(dict(name=name,path=str(path),width=pix.width(),height=pix.height()))

    def later(self,fn):QTimer.singleShot(350,fn)
    def run(self):
        self.w.navigation.setCurrentRow(0);p=self.w.pages[0]
        p.command_type.setCurrentIndex(1);p.angle.setValue(10);p.seconds_per_degree.setValue(6)
        self.shot('01_中文斜坡动作预览')
        p.command_type.setCurrentIndex(0);p.angle.setValue(2);p.duration.setValue(.5)
        self.pending='simulation';p._run()

    def finished(self,task_id,result):
        result=dict(result);self.results[task_id]=result
        self.task_walls.append(dict(task=task_id,wall_s=time.perf_counter()-self.task_started))
        print('DONE '+task_id,flush=True)
        (OUT/f'{task_id}_last_run.json').write_text(json.dumps({k:v for k,v in result.items() if k in ('runtime_s','sample_count','random_seed','output_dir','summary','grids','row_count')},default=str,ensure_ascii=False,indent=2),encoding='utf-8')
        self.later(lambda:self.after(task_id,result))

    def after(self,task_id,result):
        if task_id=='simulation':
            self.shot('02_实时阶跃动态成功')
            if self.skip_batch:self.continue_after_simulation()
            else:self.w.pages[0]._batch()
        elif task_id=='batch':
            assert len(result['rows'])==3111
            self.shot('05b_3111真实网格覆盖摘要')
            self.continue_after_simulation()
        elif task_id=='degradation':
            p=self.w.pages[2]
            if self.pending=='deterministic':
                p.tabs.setCurrentIndex(1);self.shot('07_二十模式末态列表')
                p.tabs.setCurrentIndex(0);p.view_mode.setCurrentIndex(1)
                for index,metric,name in [(0,'volumetric_efficiency','08_齿轮泵容积效率'),(0,'mechanical_efficiency','09_齿轮泵机械效率'),(2,'response_time_s','10_转向阀响应时间'),(7,'friction_scale','11_五桥等效缸摩擦')]:
                    p.component.setCurrentIndex(index);p.metric.setCurrentIndex(p.metric.findData(metric));self.shot(name)
                p.component.setCurrentIndex(0);p.metric.setCurrentIndex(p.metric.findData('volumetric_efficiency'))
                p.forecast_mode.setCurrentIndex(1);p.sample_count.setValue(128);self.pending='128';p._run()
            elif self.pending=='128':
                self.shot('12_真实128条Gamma预测区间');self.result128=result
                p.sample_count.setValue(1000);self.pending='1000';p._run()
            else:
                self.shot('13_真实1000条Gamma预测区间')
                menu=p.damage_plot.chinese_context_menu()
                from PySide6.QtCore import QPoint
                menu.popup(p.damage_plot.mapToGlobal(QPoint(100,60)))
                QApplication.processEvents()
                QApplication.primaryScreen().grabWindow(int(menu.winId())).save(str(OUT/'19_真实中文图表菜单.png'))
                menu.close();menu.deleteLater()
                import pyqtgraph.exporters
                pg.exporters.ImageExporter(p.damage_plot.plotItem).export(str(OUT/'1000路径物理参数曲线.png'))
                p.tabs.setCurrentWidget(p.statistics_table)
                original=QFileDialog.getSaveFileName
                QFileDialog.getSaveFileName=lambda *a,**k:(str(OUT/'随机预测区间.xlsx'),'')
                try:self.w.export_current_table()
                finally:QFileDialog.getSaveFileName=original
        elif task_id=='export':
            if self.pending=='spectrum_export':
                from steering_sim.degradation import load_task_spectrum
                spectrum=load_task_spectrum(OUT/'当前任务谱导出.csv')
                assert len(spectrum.segments)==330 and all(s.seconds_per_degree==6 for s in spectrum.segments)
                self.w.navigation.setCurrentRow(2);self.pending='deterministic';self.w.pages[2]._run()
            else:
                self.w.navigation.setCurrentRow(3);self.w.pages[3]._run()
        elif task_id=='quality':
            self.shot('14_中文真实质量评价');self.w.navigation.setCurrentRow(4)
            p=self.w.pages[4];p.initial.setCurrentIndex(0);p.samples.setValue(128);p.max_cycles.setValue(240);p._run()
        elif task_id=='rul':
            self.shot('15_新口径剩余任务循环预测');self.complete()

    def continue_after_simulation(self):
        self.replay_reference()
        self.w.navigation.setCurrentRow(1)
        p=self.w.pages[1];original=QFileDialog.getOpenFileName
        QFileDialog.getOpenFileName=lambda *a,**k:(str(ROOT/'data/degradation/r2/task_spectrum_30day_example.xlsx'),'')
        try:p.import_file()
        finally:QFileDialog.getOpenFileName=original
        assert len(p.frame())==330
        self.shot('06_中文任务载荷谱')
        original=QFileDialog.getSaveFileName
        QFileDialog.getSaveFileName=lambda *a,**k:(str(OUT/'当前任务谱导出.csv'),'')
        self.pending='spectrum_export'
        try:p.export_file()
        finally:QFileDialog.getSaveFileName=original

    def replay_reference(self):
        row=json.loads((ROOT/'outputs/desktop/r2/a/reference_step_matrix/ramp_acceptance_summary.json').read_text('utf-8'))[0]
        data=pd.read_csv(ROOT/row['timeseries_csv']);samples={c:data[c].to_numpy() for c in data}
        stored=json.loads((ROOT/row['timeseries_csv']).with_name('summary.json').read_text('utf-8'))
        summary=stored.get('summary',stored)
        response=analyze_response(samples,row['command_completion_s'],ResponseCriteria())
        result=dict(kind='simulation',samples=samples,response=response,
            wheel_table=pd.DataFrame([dict(车轮=r['wheel'],最终目标角=r['final_target_deg'],最终实际角=r['final_actual_deg']) for r in response['wheel_table'].to_dict('records')]),
            wheel_response_table=response['wheel_table'],cylinder_response_table=response['cylinder_table'],runtime_s=row['runner_wall_s'],service_runtime_s=row['service_wall_s'],
            simulation_horizon_s=data.time_s.iloc[-1],calculation_success=bool(summary.get('completed')),
            tracking_pass=bool(summary.get('TRACKING_PASS')) and bool(summary.get('TRANSIENT_TRACKING_PASS')),
            trajectory_feasible=float(summary.get('target_path_adhesion_ratio',float('inf')))<=1,
            command_type='ramp',seconds_per_degree=6.,csv_path=row['timeseries_csv'],summary=summary,trace_source='本次续作实际0.5ms验收积分结果回放')
        p=self.w.pages[0];p.command_type.setCurrentIndex(1);p.angle.setValue(10)
        p.hold_observation.setValue(float(data.time_s.iloc[-1])-row['command_completion_s'])
        p.task_finished(result)
        self.w.results['simulation']=result
        self.w.status_text.setText('本轮0.5ms长工况数据回放；不重新计时')
        self.w.elapsed.setText(f"原服务计算 {row['service_wall_s']:.2f} s")
        for tab,name in [(0,'03_六秒每度真实十二轮响应'),(1,'04_四通道真实行程'),(2,'05_十二轮稳态时间表')]:
            p.tabs.setCurrentIndex(tab);p.banner.set_status('本次已完成的0.5ms参考验收结果回放，数据未经滤波或目标替代。','info');self.shot(name)

    def complete(self):
        if getattr(self,'unhandled',[]):
            self.failed('Qt callback','未处理异常','\n'.join(self.unhandled));return
        from scripts.d3.run_phase_d3 import load_initial_state
        state,_=load_initial_state(str(Path(self.w.results['degradation']['output_dir'])/'final_twenty_state.json'),None,None)
        assert state==self.w.results['degradation']['final_state']
        self.w._sync_project();self.w.project.name='D4-R2完整中文验收工程'
        project=OUT/'中文验收工程.d4project.json';self.w.project.save(project)
        report=write_report(OUT/'中文综合报告.md',asdict(self.w.project),self.w.results,self.w.project.provenance)
        # Report visibly opened within the actual Qt desktop, not a fabricated screenshot.
        from PySide6.QtWidgets import QTextBrowser
        self.browser=QTextBrowser(self.w);self.browser.setWindowFlags(self.browser.windowFlags()|__import__('PySide6.QtCore',fromlist=['Qt']).Qt.Window)
        self.browser.setWindowTitle('本次实际计算中文综合报告');self.browser.resize(1200,850);self.browser.setMarkdown(report.read_text('utf-8'));self.browser.show()
        QApplication.processEvents();QApplication.primaryScreen().grabWindow(int(self.browser.winId())).save(str(OUT/'16_中文综合报告.png'))
        self.browser.close()
        original=QFileDialog.getOpenFileName;QFileDialog.getOpenFileName=lambda *a,**k:(str(project),'')
        try:self.w.open_project()
        finally:QFileDialog.getOpenFileName=original
        assert self.w.pages[2].sample_count.value()==1000 and not self.w.results
        # Cooperative cancellation of an actual new long ramp; no completed result may survive.
        self.w.navigation.setCurrentRow(0);p=self.w.pages[0];p.command_type.setCurrentIndex(1);p.angle.setValue(30)
        self.pending='cancel';p._run();QTimer.singleShot(150,self.w.controller.request_cancel)

    def cancelled(self,task_id,message):
        if self.pending!='cancel':return
        self.shot('17_后台安全取消')
        payload=dict(status='PASS',screenshots=self.records,real_qt_window_capture=True,
            capture_method='QScreen.grabWindow',workflow_wall_s=time.perf_counter()-self.started,
            heartbeat_count=len(self.beats),maximum_heartbeat_gap_s=max([b-a for a,b in zip(self.beats,self.beats[1:])] or [0]),
            task_wall_times=self.task_walls,optional_batch_executed=not self.skip_batch,
            maximum_busy_heartbeat_gap_s=max([b[1]-a[1] for a,b in zip(self.busy_beats,self.busy_beats[1:]) if a[0] is not None and a[0]==b[0]] or [0]),
            project_roundtrip=True,cancelled_at_safe_checkpoint=True,
            note='截图03至05回放本次续作已完成的真实长工况，不重复积分；并非人工鼠标双击验收')
        (OUT/'gui_acceptance.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
        QTimer.singleShot(100,self.app.quit)

    def failed(self,task_id,message,detail):
        (OUT/'FAILED.txt').write_text(f'{task_id}\n{message}\n{detail}',encoding='utf-8')
        (OUT/'gui_acceptance.json').write_text(json.dumps({'status':'FAIL','task':task_id,'message':message},ensure_ascii=False),encoding='utf-8')
        print(detail,flush=True);self.app.exit(2)

def main():
    app=QApplication(sys.argv);app.setStyleSheet(STYLE);app.setFont(QFont('Microsoft YaHei UI',11))
    pg.setConfigOptions(antialias=True,foreground='#30475d')
    w=MainWindow();w.showMaximized();driver=Driver(app,w);QTimer.singleShot(1000,driver.run)
    import traceback
    driver.unhandled=[]
    def record_exception(kind,value,tb):
        text=''.join(traceback.format_exception(kind,value,tb));driver.unhandled.append(text);print(text,flush=True)
    sys.excepthook=record_exception
    return app.exec()
if __name__=='__main__':raise SystemExit(main())
