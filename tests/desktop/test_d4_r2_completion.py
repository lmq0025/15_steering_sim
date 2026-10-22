from pathlib import Path
from dataclasses import replace
import numpy as np
import pytest

from steering_sim.degradation.spectrum import TaskSegment,TaskSpectrum,SpectrumError,load_task_spectrum
from steering_sim.degradation.multimode import MultiModeDegradationState,load_d3_config,parameters_from_multimode
from steering_sim.degradation.rul import MissionSegmentExposure,MissionCycleProfile,advance_segment
from steering_sim.degradation.stochastic import gamma_advance,monte_carlo_rul
from steering_sim.degradation.forecast import mission_forecast,physical_curves
from steering_sim.hydraulics_engineering import load_parameters

ROOT=Path(__file__).resolve().parents[2]
CFG=ROOT/'configs/degradation/d3_rul_models.json'
HEALTHY=ROOT/'configs/j1r2/engineering_hydraulics.json'


def profile(config,exposure=1):
    keys=MultiModeDegradationState.healthy().modes
    segment=MissionSegmentExposure('test',1,2592000,30,{key:exposure for key in keys})
    return MissionCycleProfile((segment,),{}, {},())


def test_explicit_rate_strict_duration_and_old_compatibility():
    args=dict(segment_id='S',speed_kmh=5,target_outer_angle_deg=10,
              segment_duration_s=59,friction_coefficient=.8,axle_mass_t=(11.5,)*6,pump_running=True)
    old=TaskSegment(**args)
    assert old.seconds_per_degree is None
    spectrum=TaskSpectrum((replace(old,seconds_per_degree=6),),Path('test'))
    with pytest.raises(SpectrumError,match='严格模式'): spectrum.validate_transitions()
    replace(spectrum,segments=(replace(old,segment_duration_s=60,seconds_per_degree=6),)).validate_transitions()
    data=load_task_spectrum(ROOT/'data/degradation/r2/task_spectrum_30day_example.csv')
    assert data.total_days==30 and all(s.seconds_per_degree==6 for s in data.segments)


def test_twenty_states_match_authoritative_d3_and_physical_mapping():
    cfg=load_d3_config(CFG); healthy=load_parameters(HEALTHY)
    initial=MultiModeDegradationState.healthy(); p=profile(cfg,100)
    result=mission_forecast(p,initial,healthy,cfg)
    expected,_=advance_segment(initial,p.segments[0],cfg)
    assert result['final_state']==expected and len(result['mode_keys'])==20
    physical=parameters_from_multimode(healthy,expected,cfg)
    last=result['curve_frame'].iloc[-1]
    assert last['pump:front:mechanical_efficiency']==pytest.approx(physical.degradation.pump('front').mechanical_efficiency)
    assert last['valve:channel_rear_2:response_time_s']==pytest.approx(healthy.channel('channel_rear_2').valve.lag_time_s*physical.degradation.valve('channel_rear_2').lag_scale)
    assert last['cylinder:channel_rear_3:friction_scale']==pytest.approx(physical.degradation.cylinder('channel_rear_3').friction_scale)


def test_gamma_1000_real_paths_reproducible_monotone_and_parameter_quantiles():
    cfg=load_d3_config(CFG); healthy=load_parameters(HEALTHY); initial=MultiModeDegradationState.healthy()
    p=profile(cfg,30)
    a=mission_forecast(p,initial,healthy,cfg,sample_count=1000,random_seed=43)
    b=mission_forecast(p,initial,healthy,cfg,sample_count=1000,random_seed=43)
    assert a['paths'].shape==(2,1000,20)
    np.testing.assert_array_equal(a['paths'],b['paths'])
    assert np.all(np.diff(a['paths'],axis=0)>=0) and np.all(a['paths']>=0)
    assert not np.array_equal(a['paths'][-1,:,0],a['paths'][-1,:,2])
    stats=a['statistics']
    assert (stats.p05<=stats.p50).all() and (stats.p50<=stats.p95).all()
    row=stats.loc[(stats.day==30)&(stats.metric=='pump:front:volumetric_efficiency')].iloc[0]
    mapped,_=physical_curves(a['paths'],a['mode_keys'],healthy,cfg)
    assert row.p05==pytest.approx(np.quantile(mapped['pump:front:volumetric_efficiency'][-1],.05))
    assert mapped['pump:front:volumetric_efficiency'][-1].mean()<1


