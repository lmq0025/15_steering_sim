"""Cycle-checkpoint statistics: never use survivor-only data as a full-N band."""
import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget,QVBoxLayout,QGridLayout,QComboBox,QCheckBox,QLabel,QTabWidget
from steering_sim.degradation.forecast import physical_curves
from steering_sim.degradation.multimode import D3Config, MultiModeDegradationState
from .widgets import EngineeringPlot,DataTable
from .localization import cn

PHYSICAL_METRICS={('pump','leakage_wear'):('leakage_coefficient','volumetric_efficiency'),
 ('pump','mechanical_loss'):('mechanical_efficiency',),
 ('valve','leakage_wear'):('leakage_coefficient','reference_leakage_lpm'),
 ('valve','response_lag'):('response_time_s','lag_scale'),
 ('cylinder','leakage_wear'):('leakage_coefficient','reference_leakage_lpm'),
 ('cylinder','friction_growth'):('friction_scale','reference_friction_n')}

def mapped_metric(result,key,metric):
    record=result['mc_checkpoints'];keys=tuple(record['mode_keys'].tolist());index=keys.index(key)
    return map_mode_metric(result,record['damage'],keys,key,metric)

def map_mode_metric(result,damage,keys,key,metric):
    """Use the official path-wise physical mapping for data and its hard limit."""
    index=keys.index(key)
    kind,component,mode=key.split(':');config=D3Config({'modes':result['mc_models']},'DISPLAY_MAP','ENGINEERING_DESIGN_ASSUMPTION')
    damage_threshold=float(config.mode(kind,mode)['failure_damage'])
    if metric=='damage':return damage[:,:,index],damage_threshold,'无量纲'
    physical_key=f'{kind}:{component}:{metric}'
    values,units=physical_curves(damage,keys,result['physical_reference_parameters'],config)
    threshold=np.zeros((1,1,len(keys)));threshold[0,0,index]=damage_threshold
    mapped,_=physical_curves(threshold,keys,result['physical_reference_parameters'],config)
    return values[physical_key],float(mapped[physical_key][0,0]),units[physical_key]

def deterministic_mode_record(result):
    """Recorded deterministic states only; never invent a zero initial state."""
    keys=tuple(MultiModeDegradationState.healthy().modes)
    frame=result.get('deterministic_modes',pd.DataFrame())
    if not frame.empty:
        frame=frame.copy()
        frame['mode_key']=frame.component_type+':'+frame.component_id+':'+frame.degradation_mode
        wide=frame.pivot(index='mission_cycle',columns='mode_key',values='damage').reindex(columns=keys).sort_index()
    else:
        history=result.get('history',pd.DataFrame())
        columns=[key.replace(':','_') for key in keys]
        if history.empty or not all(key in history for key in columns):return None
        wide=history.set_index('mission_cycle')[columns].copy();wide.columns=keys
    terminal=result.get('summary',{}).get('first_failure_cycle')
    if terminal is not None:wide=wide.loc[wide.index<=int(terminal)]
    if wide.empty or not np.isfinite(wide.to_numpy(dtype=float)).all():return None
    return np.asarray(wide.index,dtype=int),wide.to_numpy(dtype=float)[:,None,:],keys

