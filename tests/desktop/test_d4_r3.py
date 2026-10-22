import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from dataclasses import replace
import importlib.util,sys,copy
import numpy as np
import pandas as pd
import pytest
from PySide6.QtWidgets import QApplication,QAbstractSpinBox,QComboBox,QScrollArea
from PySide6.QtCore import Qt,QPoint,QPointF
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from steering_sim.desktop.app import MainWindow
from steering_sim.desktop.replay import ReplayControl,VehicleView,ChannelOverview,WHEELS,CHANNELS

ROOT=Path(__file__).resolve().parents[2]
def app():return QApplication.instance() or QApplication([])
def wheel(widget,amount=-120):
    p=widget.rect().center()
    e=QWheelEvent(QPointF(p),QPointF(widget.mapToGlobal(p)),QPoint(),QPoint(0,amount),Qt.NoButton,Qt.NoModifier,Qt.ScrollUpdate,False)
    QApplication.sendEvent(widget,e)

def test_parameter_wheel_never_edits_and_parent_scrolls():
    from steering_sim.desktop.app import STYLE
    qt=app();w=MainWindow();w.setStyleSheet(STYLE);w.resize(1250,780);w.show();qt.processEvents();p=w.pages[0]
    spin=p.angle;spin.setFocus();before=spin.value()
    scroll=spin.parentWidget()
    while not isinstance(scroll,QScrollArea):scroll=scroll.parentWidget()
    scroll.widget().setMinimumHeight(1300);qt.processEvents()
    assert scroll.verticalScrollBar().maximum()>0
    scroll.verticalScrollBar().setValue(0)
    wheel(spin);assert spin.value()==before
    assert scroll.verticalScrollBar().value()>0
    combo=p.command_type;combo.setFocus();before=combo.currentIndex();wheel(combo);assert combo.currentIndex()==before
    QTest.mouseClick(spin,Qt.LeftButton,pos=QPoint(spin.width()-15,8));assert spin.value()>10
    spin.lineEdit().selectAll();QTest.keyClicks(spin.lineEdit(),'7.5');QTest.keyClick(spin.lineEdit(),Qt.Key_Return);assert spin.value()==7.5
    p.tabs.setCurrentWidget(p.angle_detail_page)
    plot=p.angle_plot;plot.replace_curves([('测试',[0,1,2],[0,1,0],'#1976d2')]);plot.resize(500,250);plot.show();qt.processEvents()
    before=plot.viewRange();wheel(plot.viewport(),120);qt.processEvents();assert plot.viewRange()!=before
    w.close()

def samples():
    t=np.array([0.,1.,2.]);values={'time_s':t}
    for i,k in enumerate(WHEELS):values[f'wheel_{k}_actual_deg']=t*(i+1) if not k.startswith('axle3') else t*0
    for i,k in enumerate(CHANNELS):
        for suffix,a in [('x_m',.001),('x_ref_eff_m',.0011),('v_m_s',.001),('pA_mpa_g',10),('pB_mpa_g',3)]:values[f'{k}_{suffix}']=t*a*(i+1)
    return values

def test_display_replay_uses_actual_angles_and_all_channel_data():
    qt=app();r=ReplayControl();v=VehicleView();c=ChannelOverview();data=samples();original={k:a.copy() for k,a in data.items()}
    r.time_changed.connect(lambda _: (v.set_sample(r.sample()),c.set_sample(r.sample())))
    c.set_samples(data);r.set_samples(data);assert r.current_time==2
    r.seek(.5)
    for i,k in enumerate(WHEELS):assert v.wheel_angles[k]==(0 if k.startswith('axle3') else .5*(i+1))
    assert len(c.plots)==4 and len(c.gauges)==4
    assert c.gauges[2].position==.0015
    assert all(line.value()==.5 for line in c.cursors)
    assert 'A/B 15.00 / 4.50 MPa' in c.labels[2].text()
    assert len({(g.minimum,g.maximum) for g in c.gauges})>1
    data['wheel_axle3_left_actual_deg']=np.array([0.,.1,.2]);r.set_samples(data);r.seek(1)
    assert v.wheel_angles['axle3_left']==.1  # never hide the anomaly in graphics
    for k in original:
        if k!='wheel_axle3_left_actual_deg':np.testing.assert_array_equal(original[k],data[k])
    c.open_detail(2);assert c.dialogs[-1][0].isVisible();c.clear();assert c.frame.empty
    r.pause();r.close();v.close();c.close()