def test_conditional_mean_and_equivalent_split_statistics():
    cfg={'maximum_damage':1.,'state_factor_alpha':0.,'rate':.01,'gamma_scale_damage':.002}
    n=100000; old=np.full(n,.2)
    one=gamma_advance(old,1,cfg,np.random.default_rng(1))
    rng=np.random.default_rng(2)
    split=gamma_advance(gamma_advance(old,.4,cfg,rng),.6,cfg,rng)
    assert abs((one-old).mean()-.01)<8e-5
    assert abs(one.mean()-split.mean())<1e-4
    assert abs(one.var()-split.var())<1e-6
    nonlinear=dict(cfg,state_factor_alpha=.35)
    next_state=gamma_advance(old,1,nonlinear,np.random.default_rng(3))
    expected=(.2+1/.35)*np.expm1(.35*.01)
    assert abs((next_state-old).mean()-expected)<8e-5


def test_page03_and05_same_core_first_cycle_distribution():
    cfg=load_d3_config(CFG); healthy=load_parameters(HEALTHY); initial=MultiModeDegradationState.healthy()
    p=profile(cfg,30)
    a=mission_forecast(p,initial,healthy,cfg,sample_count=4000,random_seed=21)
    b=monte_carlo_rul(initial,p,cfg,sample_count=4000,random_seed=21,maximum_cycles=1,stored_paths=4000)
    key=next(iter(initial.modes)).replace(':','_')
    values=np.array([r[key] for r in b.path_rows])
    samples=a['paths'][-1,:,0]
    assert abs(samples.mean()-values.mean())<5*np.sqrt(samples.var()/4000+values.var()/4000)
    assert b.censored_count==4000


def test_chinese_exports_and_random_project_roundtrip(tmp_path):
    import os
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    from steering_sim.desktop.app import MainWindow
    from steering_sim.desktop.models import ProjectState
    from steering_sim.desktop.widgets import DataTable
    import pandas as pd
    qt=QApplication.instance() or QApplication([])
    window=MainWindow();page=window.pages[2]
    page.forecast_mode.setCurrentIndex(1);page.sample_count.setValue(1000);page.seed.setValue(99)
    page.component.setCurrentIndex(7);page.view_mode.setCurrentIndex(1);page.interval.setCurrentIndex(1)
    page.show_threshold.setChecked(True)
    payload=page.project_payload()
    path=tmp_path/'中文工程.d4project.json'
    state=ProjectState(page_inputs={'degradation':payload});state.save(path)
    window._apply_page_inputs(ProjectState.load(path).page_inputs)
    assert page.sample_count.value()==1000 and page.seed.value()==99
    assert page.component.currentIndex()==7 and page.interval.currentData()==95
    assert page.show_threshold.isChecked()
    table=DataTable();table.set_frame(pd.DataFrame({'component_type':['pump'],'degradation_mode':['mechanical_loss']}))
    csv=tmp_path/'中文.csv';table.export(csv)
    text=csv.read_text(encoding='utf-8-sig')
    assert '部件类型' in text and '齿轮泵' in text and '机械损失' in text
    window.close()


def test_rate_changes_flow_but_not_completed_sliding_distance():
    from steering_sim.desktop.services import _runner,D1_CONFIG
    from steering_sim.degradation import D1Predictor,load_degradation_config,DegradationState
    from steering_sim.j0_coupling.runner import CHANNEL_ORDER
    predictor=D1Predictor(_runner(),load_degradation_config(D1_CONFIG))
    state=DegradationState.healthy(CHANNEL_ORDER)
    segment=TaskSegment('rate',5,10,120,.8,(11.5,)*6,True,seconds_per_degree=6)
    slow=predictor._features(0,segment,state,True)
    fast=predictor._features(0,replace(segment,seconds_per_degree=3),state,True)
    assert slow['strokes_m']==fast['strokes_m']
    assert slow['transition_time_s']==60 and fast['transition_time_s']==30
    assert fast['rail_features']['front']['motion_flow_m3_s']==pytest.approx(2*slow['rail_features']['front']['motion_flow_m3_s'])
    assert predictor.cache_misses==2


def test_plot_accepts_filtered_pandas_series_without_zero_index():
    import os
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    import pandas as pd
    from PySide6.QtWidgets import QApplication
    from steering_sim.desktop.widgets import EngineeringPlot
    qt=QApplication.instance() or QApplication([])
    x=pd.Series([0.,1.],index=[100,101]);y=pd.Series([.9,.8],index=[100,101])
    p=EngineeringPlot('测试','效率','天');p.replace_curves([('实际参数',x,y,'#1976d2')])
    band=p.add_prediction_band(x,y-.01,y+.01)
    assert band.path().elementCount()>0 and band.boundingRect().height()>0
    p.close()


