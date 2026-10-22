"""Actual D2 dynamics at this run's D3 day-0/day-30 deterministic states."""
import sys,json,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/'src')]
import pandas as pd
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from steering_sim.desktop.app import MainWindow,STYLE
from steering_sim.desktop.localization import chinese_frame
from steering_sim.desktop.reporting import _table
from steering_sim.degradation import MultiModeDegradationState
from scripts.d3.run_phase_d3 import load_initial_state

OUT=ROOT/'outputs/desktop/r2/gui'
current=json.loads((OUT/'degradation_last_run.json').read_text('utf-8'))
end,_=load_initial_state(str(Path(current['output_dir'])/'final_twenty_state.json'),None,None)
app=QApplication([]);app.setStyleSheet(STYLE);app.setFont(QFont('Microsoft YaHei UI',11))
w=MainWindow();w.showMaximized();w.navigation.setCurrentRow(3)
records=[];results=[];start=time.perf_counter()
def request(day):
    page=w.pages[3];page.source.setCurrentIndex(page.source.findData('healthy' if day==0 else 'checkpoint_30'))
    w.start_task('quality',{'state_source':'自然退化第0天' if day==0 else '自然退化第30天',
        'severity':0.,'multimode_state':MultiModeDegradationState.healthy() if day==0 else end})
def finished(task,result):
    day=0 if not results else 30
    frame=result['rows'].copy();frame['checkpoint_day']=day;records.append(frame);results.append(result)
    if day==0:QTimer.singleShot(150,lambda:request(30));return
    QTimer.singleShot(200,complete)
def complete():
    frame=pd.concat(records,ignore_index=True)
    frame.to_csv(OUT/'quality_day0_day30_raw.csv',index=False,encoding='utf-8-sig')
    chinese_frame(frame.rename(columns={'checkpoint_day':'自然退化检查日（天）'})).to_csv(OUT/'自然退化月初月末质量.csv',index=False,encoding='utf-8-sig')
    page=w.pages[3];page.result_table.set_frame(frame.rename(columns={'checkpoint_day':'自然退化检查日（天）'}))
    plots=[]
    for i,result in enumerate(results):
        dynamic=result['dynamics'][0];s=dynamic.samples
        plots.append((('健康' if i==0 else '第30天确定性末态'),s['time_s'],s['wheel_axle1_right_actual_deg'],['#1976d2','#d97706'][i]))
    page.angle_plot.setTitle('月初/月末：同一标准工况真实轮角动态')
    page.angle_plot.replace_curves(plots)
    page.banner.set_status('月初/月末均由实际22状态计算；不代表中间所有时刻均已验证，也不是随机系统性能区间。','info')
    app.processEvents();app.primaryScreen().grabWindow(int(w.winId())).save(str(OUT/'18_自然退化月初月末真实质量对比.png'))
    with (OUT/'中文综合报告.md').open('a',encoding='utf-8') as report:
        report.write('\n## 10. 补充真实动态：自然退化第0/30天\n\n')
        report.write('以下为本轮20模式确定性月末状态与健康状态的独立标准动态复核。不能由端点等级推断所有中间时刻，也不把部件随机区间直接变成系统质量区间。\n\n')
        report.write(_table(frame[['checkpoint_day','case_id','quality_grade','max_tracking_error_deg','minimum_pump_flow_margin_lpm']].rename(columns={'checkpoint_day':'自然退化检查日（天）'}))+'\n')
    metadata=dict(status='PASS',state_source=current['output_dir'],grades=[r['grade'] for r in results],
        runtime_s=time.perf_counter()-start,hydraulic_state_count=22,
        interpretation='两个确定性状态，各运行相同D2标准动态；未把参数分位区间乘到轮角误差')
    (OUT/'quality_endpoint_validation.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(metadata,ensure_ascii=False),flush=True);w.close();app.quit()
def failed(task,message,detail):
    print(detail,flush=True);app.exit(2)
w.controller.finished.connect(finished);w.controller.failed.connect(failed)
QTimer.singleShot(500,lambda:request(0));raise SystemExit(app.exec())