def test_mc_recording_does_not_change_existing_random_draws_or_lifetimes():
    from steering_sim.degradation import load_d3_config,MultiModeDegradationState
    from steering_sim.degradation.rul import MissionCycleProfile,MissionSegmentExposure
    from steering_sim.degradation.stochastic import monte_carlo_rul
    old_path=ROOT/'outputs/desktop/r3/baseline_r2/src/steering_sim/degradation/stochastic.py'
    spec=importlib.util.spec_from_file_location('steering_sim.degradation.r3_original_stochastic',old_path)
    old=importlib.util.module_from_spec(spec);sys.modules[spec.name]=old;spec.loader.exec_module(old)
    config=load_d3_config(ROOT/'configs/degradation/d3_rul_models.json');raw=copy.deepcopy(config.raw)
    # Synthetic test coefficients, never written to the engineering configuration.
    for modes in raw['modes'].values():
        for item in modes.values():item.update(rate=.01,failure_damage=.05,gamma_scale_damage=.004)
    config=replace(config,raw=raw);initial=MultiModeDegradationState.healthy()
    segment=MissionSegmentExposure('TEST',1,2592000,30,{k:1. for k in initial.modes})
    profile=MissionCycleProfile((segment,),{},{},())
    a=old.monte_carlo_rul(initial,profile,config,sample_count=128,random_seed=91,maximum_cycles=8)
    b=monte_carlo_rul(initial,profile,config,sample_count=128,random_seed=91,maximum_cycles=8,record_all_states=True)
    assert a.quantiles==b.quantiles and a.path_rows==b.path_rows and a.censored_count==b.censored_count
    for before,after in zip(a.sample_rows,b.sample_rows):assert all(after[k]==v for k,v in before.items())
    assert b.checkpoint_damage.shape[1:]==(128,20)
    for i,terminal in enumerate(b.terminal_cycles):
        assert np.isfinite(b.checkpoint_damage[:terminal+1,i]).all()
        assert np.isnan(b.checkpoint_damage[terminal+1:,i]).all()
        assert b.sample_rows[i]['remaining_complete_cycles']==terminal-1

def test_quality_cache_key_includes_conditions_and_versions():
    from steering_sim.desktop.services import DesktopCalculationService
    from steering_sim.quality_assessment import standard_cases
    case=standard_cases()[0];key=DesktopCalculationService.quality_cache_key
    base=key(case,{'model':'a'},{'dt':.0005})
    assert base!=key(replace(case,speed_kmh=5),{'model':'a'},{'dt':.0005})
    assert base!=key(case,{'model':'b'},{'dt':.0005})
    assert base!=key(case,{'model':'a'},{'dt':.002})

def random_view_result():
    from steering_sim.degradation import load_d3_config,MultiModeDegradationState
    from steering_sim.hydraulics_engineering import load_parameters
    cfg=load_d3_config(ROOT/'configs/degradation/d3_rul_models.json')
    keys=list(MultiModeDegradationState.healthy().modes);key='valve:channel_front:response_lag';j=keys.index(key)
    matrix=np.zeros((6,12,20));terminals=[];crossing=np.full((12,20),-1);rows=[]
    for sample in range(12):
        slope=.2+.01*sample;terminal=int(np.ceil(.9/slope));terminals.append(terminal)
        matrix[:,sample,j]=np.minimum(1.,np.arange(6)*slope);matrix[terminal+1:,sample]=np.nan;crossing[sample,j]=terminal
        rows.append(dict(sample_id=sample,status='FAILURE_REACHED',failure_cycle=terminal,last_safe_checkpoint=terminal-1))
    return dict(summary={'failure_reasons':[key+' damage reached limit']},
        mc_checkpoints=dict(damage=matrix,mode_keys=np.array(keys),sample_ids=np.arange(12),terminal_cycles=np.array(terminals),first_mode_crossings=crossing),
        mc_models=cfg.raw['modes'],physical_reference_parameters=load_parameters(ROOT/'configs/j1r2/engineering_hydraulics.json'),
        mc_samples=pd.DataFrame(rows))