def test_typed_sort_and_chinese_spectrum_export_roundtrip(tmp_path,monkeypatch):
    import os
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    import pandas as pd
    from PySide6.QtWidgets import QApplication,QFileDialog
    from PySide6.QtCore import Qt
    from steering_sim.desktop.widgets import DataTable
    from steering_sim.desktop.pages import SpectrumPage
    from steering_sim.desktop.services import DesktopCalculationService
    qt=QApplication.instance() or QApplication([])
    table=DataTable();table.set_frame(pd.DataFrame({'numeric':[2.,10.,-1.]}))
    assert table.frame.numeric.tolist()==[2.,10.,-1.]
    table.proxy.sort(0,Qt.AscendingOrder)
    assert table.frame.numeric.tolist()==[-1.,2.,10.]
    page=SpectrumPage();page.load_frame(pd.read_excel(ROOT/'data/degradation/r2/task_spectrum_30day_example.xlsx'))
    target=tmp_path/'中文任务谱.csv';captured=[]
    monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *a,**k:(str(target),''))
    page.run_requested.connect(lambda name,payload:captured.append(payload))
    page.export_file()
    DesktopCalculationService(tmp_path).export_table(**captured[0],progress=lambda *_:None,is_cancelled=lambda:False)
    profile=load_task_spectrum(target)
    assert profile.total_days==30 and len(profile.segments)==330
    assert all(s.seconds_per_degree==6 for s in profile.segments)
    assert profile.segments[0].pump_running is False
    assert '每度转向时间（秒/度）' in target.read_text(encoding='utf-8-sig')
    page.close();table.close()


def test_formal_visible_enums_and_plot_menu_are_chinese():
    import os
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    from steering_sim.desktop.localization import cn
    from steering_sim.desktop.widgets import EngineeringPlot
    qt=QApplication.instance() or QApplication([])
    assert cn('standard')=='标准工况'
    assert cn('D4_REAL_22_STATE')=='正式22状态动态计算'
    assert cn('equivalent_range')=='等效载荷范围'
    assert '目标行驶轨迹' in cn('VEHICLE_DYNAMIC_INFEASIBLE')
    assert '一二桥' in cn('limiter_count:valve:channel_front')
    plot=EngineeringPlot('测试');menu=plot.chinese_context_menu()
    assert [a.text() for a in menu.actions() if not a.isSeparator()]==[
        '复位并显示全部数据','显示／隐藏网格','显示／隐藏图例','保存当前图表为PNG']
    menu.deleteLater();plot.close()


def test_censored_rul_result_clears_prior_distribution():
    import os
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    import pandas as pd
    from PySide6.QtWidgets import QApplication
    from steering_sim.desktop.pages import RULPage
    qt=QApplication.instance() or QApplication([])
    page=RULPage()
    data=dict(kind='rul',summary={'prediction_status':'NOT_REACHED_WITHIN_HORIZON'},
        history=pd.DataFrame({'mission_cycle':[1,2],'pump_front_leakage_wear':[.1,.2]}),
        quality=pd.DataFrame(),modes=pd.DataFrame(),
        mc_summary=pd.DataFrame({'metric':['sample_count','right_censored_count'],'value':[1,0]}),
        mc_samples=pd.DataFrame({'failure_cycle':[2.]}))
    page.task_finished(data)
    assert len(page.distribution_plot.listDataItems())==1
    data['mc_samples']=pd.DataFrame({'failure_cycle':[np.nan]})
    data['mc_summary']=pd.DataFrame({'metric':['sample_count','right_censored_count','p05','p50','p95'],'value':[1,1,np.nan,np.nan,np.nan]})
    page.task_finished(data)
    assert not page.distribution_plot.listDataItems()
    assert '条件分位' in page.quantile_card.note_label.text()
    assert 'nan' not in page.quantile_card.value_label.text()
    page.close()


def test_mission_snapshot_survives_later_input_edits(tmp_path):
    import hashlib
    from steering_sim.desktop.services import DesktopCalculationService
    source=tmp_path/'任务谱.csv'
    original=(ROOT/'data/degradation/r2/task_spectrum_30day_example.csv').read_bytes()
    source.write_bytes(original)
    result=DesktopCalculationService(tmp_path/'out').run_degradation(
        spectrum_path=str(source),initial_state='healthy',progress=lambda *_:None,
        is_cancelled=lambda:False)
    snapshot=Path(result['output_dir'])/result['provenance']['input_snapshot']
    source.write_text('模拟下一次用户编辑',encoding='utf-8')
    assert snapshot.read_bytes()==original
    assert hashlib.sha256(snapshot.read_bytes()).hexdigest()==result['provenance']['spectrum_sha256']
    assert result['curve_frame'].day.iloc[-1]==30
