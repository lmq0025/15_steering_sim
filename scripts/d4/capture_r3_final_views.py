"""Refresh final presentation from explicitly identified R3 calculated records.

No integration or random draws. Captures are actual Qt pixels; provenance is
retained separately from live computation acceptance.
"""
import sys,json,time
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/'src')]
assert Path(sys.executable)==Path(r'E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe')
import pandas as pd,numpy as np
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from steering_sim.desktop.app import MainWindow,STYLE
from steering_sim.desktop.localization import FIELDS,cn
from steering_sim.desktop.services import DesktopCalculationService,HEALTHY
from steering_sim.hydraulics_engineering import load_parameters
OUT=ROOT/'outputs/desktop/r3/gui';DETAIL=OUT/'final_views';DETAIL.mkdir(exist_ok=True)
accept=json.loads((OUT/'acceptance.json').read_text('utf-8'))
sources={t['task']:Path(t['output_dir']) for t in accept['tasks'] if t['output_dir']}
app=QApplication([]);app.setStyleSheet(STYLE);w=MainWindow();w.showMaximized();shots=[]
def shot(name):
    app.processEvents();target=DETAIL/f'{name}.png';assert app.primaryScreen().grabWindow(int(w.winId())).save(str(target));shots.append(target.name)
def run():
    qdir=sources['quality'];conditions=json.loads((qdir/'comparison_conditions.json').read_text('utf-8'))
    comparison=pd.read_csv(qdir/'健康当前同工况指标.csv');comparison=comparison.rename(columns={cn(k):k for k in FIELDS})
    trace=pd.read_csv(qdir/'paired_dynamic_raw.csv');rows=[];pairs=[]
    for case in conditions['cases']:
        case_id=case['case_id'];subset=comparison.loc[comparison.case_id==cn(case_id)];row=dict(case_id=case_id)
        for item in subset.to_dict('records'):
            metric=next(k for k in FIELDS if cn(k)==item['metric'])
            row[metric]=item['current_value']
        grades={'健康':'HEALTHY','亚健康':'SUBHEALTHY','退化':'DEGRADED','危险':'DANGEROUS'}
        row['quality_grade']=grades.get(subset.iloc[0].quality_grade,subset.iloc[0].quality_grade)
        row['grade_causes']=subset.iloc[0].grade_causes;rows.append(row)
        pair={**case}
        for state in ('healthy','current'):
            data=trace.loc[(trace.case_id==case_id)&(trace.state_label==state)].drop(columns=['case_id','state_label'])
            pair[state]=SimpleNamespace(samples={key:data[key].to_numpy() for key in data})
        pairs.append(pair)
    quality_inputs=json.loads((OUT/'交互与可视化验收工程.d4project.json').read_text('utf-8'))['page_inputs']['quality']
    order={'HEALTHY':0,'SUBHEALTHY':1,'DEGRADED':2,'DANGEROUS':3}
    grade=max((row['quality_grade'] for row in rows),key=order.get)
    qresult=dict(kind='quality',grade=grade,rows=pd.DataFrame(rows),comparison_dynamics=pairs,comparison_frame=comparison,
        natural_or_sensitivity=cn(quality_inputs['state_source'])+'（本轮已计算记录回放）',source=quality_inputs['state_source'])
    w.navigation.setCurrentRow(3);p=w.pages[3];p.source.setCurrentIndex(p.source.findData(quality_inputs['state_source']));p.severity.setValue(quality_inputs['severity']);p.task_finished(qresult)
    p.tabs.setCurrentIndex(1);w.status_text.setText('显示本轮已完成的同工况真实积分记录，未重新求解');shot('01_精简原因_同工况轮角')
    p.tabs.setCurrentIndex(2);shot('02_精简原因_同工况供压')
    rdir=sources['rul'];csv=lambda name:pd.read_csv(rdir/name)
    with np.load(rdir/'monte_carlo_checkpoints.npz',allow_pickle=False) as archive:record={k:archive[k].copy() for k in archive.files}
    result=dict(kind='rul',summary=json.loads((rdir/'rul_prediction_summary.json').read_text('utf-8')),
        history=csv('mission_cycle_history.csv'),quality=csv('quality_over_mission_cycles.csv'),modes=csv('component_degradation_modes.csv'),
        mc_summary=csv('monte_carlo_rul_summary.csv'),mc_samples=csv('monte_carlo_rul_samples.csv'),mc_checkpoints=record,
        mc_models=json.loads((rdir/'component_failure_thresholds.json').read_text('utf-8'))['modes'],physical_reference_parameters=load_parameters(HEALTHY))
    w.navigation.setCurrentRow(4);p=w.pages[4];p.task_finished(result);p.random_view.path_count.setCurrentIndex(1)
    w.status_text.setText('显示本轮已完成的随机结果，未重新抽样');shot('03_完整小数格式_限制模式与越限')
    p.random_view.metric.setCurrentIndex(p.random_view.metric.findData('response_time_s'));shot('04_真实响应常数与物理阈值')
    p.tabs.setCurrentIndex(2);shot('05_实际离散质量检查点')
    import pyqtgraph.exporters
    for widget,name in ((w.pages[3].angle_plot,'健康当前轮角'),(w.pages[3].pressure_plot,'健康当前供压'),(p.random_view.plot,'随机物理参数与首次越限')):
        exporter=pyqtgraph.exporters.ImageExporter(widget.plotItem);exporter.parameters()['width']=1600;exporter.export(str(DETAIL/f'{name}.png'))
    from steering_sim.desktop.localization import chinese_frame
    for table,name in ((p.random_view.paths_table,'随机模式代表路径'),(p.random_view.statistics_table,'全样本共同安全范围')):
        frame=chinese_frame(table.frame);frame.to_csv(DETAIL/f'{name}.csv',index=False,encoding='utf-8-sig');frame.to_excel(DETAIL/f'{name}.xlsx',index=False)
    sim=json.loads((ROOT/'outputs/desktop/r3/a_live/实时两度斜坡.d4project.json').read_text('utf-8'))['page_inputs']['simulation']['record_reference']
    loaded=DesktopCalculationService().load_simulation_record(reference=sim,progress=lambda *_:None,is_cancelled=lambda:False)
    for key,name in (('wheel_response_table','十二轮到位稳态时间'),('cylinder_response_table','四通道到位稳态时间')):
        frame=chinese_frame(loaded[key]);frame.to_csv(DETAIL/f'{name}.csv',index=False,encoding='utf-8-sig');frame.to_excel(DETAIL/f'{name}.xlsx',index=False)
    (DETAIL/'evidence.json').write_text(json.dumps(dict(status='PASS',method='QScreen.grabWindow actual Qt record replay',
        new_solver_calls=0,new_random_draws=0,source_paths={k:str(v) for k,v in sources.items()},screenshots=shots),ensure_ascii=False,indent=2),encoding='utf-8')
    w.close();app.quit()
def hook(kind,value,tb):
    import traceback
    text=''.join(traceback.format_exception(kind,value,tb));(DETAIL/'failure.txt').write_text(text,encoding='utf-8');print(text,flush=True);app.exit(2)
sys.excepthook=hook;QTimer.singleShot(600,run);raise SystemExit(app.exec())