def test_random_view_uses_full_n_and_stops_band_before_first_failure():
    from steering_sim.desktop.rul_view import RULRandomView,mapped_metric
    qt=app();view=RULRandomView();result=random_view_result();original=result['mc_checkpoints']['damage'].copy();view.set_result(result)
    assert view.mode_selector.currentData()=='valve:channel_front:response_lag'
    assert view.displayed_ids==list(range(5)) and view.common_safe_cycle==2
    stats=view.statistics_table.frame;assert set(stats.sample_count)=={12}
    assert stats.iloc[-1]['mean']==np.mean(original[2,:,5])
    assert stats.mission_cycle.max()==2
    view.path_count.setCurrentIndex(1);assert view.displayed_ids==list(range(10))
    for sample,frame in view.paths_table.frame.groupby('sample_id'):
        assert frame.mission_cycle.max()==result['mc_checkpoints']['terminal_cycles'][sample]
    metric='response_time_s';view.metric.setCurrentIndex(view.metric.findData(metric))
    matrix,limit,unit=mapped_metric(result,'valve:channel_front:response_lag',metric)
    assert unit=='s' and limit>0
    assert view.statistics_table.frame.iloc[-1].p05==np.quantile(matrix[2],.05)
    view.center.setCurrentIndex(1);view.band.setChecked(False)
    np.testing.assert_array_equal(original,result['mc_checkpoints']['damage'])
    view.clear();assert not view.plot.listDataItems();view.close()

def test_quality_actual_pair_and_cache_keep_conditions_and_healthy_parameters(tmp_path):
    from steering_sim.desktop.services import DesktopCalculationService,HEALTHY,file_hash
    service=DesktopCalculationService(tmp_path);before=file_hash(HEALTHY)
    run=lambda source,severity:service.run_quality(state_source=source,severity=severity,progress=lambda *_:None,is_cancelled=lambda:False)
    healthy=run('healthy',0)
    assert healthy['comparison_frame']['change'].eq(0).all()
    for pair in healthy['comparison_dynamics']:
        assert pair['healthy'].case==pair['current'].case
        for key in pair['healthy'].samples:np.testing.assert_array_equal(pair['healthy'].samples[key],pair['current'].samples[key])
    worn=run('specified_heavy',.85)
    assert all(pair['baseline_cache_hit'] for pair in worn['comparison_dynamics'])
    assert any(abs(worn['comparison_frame']['change'])>1e-9)
    assert file_hash(HEALTHY)==before
    from steering_sim.desktop.pages import QualityPage
    page=QualityPage();page.task_finished(worn);page.test_case.setCurrentIndex(1)
    assert page.banner.label.text().count('；')<=2
    assert len(page.banner.label.text())<250
    pair=worn['comparison_dynamics'][1];items=page.angle_plot.listDataItems()
    assert len(items)==3
    np.testing.assert_array_equal(items[-1].xData,pair['current'].samples['time_s'])
    np.testing.assert_array_equal(items[-1].yData,pair['current'].samples['wheel_axle1_right_actual_deg'])
    # No zero padding/extrapolation, even when a recorded current run ends earlier.
    truncated=copy.deepcopy(worn);dynamic=truncated['comparison_dynamics'][1]['current']
    dynamic.samples.update({k:np.asarray(v)[:5] for k,v in dynamic.samples.items()})
    page.task_finished(truncated);page.test_case.setCurrentIndex(1)
    assert len(page.angle_plot.listDataItems()[-1].xData)==5
    page.close()