class RULRandomView(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent);self.result=None;self.displayed_ids=[];self.common_safe_cycle=None
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);controls=QGridLayout()
        self.mode_selector=QComboBox();self.metric=QComboBox();self.path_count=QComboBox()
        for n in (5,10):self.path_count.addItem(f'{n}条代表路径',n)
        self.center=QComboBox();self.center.addItem('全样本均值','mean');self.center.addItem('全样本P50','p50')
        self.band=QCheckBox('P05～P95逐时刻区间');self.band.setChecked(True)
        self.threshold=QCheckBox('显示当前硬阈值');self.threshold.setChecked(True)
        for i,w in enumerate((self.mode_selector,self.metric,self.path_count,self.center,self.band,self.threshold)):controls.addWidget(w,i//3,i%3)
        layout.addLayout(controls);self.scope=QLabel('尚未计算');self.scope.setWordWrap(True);layout.addWidget(self.scope)
        options=QGridLayout();self.deterministic=QCheckBox('确定性轨迹');self.deterministic.setChecked(True)
        self.random_paths=QCheckBox('显示真实随机路径');self.random_paths.setChecked(True)
        options.addWidget(self.deterministic,0,0);options.addWidget(self.random_paths,0,1);layout.addLayout(options)
        self.tabs=QTabWidget();self.plot=EngineeringPlot('部件随机退化与首次越限','损伤','30天任务循环数')
        self.paths_table=DataTable();self.statistics_table=DataTable();self.deterministic_table=DataTable()
        self.tabs.addTab(self.plot,'限制部件与首次越限');self.tabs.addTab(self.deterministic_table,'确定性轨迹数据');self.tabs.addTab(self.paths_table,'代表路径数据');self.tabs.addTab(self.statistics_table,'全样本共同安全范围统计');layout.addWidget(self.tabs,1)
        self.mode_selector.currentIndexChanged.connect(self._metrics)
        for w in (self.metric,self.path_count,self.center):w.currentIndexChanged.connect(self.refresh)
        for w in (self.band,self.threshold,self.deterministic,self.random_paths):w.toggled.connect(self.refresh)
    def clear(self):
        self.result=None;self.displayed_ids=[];self.common_safe_cycle=None
        self.plot.replace_curves([]);self.paths_table.set_frame(pd.DataFrame());self.statistics_table.set_frame(pd.DataFrame());self.deterministic_table.set_frame(pd.DataFrame());self.scope.setText('尚未计算')
    def set_result(self,result):
        self.clear();self.result=result
        record=result.get('mc_checkpoints')
        self.mode_selector.blockSignals(True);self.mode_selector.clear()
        deterministic=deterministic_mode_record(result)
        if record is not None or deterministic is not None:
            keys=record['mode_keys'].tolist() if record is not None else list(deterministic[2])
            for key in keys:self.mode_selector.addItem(cn(key),key)
            reasons=result['summary'].get('failure_reasons',[])
            selected=getattr(self,'_saved_mode',None) or next((k for k in keys if any(str(r).startswith(k+' ') for r in reasons)),keys[0])
            self.mode_selector.setCurrentIndex(max(0,self.mode_selector.findData(selected)))
            self._saved_mode=None
        self.mode_selector.blockSignals(False);self._metrics()
    def _metrics(self):
        previous=self.metric.currentData();self.metric.blockSignals(True);self.metric.clear()
        key=self.mode_selector.currentData()
        if key:
            kind,_,mode=key.split(':');self.metric.addItem('累计损伤','damage')
            for name in PHYSICAL_METRICS[kind,mode]:self.metric.addItem(cn(name),name)
            selected=getattr(self,'_saved_metric',None) or previous
            self.metric.setCurrentIndex(max(0,self.metric.findData(selected)))
            self._saved_metric=None
        self.metric.blockSignals(False);self.refresh()
    def refresh(self):
        if not self.result:return
        key=self.mode_selector.currentData();metric=self.metric.currentData()
        if not key or not metric:return
        curves=[];deterministic=deterministic_mode_record(self.result);deterministic_crossing=None
        det_frame=pd.DataFrame();summary=self.result.get('summary',{})
        if deterministic is not None:
            cycles,damage,det_keys=deterministic
            mapped,threshold,unit=map_mode_metric(self.result,damage,det_keys,key,metric)
            values=mapped[:,0]
            limit=float(self.result['mc_models'][key.split(':')[0]][key.split(':')[2]]['failure_damage'])
            crossing=np.flatnonzero(damage[:,0,det_keys.index(key)]+1e-15>=limit)
            if len(crossing):deterministic_crossing=(int(cycles[crossing[0]]),float(values[crossing[0]]))
            det_frame=pd.DataFrame(dict(mission_cycle=cycles,metric=metric,value=values,unit=unit,
                mode_key=key,detection_resolution='RECORDED_CYCLE_OR_FAILURE_SEGMENT_END'))
            if self.deterministic.isChecked():curves.append(('确定性轨迹',cycles,values,'#122e52'))
        record=self.result.get('mc_checkpoints')
        if record is not None:
            matrix,threshold,unit=mapped_metric(self.result,key,metric)
            n=matrix.shape[1];keys=record['mode_keys'].tolist();j=keys.index(key)
        else:
            self.displayed_ids=[];self.common_safe_cycle=None
            if deterministic is None:
                self.plot.replace_curves([]);self.scope.setText('本结果缺少所选模式轨迹，不能由最大损伤推造部件曲线。');return
            self.plot.replace_curves(curves);self.paths_table.set_frame(pd.DataFrame());self.statistics_table.set_frame(pd.DataFrame())
            self._finish_plot(key,metric,unit,threshold,det_frame,deterministic_crossing,
                              '确定性推进；本次未启用随机分析。')
            return
        self.displayed_ids=record['sample_ids'][:min(self.path_count.currentData(),n)].tolist()
        samples=self.result['mc_samples'];safe=int(pd.to_numeric(samples['last_safe_checkpoint']).min())
        # Do not label an initially violated threshold as a safe state.
        initial=record['damage'][0];limits=np.array([self.result['mc_models'][k.split(':')[0]][k.split(':')[2]]['failure_damage'] for k in keys])
        if np.any(initial+1e-15>=limits):safe=-1
        self.common_safe_cycle=safe;stats=pd.DataFrame()
        if safe>=0:
            data=matrix[:safe+1]
            if not np.isfinite(data).all():raise ValueError('共同安全范围缺少样本记录，不生成全样本预测带')
            q=np.quantile(data,[.05,.5,.95],axis=1)
            stats=pd.DataFrame(dict(mission_cycle=np.arange(safe+1),sample_count=n,metric=metric,mean=data.mean(axis=1),p05=q[0],p50=q[1],p95=q[2],unit=unit))
            curves.append((f'全{n}样本'+('均值' if self.center.currentData()=='mean' else 'P50')+'（共同安全范围）',stats.mission_cycle,stats[self.center.currentData()],'#1976d2'))
        colors=['#78909c','#9c8cb5','#6c9d8d','#b69b75','#7499b5','#a28b8b','#7199a6','#a5a86a','#8ba675','#9987a8']
        rows=[]
        for i,sample_id in enumerate(self.displayed_ids):
            terminal=int(record['terminal_cycles'][sample_id]);values=matrix[:terminal+1,sample_id]
            if self.random_paths.isChecked():curves.append((f'样本ID {sample_id}',np.arange(terminal+1),values,colors[i]))
            for cycle,value in enumerate(values):rows.append(dict(sample_id=sample_id,mission_cycle=cycle,value=value,unit=unit,
                status=('所选模式首次越限' if record['first_mode_crossings'][sample_id,j]==cycle else str(samples.iloc[sample_id]['status']) if cycle==terminal else '有效检查点')))
        self.plot.replace_curves(curves)
        if safe>=1 and self.band.isChecked():self.plot.add_prediction_band(stats.mission_cycle,stats.p05,stats.p95)
        first=True
        for sample_id in self.displayed_ids:
            crossing=int(record['first_mode_crossings'][sample_id,j])
            if crossing>=0 and self.random_paths.isChecked():
                self.plot.plot([crossing],[matrix[crossing,sample_id]],pen=None,symbol='x',symbolPen='#b42318',symbolSize=12,name='所选模式首次越限（循环末）' if first else None);first=False
        self.paths_table.set_frame(pd.DataFrame(rows));self.statistics_table.set_frame(stats)
        self._finish_plot(key,metric,unit,threshold,det_frame,deterministic_crossing,
            f'全{n}样本共同安全范围：'+(f'第0～{safe}循环' if safe>=0 else '无')+f'；随机种子{summary.get("random_seed","—")}；显示样本ID {self.displayed_ids}，各路径到首次终止为止。随机越限按循环末检测。')

    def _finish_plot(self,key,metric,unit,threshold,det_frame,crossing,note):
        self.plot.setTitle(f'{cn(key)}：{cn(metric)}与首次越限')
        self.plot.setLabel('left',unit)
        if self.threshold.isChecked():self.plot.addItem(pg.InfiniteLine(pos=threshold,angle=0,pen=pg.mkPen('#b42318',style=Qt.DashLine),label=f'当前硬阈值 {threshold:.6g}'))
        if crossing is not None and self.deterministic.isChecked():
            self.plot.plot([crossing[0]],[crossing[1]],pen=None,symbol='t',symbolBrush='#b42318',symbolSize=14,name='确定性所选模式首次越限记录')
        # Keep the actual 5/10 sample IDs and both crossing legends visible in
        # the short overview plot. This only lays out labels, never curve data.
        legend=self.plot.plotItem.legend
        if legend is not None:legend.setColumnCount(max(1,(len(legend.items)+4)//5))
        self.deterministic_table.set_frame(det_frame)
        summary=self.result.get('summary',{});cycle=summary.get('first_failure_cycle');remaining=summary.get('remaining_complete_30day_cycles')
        ending=''
        if cycle is not None:
            segment=summary.get('first_failure_segment_id') or ''
            if segment=='DYNAMIC_CHECKPOINT':ending=f'系统质量在第{cycle}次检查检测达到终止等级；只支持检查区间。'
            else:ending=f'本次寿命：完整剩余{remaining}次；第{cycle}次任务{segment}段末检测越限。'
        self.scope.setText(ending+note)
    def payload(self):
        return dict(mode=getattr(self,'_saved_mode',None) or self.mode_selector.currentData(),metric=getattr(self,'_saved_metric',None) or self.metric.currentData(),path_count=self.path_count.currentData(),
            representative_ids=self.displayed_ids,center=self.center.currentData(),band=self.band.isChecked(),threshold=self.threshold.isChecked(),
            deterministic=self.deterministic.isChecked(),random_paths=self.random_paths.isChecked(),detail_tab=self.tabs.currentIndex())
    def restore(self,raw):
        self._saved_mode=raw.get('mode');self._saved_metric=raw.get('metric')
        self.path_count.setCurrentIndex(1 if raw.get('path_count')==10 else 0);self.center.setCurrentIndex(1 if raw.get('center')=='p50' else 0)
        self.band.setChecked(raw.get('band',True));self.threshold.setChecked(raw.get('threshold',True))
        self.deterministic.setChecked(raw.get('deterministic',True));self.random_paths.setChecked(raw.get('random_paths',True))
        self.tabs.setCurrentIndex(int(raw.get('detail_tab',0)))
