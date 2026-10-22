"""Actual Qt R4 lifetime acceptance; serial fresh 5/10-checkpoint D2 runs.

Uses the desktop's normal QThread service, never a mocked quality evaluator.
Run only when other integration/performance jobs have finished.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
import time
import traceback
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
assert Path(sys.executable)==Path(r'E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe')
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
import numpy as np
import pandas as pd
from PySide6.QtCore import QTimer,Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication,QFileDialog,QMessageBox,QTextBrowser
from steering_sim.desktop.app import MainWindow,STYLE
from steering_sim.desktop.services import DesktopCalculationService,EXAMPLE_SPECTRUM
from steering_sim.desktop.localization import chinese_frame


def hash_file(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def compare_frames(before,after):
    """Report numeric equality separately from string/event equality."""
    if list(before.columns)!=list(after.columns) or before.shape!=after.shape:
        return dict(equal=False,reason='shape_or_columns',before_shape=before.shape,after_shape=after.shape)
    changed=[];numeric_max=0.
    for column in before:
        a,b=before[column],after[column]
        if pd.api.types.is_numeric_dtype(a) and pd.api.types.is_numeric_dtype(b):
            x,y=a.to_numpy(float),b.to_numpy(float)
            finite=np.isfinite(x)&np.isfinite(y)
            if np.any(finite):numeric_max=max(numeric_max,float(np.max(np.abs(x[finite]-y[finite]))))
            if not np.allclose(x,y,rtol=1e-12,atol=1e-12,equal_nan=True):changed.append(column)
        elif a.fillna('').astype(str).tolist()!=b.fillna('').astype(str).tolist():changed.append(column)
    return dict(equal=not changed,changed_columns=changed,maximum_numeric_absolute_difference=numeric_max)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=ROOT/'outputs/desktop/r4/rul_gui')
    parser.add_argument('--r3-baseline',type=Path,default=ROOT/'outputs/desktop/r3/gui/calculations/rul/run_1792396187340386900')
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    if (out/'acceptance.json').exists():raise RuntimeError('已有验收记录，请用--output指定新的目录以保留历史结果')
    app=QApplication([]);app.setFont(QFont('Microsoft YaHei UI',11));app.setStyleSheet(STYLE)
    window=MainWindow();window.service=DesktopCalculationService(out/'calculations')
    window.showMaximized();page=window.pages[4];window.navigation.setCurrentRow(4)
    shots=[];runs=[];beat=[];errors=[];results={};started=time.perf_counter();task_started=0.;pending_count=5
    stages=[];failed=False
    original_critical=QMessageBox.critical
    QMessageBox.critical=lambda *_args,**_kwargs:QMessageBox.Ok
    timer=QTimer(window);timer.timeout.connect(lambda:beat.append((bool(window.controller.busy),time.perf_counter())));timer.start(50)

    def later(fn):QTimer.singleShot(350,fn)
    def shot(name,widget=None):
        app.processEvents();widget=widget or window;path=out/(name+'.png')
        assert app.primaryScreen().grabWindow(int(widget.winId())).save(str(path),'PNG')
        shots.append(str(path));print('SCREEN '+name,flush=True)
    def stop_when_safe(code):
        if window.controller.busy:
            window.controller.request_cancel();QTimer.singleShot(150,lambda:stop_when_safe(code));return
        timer.stop();window.close();app.exit(code)
    def fail(message,detail=''):
        nonlocal failed
        if failed:return
        failed=True;errors.append(detail or message)
        (out/'acceptance.json').write_text(json.dumps(dict(status='FAIL',message=message,errors=errors,
            completed_runs=runs,screenshots=shots,elapsed_s=time.perf_counter()-started),ensure_ascii=False,indent=2),encoding='utf-8')
        print(message+'\n'+detail,flush=True);stop_when_safe(2)
    def hook(kind,value,tb):fail('Qt验收回调异常',''.join(traceback.format_exception(kind,value,tb)))
    sys.excepthook=hook
    def started_task(task):
        nonlocal task_started
        task_started=time.perf_counter();print(f'START {task} {pending_count} checkpoints',flush=True)
    def progress(percent,message):
        stages.append(dict(checkpoints=pending_count,progress_percent=int(percent),message=str(message),elapsed_s=time.perf_counter()-task_started))
    def save_report(count):
        path=out/f'中文寿命报告_{count}检查点.md'
        previous=QFileDialog.getSaveFileName;QFileDialog.getSaveFileName=lambda *_a,**_k:(str(path),'Markdown (*.md)')
        try:window.export_report()
        finally:QFileDialog.getSaveFileName=previous
        assert path.exists() and '检查点' in path.read_text('utf-8')
        return path
    def begin(count):
        nonlocal pending_count
        assert not window.controller.busy
        pending_count=count;page.initial.setCurrentIndex(page.initial.findData('d1_day30'))
        page.max_cycles.setValue(240);page.stochastic.setChecked(True);page.samples.setValue(128);page.seed.setValue(20261013)
        page.mode.setCurrentIndex(0);page.quality_density.setCurrentIndex(0 if count==5 else 1)
        assert page.quality_checkpoints.value()==count
        window.navigation.setCurrentRow(4);page.tabs.setCurrentIndex(0);page._run()
    def compare_old(result):
        baseline=args.r3_baseline
        path=baseline/'rul_prediction_summary.json'
        if not path.exists():return dict(status='NOT_AVAILABLE',source=str(baseline))
        old=json.loads(path.read_text('utf-8'));new=result['summary']
        same_input=old['spectrum_sha256']==new['spectrum_sha256']
        same_config=old['d3_config_sha256']==new['d3_config_sha256'] and old['quality_thresholds_sha256']==new['quality_thresholds_sha256']
        comparison=dict(source=str(baseline),same_input_hash=same_input,same_configuration_hashes=same_config)
        if not same_input or not same_config:return comparison|dict(status='NOT_COMPARABLE_INPUTS')
        keys=['prediction_status','remaining_complete_30day_cycles','first_failure_cycle','first_failure_day_in_cycle',
              'first_failure_segment_id','limiting_factors','initial_state','random_seed']
        comparison['lifetime_fields_equal']=all(old[k]==new[k] for k in keys)
        comparison['monte_carlo_samples']=compare_frames(pd.read_csv(baseline/'monte_carlo_rul_samples.csv'),result['mc_samples'])
        comparison['deterministic_trajectories']=compare_frames(pd.read_csv(baseline/'component_parameter_trajectories.csv'),result['deterministic_modes'])
        comparison['status']='PASS' if comparison['lifetime_fields_equal'] and comparison['monte_carlo_samples']['equal'] and comparison['deterministic_trajectories']['equal'] else 'DIFFERENCE_RECORDED'
        return comparison
    def finished(task,result):
        elapsed=time.perf_counter()-task_started
        print(f'DONE {task} {pending_count} checkpoints {elapsed:.3f}s',flush=True)
        later(lambda:accept_result(task,result,elapsed))
    def accept_result(task,result,elapsed):
        nonlocal results
        assert task=='rul' and result and page.last_result is window.results['rul']
        count=pending_count;summary=result['summary'];quality=result['quality'];cases=result['quality_cases']
        assert summary['executed_quality_checkpoint_count']==count==len(quality)
        cycles=[int(value) for value in quality.mission_cycle]
        assert cycles==summary['quality_checkpoint_cycles']
        assert int(summary['executed_quality_case_count'])==len(cases)==count*2
        assert set(cases.case_id)=={'STD_L10','STD_L30'}
        assert cases.groupby('mission_cycle').size().to_dict()=={cycle:2 for cycle in cycles}
        assert quality.rated_quality_grade.iloc[-1]!='DANGEROUS' and summary['prediction_status']=='FAILURE_REACHED'
        assert summary['first_failure_segment_id']!='DYNAMIC_CHECKPOINT'
        assert len(result['mc_samples'])==128 and result['mc_checkpoints']['damage'].shape[1:]==(128,20)
        assert page.random_view.mode_selector.currentData()=='valve:channel_front:response_lag'
        assert page.random_view.deterministic_table.frame.mission_cycle.iloc[0]==0
        point=next(item for item in page.random_view.plot.listDataItems() if item.opts.get('symbol')=='t')
        assert int(point.xData[0])==summary['first_failure_cycle']
        result_dir=Path(result['output_dir']);assert result_dir.is_relative_to(out)
        info=dict(checkpoints_requested=count,quality_checkpoints_executed=len(quality),quality_cases_executed=len(cases),
            quality_cycles=cycles,final_quality_grade=quality.rated_quality_grade.iloc[-1],
            component_failure_reasons=summary['failure_reasons'],remaining_complete_cycles=summary['remaining_complete_30day_cycles'],
            first_failure_cycle=summary['first_failure_cycle'],service_to_present_s=elapsed,output_dir=str(result_dir),
            last_quality_display=page.quality_scope.text(),input_hash=summary['spectrum_sha256'],random_sample_count=128)
        runs.append(info);results[count]=result
        if count==5:info['r3_same_seed_comparison']=compare_old(result)
        page.tabs.setCurrentIndex(0);page.random_view.random_paths.setChecked(False);page.random_view.band.setChecked(False)
        page.random_view.center.setCurrentIndex(0)
        # The deterministic curve remains the same actual record; hiding paths does not redraw samples.
        shot(f'{count}检查点_01_限制部件确定性轨迹与首次越限')
        page.random_view.random_paths.setChecked(True);page.random_view.band.setChecked(True);page.random_view.path_count.setCurrentIndex(1)
        shot(f'{count}检查点_02_128条随机统计十路径预测带')
        page.tabs.setCurrentIndex(2);shot(f'{count}检查点_03_系统质量离散抽样及检查范围')
        chinese_frame(quality).to_csv(out/f'系统质量_{count}检查点.csv',index=False,encoding='utf-8-sig')
        chinese_frame(page.random_view.deterministic_table.frame).to_csv(out/f'限制模式确定性轨迹_{count}检查点.csv',index=False,encoding='utf-8-sig')
        page.tabs.setCurrentIndex(0);report=save_report(count)
        window._sync_project();window.project.save(out/f'寿命验收_{count}检查点.d4project.json')
        info['report_path']=str(report)
        if count==5:later(lambda:begin(10));return
        # Checkpoint density changes dynamic assessments, not Gamma draws or damage advancement.
        info['five_vs_ten_mc_comparison']=compare_frames(results[5]['mc_samples'],result['mc_samples'])
        info['five_vs_ten_deterministic_comparison']=compare_frames(results[5]['deterministic_modes'],result['deterministic_modes'])
        assert info['five_vs_ten_mc_comparison']['equal'] and info['five_vs_ten_deterministic_comparison']['equal']
        browser=QTextBrowser(window);browser.setWindowFlags(browser.windowFlags()|Qt.Window)
        browser.setWindowTitle('本次实际寿命预测中文报告：10个动态检查点');browser.resize(1320,900)
        browser.setMarkdown(report.read_text('utf-8'));browser.show();app.processEvents()
        shot('10检查点_04_本次中文综合报告',browser);browser.close()
        old=QFileDialog.getOpenFileName;QFileDialog.getOpenFileName=lambda *_a,**_k:(str(out/'寿命验收_10检查点.d4project.json'),'')
        try:window.open_project()
        finally:QFileDialog.getOpenFileName=old
        assert page.quality_density.currentData()==10 and page.quality_checkpoints.value()==10
        assert page.random_view.path_count.currentData()==10 and not window.results
        evidence=dict(status='PASS',validation_method='Actual Qt MainWindow, QThread services, fresh D3 + actual D2 QualityAssessor calls, QScreen.grabWindow',
            python=sys.executable,screenshots=shots,runs=runs,project_roundtrip=True,
            display_only_changes_do_not_resample=True,elapsed_s=time.perf_counter()-started,
            maximum_busy_heartbeat_gap_s=max([b[1]-a[1] for a,b in zip(beat,beat[1:]) if a[0] and b[0]] or [0]),
            notes=['5与10检查点分别真实计算，没有使用质量插值。','旧R3记录只用于结果对照，没有载入旧曲线冒充本次计算。',
                   '部件硬阈值与最后检查点的系统退化等级分别显示。','主图保留Gamma全样本均值；路径开关仅控制代表路径。'])
        (out/'progress_stages.json').write_text(json.dumps(stages,ensure_ascii=False,indent=2),encoding='utf-8')
        (out/'acceptance.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(evidence,ensure_ascii=False),flush=True);QMessageBox.critical=original_critical;stop_when_safe(0)
    window.controller.started.connect(started_task)
    window.controller.progress.connect(progress)
    window.controller.finished.connect(finished)
    window.controller.failed.connect(lambda task,message,detail:fail(f'{task}：{message}',detail))
    window.controller.cancelled.connect(lambda task,message:fail(f'验收任务提前取消：{task} {message}'))
    # Load the current official task, then let the normal Run handler write its input snapshot.
    window.pages[1].load_frame(pd.read_csv(EXAMPLE_SPECTRUM),str(EXAMPLE_SPECTRUM))
    QTimer.singleShot(800,lambda:begin(5))
    return app.exec()


if __name__=='__main__':raise SystemExit(main())