def test_quality_grade_chart_is_discrete_checkpoint_scatter():
    from steering_sim.desktop.pages import RULPage
    qt=app();page=RULPage()
    data=dict(kind='rul',summary={'prediction_status':'NOT_REACHED_WITHIN_HORIZON'},history=pd.DataFrame(),modes=pd.DataFrame(),
        mc_summary=pd.DataFrame(columns=['metric','value']),mc_samples=pd.DataFrame({'failure_cycle':[]}),
        quality=pd.DataFrame({'mission_cycle':[0,4,10],'rated_quality_grade':['HEALTHY','SUBHEALTHY','DANGEROUS']}))
    page.task_finished(data);curve=page.quality_plot.listDataItems()[0]
    assert curve.opts['pen'] is None and curve.opts['symbol']=='o'
    assert list(curve.yData)==[0,1,3]
    assert '确定性' in page.damage_plot.plotItem.titleLabel.text or not page.damage_plot.listDataItems()
    page.close()


def test_r3_project_roundtrip_restores_replay_and_view_options_without_old_results(tmp_path):
    from steering_sim.desktop.models import ProjectState
    qt=app();first=MainWindow();simulation,degradation,quality,rul=(first.pages[i] for i in (0,2,3,4))
    simulation._saved_replay_time=1.25
    simulation.replay.speed.setCurrentIndex(simulation.replay.speed.findData(5))
    simulation.wheel_selector.setCurrentIndex(9);simulation.cylinder_selector.setCurrentIndex(2)
    simulation.channel_overview.link.setChecked(False);simulation.detail_markers.setChecked(True)
    simulation.channel_markers.setChecked(True);simulation.tabs.setCurrentWidget(simulation.channel_overview)
    degradation.component.setCurrentIndex(degradation.component.findData('valve:channel_rear_2'))
    degradation.view_mode.setCurrentIndex(1);degradation._saved_metric='response_time_s'
    degradation.path_count.setCurrentIndex(1);degradation.center.setCurrentIndex(1)
    degradation.show_paths.setChecked(True);degradation.show_band.setChecked(False)
    degradation.show_threshold.setChecked(True)
    quality._saved_case='STD_L30'
    quality.quality_wheel.setCurrentIndex(quality.quality_wheel.findData('axle5_left'))
    quality.supply_rail.setCurrentIndex(quality.supply_rail.findData('rear'))
    record=random_view_result();rul.random_view.set_result(record)
    rul.random_view.path_count.setCurrentIndex(1);rul.random_view.center.setCurrentIndex(1)
    rul.random_view.metric.setCurrentIndex(rul.random_view.metric.findData('response_time_s'))
    rul.random_view.band.setChecked(False);rul.random_view.threshold.setChecked(False)
    payload={p.page_id:p.project_payload() for p in first.pages}
    assert payload['rul']['random_view']['representative_ids']==list(range(10))
    target=tmp_path/'中文回放工程.d4project.json'
    ProjectState(page_inputs=payload).save(target)
    restored=ProjectState.load(target);second=MainWindow();second._apply_page_inputs(restored.page_inputs)
    s,d,q,r=(second.pages[i] for i in (0,2,3,4))
    assert s._saved_replay_time==1.25 and s.replay.speed.currentData()==5
    assert s.wheel_selector.currentIndex()==9 and s.cylinder_selector.currentIndex()==2
    assert not s.channel_overview.link.isChecked()
    assert s.detail_markers.isChecked() and s.channel_markers.isChecked()
    assert s.tabs.currentWidget() is s.channel_overview
    assert d.component.currentData()=='valve:channel_rear_2' and d._saved_metric=='response_time_s'
    assert d.path_count.currentData()==10 and d.center.currentData()=='p50'
    assert d.show_paths.isChecked() and not d.show_band.isChecked() and d.show_threshold.isChecked()
    assert q._saved_case=='STD_L30' and q.quality_wheel.currentData()=='axle5_left'
    assert q.supply_rail.currentData()=='rear'
    r.random_view.set_result(record)
    assert r.random_view.mode_selector.currentData()=='valve:channel_front:response_lag'
    assert r.random_view.metric.currentData()=='response_time_s'
    assert r.random_view.displayed_ids==list(range(10)) and r.random_view.center.currentData()=='p50'
    assert not r.random_view.band.isChecked() and not r.random_view.threshold.isChecked()
    # Applying settings is not an implicit rerun or an implicit import of old results.
    assert second.results=={} and s.last_result is None and s.replay.frame.empty
    first.close();second.close()


