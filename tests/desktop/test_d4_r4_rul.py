"""R4 display and checkpoint scheduling tests; synthetic inputs do not calibrate models."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from PySide6.QtWidgets import QApplication
from steering_sim.degradation import load_d3_config, MultiModeDegradationState
from steering_sim.degradation.damage import ComponentDamageState
from steering_sim.degradation.multimode import component_mode_rows,parameters_from_multimode
from steering_sim.degradation.rul import RepeatedMissionRULPredictor,MissionCycleProfile,MissionSegmentExposure
from steering_sim.desktop.pages import RULPage
from steering_sim.desktop.rul_view import RULRandomView,deterministic_mode_record
from steering_sim.hydraulics_engineering import load_parameters

ROOT=Path(__file__).resolve().parents[2]
def app():return QApplication.instance() or QApplication([])
def config():return load_d3_config(ROOT/'configs/degradation/d3_rul_models.json')
def healthy():return load_parameters(ROOT/'configs/j1r2/engineering_hydraulics.json')
def profile():
    initial=MultiModeDegradationState.healthy()
    return MissionCycleProfile((MissionSegmentExposure('TEST',1,2592000,30,{key:0. for key in initial.modes}),),{},{},())

@pytest.mark.parametrize('count',[5,10,7])
def test_checkpoint_count_calls_authoritative_callback_for_each_real_state(count,monkeypatch):
    from scripts.d3 import run_phase_d3 as entry
    calls=[]
    class Assessor:
        def __init__(self,*_):pass
        def run(self,label,source,case):
            calls.append((label,case.case_id))
            return SimpleNamespace(row=dict(quality_grade='HEALTHY',max_tracking_error_deg=.01,
                minimum_pump_flow_margin_lpm=1.,grade_causes=''),dynamic=SimpleNamespace(samples={
                    'time_s':np.array([0.,1.]),'wheel_axle1_right_command_deg':np.array([0.,10.]),
                    'wheel_axle1_right_actual_deg':np.array([0.,9.99]),'supply_pressure_front_mpa_g':np.array([10.,10.])}))
    monkeypatch.setattr(entry,'QualityAssessor',Assessor)
    monkeypatch.setattr(entry,'runner',lambda *a,**k:object())
    cfg=config();raw=deepcopy(cfg.raw);raw['mission']['maximum_dynamic_checkpoints']=count;cfg=replace(cfg,raw=raw)
    evaluator,details,_=entry.quality_callback_factory(healthy(),cfg,None)
    result=RepeatedMissionRULPredictor(cfg,lambda *_:profile()).predict(maximum_cycles=12,
        quality_evaluator=evaluator,quality_checkpoint_count=count)
    expected=sorted({round(12*i/(count-1)) for i in range(count)})
    assert [row['mission_cycle'] for row in result.quality_history]==expected
    assert len(calls)==count*len(cfg.raw['mission']['quality_case_ids'])==len(details)
    assert all('degradation_state_json' in row for row in result.quality_history)
    assert result.status=='NOT_REACHED_WITHIN_HORIZON'

def test_default_five_schedule_preserves_prior_evaluation_positions():
    cfg=config();callback=lambda *_:{'rated_quality_grade':'HEALTHY'}
    a=RepeatedMissionRULPredictor(cfg,lambda *_:profile()).predict(maximum_cycles=131,quality_evaluator=callback)
    b=RepeatedMissionRULPredictor(cfg,lambda *_:profile()).predict(maximum_cycles=131,quality_evaluator=callback,quality_checkpoint_count=5)
    assert [row['mission_cycle'] for row in a.quality_history]==[0,33,66,98,131]
    assert a.quality_history==b.quality_history and a.cycle_history==b.cycle_history

def display_result():
    cfg=config();base=healthy();rows=[];history=[]
    key='valve:channel_front:response_lag'
    for cycle,damage in enumerate((.05,.35,.65,.95)):
        state=MultiModeDegradationState.healthy().with_mode(key,ComponentDamageState(damage,0.))
        params=parameters_from_multimode(base,state,cfg)
        rows.extend(dict(mission_cycle=cycle,**row) for row in component_mode_rows(state,cfg,params))
        if cycle:history.append(dict(mission_cycle=cycle,maximum_damage=damage,**state.flat_damage()))
    return dict(kind='rul',summary=dict(prediction_status='FAILURE_REACHED',remaining_complete_30day_cycles=2,
        first_failure_cycle=3,first_failure_segment_id='TEST-END',first_failure_day_in_cycle=7.,
        limiting_factors=['valve:channel_front'],failure_reasons=[key+' damage 0.95 >= hard limit 0.9'],random_seed=12),
        mc_checkpoints=None,mc_models=cfg.raw['modes'],physical_reference_parameters=base,
        deterministic_modes=pd.DataFrame(rows),history=pd.DataFrame(history),quality=pd.DataFrame([
            dict(mission_cycle=0,rated_quality_grade='HEALTHY',case_count=2,grade_causes='',maximum_mode_damage=.05),
            dict(mission_cycle=3,rated_quality_grade='DEGRADED',case_count=2,grade_causes='max_tracking_error_deg',maximum_mode_damage=.95)]),
        modes=pd.DataFrame(rows[-20:]),mc_samples=pd.DataFrame(columns=['failure_cycle']),
        mc_summary=pd.DataFrame([dict(metric='sample_count',value=0)]))

def test_deterministic_limiter_is_default_without_random_result_and_uses_actual_initial():
    qt=app();result=display_result();view=RULRandomView();view.set_result(result)
    assert view.mode_selector.currentData()=='valve:channel_front:response_lag'
    line=next(item for item in view.plot.listDataItems() if item.name()=='确定性轨迹')
    np.testing.assert_array_equal(line.xData,[0,1,2,3]);np.testing.assert_array_equal(line.yData,[.05,.35,.65,.95])
    assert view.statistics_table.frame.empty and view.paths_table.frame.empty
    assert '完整剩余2次' in view.scope.text() and 'TEST-END段末检测' in view.scope.text()
    crossing=next(item for item in view.plot.listDataItems() if item.opts.get('symbol')=='t')
    assert crossing.xData.tolist()==[3] and crossing.yData.tolist()==[.95]
    view.metric.setCurrentIndex(view.metric.findData('lag_scale'))
    scale=1+(config().mode('valve','response_lag')['maximum_lag_scale']-1)*np.array([.05,.35,.65,.95])
    np.testing.assert_allclose(view.deterministic_table.frame.value,scale)
    view.close()

def test_page_checkpoint_controls_and_discrete_grade_are_independent_of_hard_failure():
    qt=app();page=RULPage();requests=[];page.run_requested.connect(lambda kind,payload:requests.append(payload))
    page.quality_density.setCurrentIndex(1);page._run();assert requests[-1]['quality_checkpoints']==10
    assert not page.quality_checkpoints.isEnabled()
    page.quality_density.setCurrentIndex(2);page.quality_checkpoints.setValue(7);assert page.quality_checkpoints.isEnabled()
    payload=page.project_payload();copy=RULPage();copy.restore_quality_settings(payload)
    assert copy.quality_checkpoints.value()==7 and copy.quality_density.currentData() is None
    page.task_finished(display_result())
    assert page.tabs.currentWidget() is page.random_view
    assert page.tabs.tabText(1).startswith('辅助分析')
    assert '已执行2个检查点、4次' in page.quality_scope.text() and '1～2' in page.quality_scope.text()
    assert '第3次30天任务：退化' in page.quality_plot.hover_formatter(3,2)
    points=page.quality_plot.listDataItems()[0]
    assert points.opts['pen'] is None and points.yData.tolist()==[0,2]
    assert page.last_result['summary']['prediction_status']=='FAILURE_REACHED'
    assert '系统质量抽样检查点（22状态动态评估）'==page.quality_plot.plotItem.titleLabel.text
    page.close();copy.close()

def test_old_history_without_initial_is_not_filled_with_fictitious_zero():
    result=display_result();result.pop('deterministic_modes')
    cycles,matrix,keys=deterministic_mode_record(result)
    assert cycles.tolist()==[1,2,3] and matrix.shape==(3,1,20)

@pytest.mark.parametrize('path_count,columns',[(5,2),(10,3)])
def test_rul_legend_wraps_real_sample_labels_without_changing_arrays(path_count,columns):
    qt=app();result=display_result();keys=tuple(MultiModeDegradationState.healthy().modes)
    j=keys.index('valve:channel_front:response_lag');damage=np.zeros((4,10,20))
    damage[:,:,j]=np.asarray([.05,.35,.65,.95])[:,None]+np.arange(10)[None,:]*.001
    crossings=np.full((10,20),-1);crossings[:,j]=3
    result['mc_checkpoints']=dict(damage=damage,mode_keys=np.array(keys),sample_ids=np.arange(10),
        terminal_cycles=np.full(10,3),first_mode_crossings=crossings)
    result['mc_samples']=pd.DataFrame(dict(last_safe_checkpoint=[2]*10,status=['FAILURE_REACHED']*10))
    original=damage.copy();view=RULRandomView()
    view.path_count.setCurrentIndex(1 if path_count==10 else 0);view.set_result(result)
    legend=view.plot.plotItem.legend
    assert legend.columnCount==columns and legend.rowCount<=5
    labels=[label.text for _,label in legend.items]
    assert len(labels)==path_count+4
    assert all(f'样本ID {sample}' in labels for sample in range(path_count))
    view.random_paths.setChecked(False)
    assert legend.columnCount==1 and len(legend.items)==3
    np.testing.assert_array_equal(result['mc_checkpoints']['damage'],original)
    view.close()