def test_explicit_historical_replay_checks_csv_hash_without_solver(tmp_path,monkeypatch):
    from dataclasses import asdict
    from steering_sim.desktop import services
    from steering_sim.desktop.response_analysis import ResponseCriteria
    service=services.DesktopCalculationService(tmp_path/'service')
    t=np.arange(5,dtype=float);data={'time_s':t}
    for i,key in enumerate(WHEELS):
        value=0 if key.startswith('axle3_') else .1*(i+1)
        for suffix in ('command_deg','actual_deg'):data[f'wheel_{key}_{suffix}']=np.full_like(t,value)
    for i,key in enumerate(CHANNELS):
        for suffix,value in (('x_ref_eff_m',.001*(i+1)),('x_m',.001*(i+1)),('v_m_s',0.)):
            data[f'{key}_{suffix}']=np.full_like(t,value)
    path=tmp_path/'原始积分记录.csv';pd.DataFrame(data).to_csv(path,index=False)
    reference=dict(csv_path=str(path),csv_sha256=services.file_hash(path),
        criteria=asdict(ResponseCriteria()),command_completion_s=1.,
        result_metadata={'calculation_success':True,'runtime_s':12.34})
    calls=[]
    def forbidden(*args,**kwargs):
        calls.append('solver');raise AssertionError('结果回放不得调用积分器')
    monkeypatch.setattr(services,'_runner',forbidden)
    monkeypatch.setattr(services.J0Runner,'run_case',forbidden)
    result=service.load_simulation_record(reference=reference,progress=lambda *_:None,is_cancelled=lambda:False)
    assert result['provenance_kind']=='HISTORICAL_REPLAY' and result['runtime_s']==12.34
    assert len(result['wheel_response_table'])==12 and len(result['cylinder_response_table'])==4
    for key,expected in data.items():np.testing.assert_allclose(result['samples'][key],expected)
    qt=app();control=ReplayControl();control.set_samples(result['samples']);control.seek(1.25)
    assert control.sample()['wheel_axle5_left_actual_deg']==pytest.approx(.9)
    assert not calls
    # Even a harmless content change invalidates the explicit historical reference.
    path.write_bytes(path.read_bytes()+b'\n')
    with pytest.raises(ValueError,match='哈希改变'):
        service.load_simulation_record(reference=reference,progress=lambda *_:None,is_cancelled=lambda:False)
    assert not calls;control.close()


def test_page03_five_ten_paths_are_view_only_and_keep_full_sample_statistics(monkeypatch):
    from steering_sim.degradation import MultiModeDegradationState,load_d3_config
    from steering_sim.degradation.rul import MissionSegmentExposure,MissionCycleProfile
    from steering_sim.degradation.forecast import mission_forecast
    from steering_sim.hydraulics_engineering import load_parameters
    from steering_sim.desktop.pages import DegradationPage
    from steering_sim.degradation import forecast,stochastic
    config=load_d3_config(ROOT/'configs/degradation/d3_rul_models.json')
    healthy=load_parameters(ROOT/'configs/j1r2/engineering_hydraulics.json')
    initial=MultiModeDegradationState.healthy()
    segments=tuple(MissionSegmentExposure(f'S{i}',i,1296000,15*i,{key:30. for key in initial.modes}) for i in (1,2))
    result=mission_forecast(MissionCycleProfile(segments,{},{},()),initial,healthy,config,sample_count=128,random_seed=19)
    result['models']=config.raw['modes']
    original=result['paths'].copy();statistics=result['statistics'].copy(deep=True)
    def forbidden(*args,**kwargs):raise AssertionError('显示切换不得重新抽样')
    monkeypatch.setattr(forecast,'gamma_advance',forbidden);monkeypatch.setattr(stochastic,'gamma_advance',forbidden)
    qt=app();page=DegradationPage();page.last_result=result;page._metrics();page.show_paths.setChecked(True)
    assert set(page.path_table.frame.sample_id)==set(range(5))
    page.path_count.setCurrentIndex(1)
    assert set(page.path_table.frame.sample_id)==set(range(10))
    key=page.component.currentData()+':'+page.metric.currentData()
    for sample_id,rows in page.path_table.frame.groupby('sample_id'):
        np.testing.assert_array_equal(rows.value,result['representatives'][key][:,sample_id])
    page.view_mode.setCurrentIndex(1)
    page.metric.setCurrentIndex(page.metric.findData('volumetric_efficiency'))
    page.center.setCurrentIndex(1);page.show_band.setChecked(False);page.show_band.setChecked(True)
    stats=result['statistics'].loc[result['statistics'].metric=='pump:front:volumetric_efficiency']
    main=page.damage_plot.listDataItems()[0]
    np.testing.assert_array_equal(main.yData,stats.p50.to_numpy())
    assert page.project_payload()['representative_ids']==list(range(10))
    assert '全部128' in page.damage_plot.toolTip()
    np.testing.assert_array_equal(result['paths'],original)
    pd.testing.assert_frame_equal(result['statistics'],statistics)
    page.close()


def test_rul_right_censored_paths_keep_full_horizon_and_no_false_crossing():
    from steering_sim.degradation import MultiModeDegradationState,load_d3_config
    from steering_sim.degradation.rul import MissionSegmentExposure,MissionCycleProfile
    from steering_sim.degradation.stochastic import monte_carlo_rul
    from steering_sim.hydraulics_engineering import load_parameters
    from steering_sim.desktop.rul_view import RULRandomView
    config=load_d3_config(ROOT/'configs/degradation/d3_rul_models.json')
    initial=MultiModeDegradationState.healthy()
    segment=MissionSegmentExposure('NO_LOAD',1,2592000,30,{key:0. for key in initial.modes})
    mc=monte_carlo_rul(initial,MissionCycleProfile((segment,),{},{},()),config,
        sample_count=12,random_seed=23,maximum_cycles=2,record_all_states=True)
    assert mc.censored_count==12 and mc.censored_fraction==1.
    assert all(value is None for value in mc.quantiles.values())
    for row in mc.sample_rows:
        assert row['status']=='RIGHT_CENSORED' and row['failure_cycle']==''
        assert row['remaining_complete_cycles']=='>=2' and row['last_safe_checkpoint']==2
        assert row['first_exceedance_checkpoint'] is None and row['failure_mode_keys']==''
        assert row['detection_resolution']=='CYCLE_END_CHECKPOINT'
    result=dict(summary={'failure_reasons':[]},mc_checkpoints=dict(damage=mc.checkpoint_damage,
        mode_keys=np.array(mc.mode_keys),sample_ids=np.arange(12),terminal_cycles=mc.terminal_cycles,
        first_mode_crossings=mc.first_mode_crossings),mc_models=config.raw['modes'],
        physical_reference_parameters=load_parameters(ROOT/'configs/j1r2/engineering_hydraulics.json'),
        mc_samples=pd.DataFrame(mc.sample_rows))
    qt=app();view=RULRandomView();view.set_result(result)
    assert view.common_safe_cycle==2 and view.displayed_ids==list(range(5))
    assert set(view.statistics_table.frame.sample_count)=={12}
    assert view.statistics_table.frame.mission_cycle.tolist()==[0,1,2]
    terminal=view.paths_table.frame.loc[view.paths_table.frame.mission_cycle==2]
    assert set(terminal.status)=={'RIGHT_CENSORED'}
    assert not any('首次越限' in str(value) for value in view.paths_table.frame.status)
    assert all(item.opts.get('symbol')!='x' for item in view.plot.listDataItems())
    view.close()


@pytest.mark.parametrize('reference_kind',('old_file_reference','missing_file','explicit_empty_rows'))
def test_open_project_replaces_previous_mission_or_clears_it(tmp_path,monkeypatch,reference_kind):
    from steering_sim.desktop.app import QFileDialog
    from steering_sim.desktop.models import ProjectState
    from steering_sim.desktop.services import EXAMPLE_SPECTRUM
    from steering_sim.degradation.spectrum import normalize_columns
    qt=app();window=MainWindow();page=window.pages[1]
    fresh=normalize_columns(pd.read_csv(EXAMPLE_SPECTRUM)).iloc[:1].copy()
    fresh['segment_id']='本次工程任务'
    referenced=tmp_path/'中文任务谱.csv';fresh.to_csv(referenced,index=False,encoding='utf-8-sig')
    prior=fresh.copy();prior['segment_id']='上个工程残留';page.load_frame(prior,'old.csv')
    if reference_kind=='old_file_reference':
        # Old projects have no embedded rows; the top-level reference is authoritative.
        state=ProjectState(spectrum_path=referenced.name,page_inputs={'spectrum':{'path':'obsolete.csv'}})
    elif reference_kind=='missing_file':
        state=ProjectState(spectrum_path=str(tmp_path/'缺失.csv'))
    else:
        # An explicit empty mission is not permission to reload the referenced file.
        state=ProjectState(spectrum_path=str(referenced),page_inputs={'spectrum':{'rows':[],'path':''}})
    saved=tmp_path/'工程.d4project.json';state.save(saved)
    monkeypatch.setattr(QFileDialog,'getOpenFileName',lambda *_a,**_k:(str(saved),'D4工程 (*.json)'))
    window.results={'simulation':{'old':True}};window.project.completed_modules={'simulation':True}
    window.open_project()
    if reference_kind=='old_file_reference':
        assert page.frame().segment_id.tolist()==['本次工程任务']
        assert Path(page.path)==referenced
    else:
        assert page.frame().empty and not page.path
    if reference_kind=='missing_file':assert '任务谱未恢复' in window.status_text.text()
    assert not window.results and not window.project.completed_modules
    assert all(p.last_result is None for p in window.pages if p.page_id!='spectrum')
    window.close()


def test_batch_report_is_fast_estimate_without_fabricated_dynamic_results():
    from steering_sim.desktop.reporting import build_report
    batch=dict(kind='batch',row_count=3111,runtime_s=2.345,output_dir='batch_actual',
        rows=pd.DataFrame({'target_outer_angle_deg':[0]}),grids={
            'target_outer_angle_deg':[-30,0,30],'speed_kmh':[0,40,80],
            'friction_coefficient':[.70,.75,.80]})
    text=build_report({'name':'批量估计工程'},{'simulation':batch},{'input_hash':'synthetic-test'})
    assert 'FAST_BATCH_ESTIMATE' in text and '3111组' in text
    assert '不是完整22状态动态仿真' in text and '一桥外轮转角网格' in text
    assert '0.7、0.75、0.8' in text and 'batch_actual' in text
    assert '## 2. 机械—液压—控制联合仿真' not in text
    assert '液压跟踪达标：' not in text and '阶跃兼容模式' not in text
    assert '指令完成时间：' not in text and '整机共同稳态时间：' not in text


def test_initial_hard_limit_has_no_safe_band_in_view_or_report():
    from steering_sim.desktop.rul_view import RULRandomView
    from steering_sim.desktop.reporting import build_report
    result=random_view_result();record=result['mc_checkpoints'];keys=record['mode_keys'].tolist()
    key='valve:channel_front:response_lag';index=keys.index(key)
    limit=result['mc_models']['valve']['response_lag']['failure_damage']
    record['damage']=record['damage'][:1].copy();record['damage'][0,:,index]=limit
    record['terminal_cycles']=np.zeros(12,dtype=int)
    record['first_mode_crossings']=np.full((12,20),-1,dtype=int);record['first_mode_crossings'][:,index]=0
    # The initial hard-limit guard also protects against old records calling checkpoint 0 safe.
    result['mc_samples']=pd.DataFrame([dict(sample_id=i,status='FAILURE_REACHED',
        failure_cycle=0,last_safe_checkpoint=0) for i in range(12)])
    qt=app();view=RULRandomView();view.set_result(result)
    assert view.common_safe_cycle==-1 and view.statistics_table.frame.empty
    assert '共同安全范围：无' in view.scope.text()
    assert set(view.paths_table.frame.status)=={'所选模式首次越限'}
    text=build_report({'name':'初态已越限'},{'rul':result},{})
    assert '无共同安全检查点（初始状态已达到硬阈值）' in text
    assert '共同安全范围：第0～0循环' not in text
    view.close()
