"""Display-only interpolation of recorded results. No solver is imported here."""
from pathlib import Path
import time
import math
import numpy as np
import pandas as pd
from PySide6.QtCore import Qt,Signal,QTimer,QPointF,QRectF
from PySide6.QtGui import QPainter,QPen,QColor,QFont
from PySide6.QtWidgets import (QWidget,QHBoxLayout,QVBoxLayout,QGridLayout,QLabel,
    QPushButton,QSlider,QComboBox,QGroupBox,QScrollArea,QDialog,QCheckBox,QSizePolicy)
import pyqtgraph as pg
from .widgets import EngineeringPlot

CHANNELS=('channel_front','channel_rear_1','channel_rear_2','channel_rear_3')
CHANNEL_NAMES=('一二桥等效作动组','四桥等效作动组','五桥等效作动组','六桥等效作动组')
WHEELS=tuple(f'axle{a}_{side}' for a in range(1,7) for side in ('left','right'))
ROOT=Path(__file__).resolve().parents[3]

def display_number(value,decimals=2):
    return '—' if value is None or not math.isfinite(float(value)) else f'{float(value):.{decimals}f}'

class ReplayControl(QWidget):
    time_changed=Signal(float)
    def __init__(self,parent=None):
        super().__init__(parent); self.frame=pd.DataFrame();self.current_time=0.;self._wall=0.
        layout=QHBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        for text,slot in [('起点',lambda:self.seek(self.begin)),('从头播放',self.play),('暂停',self.pause),('终点',lambda:self.seek(self.end))]:
            button=QPushButton(text);button.clicked.connect(slot);layout.addWidget(button)
        self.slider=QSlider(Qt.Horizontal);self.slider.setRange(0,10000)
        self.slider.valueChanged.connect(lambda v:self.seek(self.begin+(self.end-self.begin)*v/10000))
        layout.addWidget(self.slider,1);self.clock=QLabel('尚未计算');layout.addWidget(self.clock)
        self.speed=QComboBox()
        for value in (1,2,5):self.speed.addItem(f'{value}倍回放',value)
        layout.addWidget(self.speed); self.timer=QTimer(self);self.timer.setInterval(33);self.timer.timeout.connect(self._tick)
    @property
    def begin(self):return float(self.frame.time_s.iloc[0]) if len(self.frame) else 0.
    @property
    def end(self):return float(self.frame.time_s.iloc[-1]) if len(self.frame) else 0.
    def set_samples(self,samples):
        self.pause();self.frame=pd.DataFrame(samples).copy(deep=True)
        if len(self.frame):
            t=self.frame.time_s.to_numpy()
            if not np.isfinite(t).all() or np.any(np.diff(t)<=0):raise ValueError('回放时间序列必须有限且严格递增')
        self.slider.setEnabled(bool(len(self.frame)));self.seek(self.end)
    def sample(self):
        if self.frame.empty:return {}
        t=self.frame.time_s.to_numpy()
        return {k:float(np.interp(self.current_time,t,self.frame[k].to_numpy(dtype=float)))
                for k in self.frame if pd.api.types.is_numeric_dtype(self.frame[k])}
    def seek(self,t):
        self.current_time=float(np.clip(t,self.begin,self.end))
        self.slider.blockSignals(True);self.slider.setValue(round(10000*(self.current_time-self.begin)/(self.end-self.begin)) if self.end>self.begin else 0);self.slider.blockSignals(False)
        self.clock.setText(f'模拟时间 {self.current_time:.2f} / {self.end:.2f} s' if len(self.frame) else '尚未计算')
        self.time_changed.emit(self.current_time)
    def play(self):
        if self.frame.empty:return
        self.seek(self.begin);self._wall=time.perf_counter();self.timer.start()
    def pause(self):self.timer.stop()
    def _tick(self):
        now=time.perf_counter();self.seek(self.current_time+(now-self._wall)*self.speed.currentData());self._wall=now
        if self.current_time>=self.end:self.pause()

class VehicleView(QWidget):
    wheel_selected=Signal(int)
    def __init__(self,parent=None):
        super().__init__(parent);self.setMinimumHeight(300);self.values={};self.wheel_angles={};self.screen_centers={}
        from steering_sim.mechanics import reference_geometry_from_file
        ref=reference_geometry_from_file(ROOT/'mechanical_model_input_spec_v1.0.yaml')
        self.model_centers={f'axle{a}_{side}':tuple(ref.bodies[f'WHEEL_{a}_{suffix}'].pivot)
            for a in range(1,7) for side,suffix in [('left','POS_Y'),('right','NEG_Y')]}
    def set_sample(self,values):
        self.values=values;self.wheel_angles={key:values.get(f'wheel_{key}_actual_deg',float('nan')) for key in WHEELS};self.update()
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.Antialiasing);p.fillRect(self.rect(),QColor('white'))
        p.setFont(QFont('Microsoft YaHei UI',10));p.setPen(QColor('#30475d'))
        p.drawText(15,23,'转向示意：车头向右 →  （轮心采用正式几何，轮胎外形不按比例）')
        if not self.values:p.drawText(15,48,'尚未计算')
        xs=[v[0] for v in self.model_centers.values()];ys=[v[1] for v in self.model_centers.values()]
        scale=min((self.width()-150)/(max(xs)-min(xs)),(self.height()-160)/(max(ys)-min(ys)))
        mx=(max(xs)+min(xs))/2;my=(max(ys)+min(ys))/2
        self.screen_centers={k:QPointF(self.width()/2+(x-mx)*scale,self.height()/2-(y-my)*scale) for k,(x,y) in self.model_centers.items()}
        left=min(v.x() for v in self.screen_centers.values());right=max(v.x() for v in self.screen_centers.values())
        top=min(v.y() for v in self.screen_centers.values());bottom=max(v.y() for v in self.screen_centers.values())
        p.setPen(QPen(QColor('#a6b8c8'),1));p.setBrush(QColor('#f0f5fa'));p.drawRoundedRect(QRectF(left-35,top+22,right-left+70,bottom-top-44),12,12)
        p.setPen(QPen(QColor('#78909c'),1,Qt.DashLine));p.drawLine(QPointF(left-45,self.height()/2),QPointF(right+45,self.height()/2))
        for axle in range(1,7):
            a,b=self.screen_centers[f'axle{axle}_left'],self.screen_centers[f'axle{axle}_right']
            p.setPen(QPen(QColor('#9eafbd'),2));p.drawLine(a,b)
            p.setPen(QColor('#30475d'));p.drawText(QRectF(a.x()-35,self.height()/2-12,70,25),Qt.AlignCenter,f'{axle}桥')
        for i,key in enumerate(WHEELS):
            c=self.screen_centers[key];angle=self.wheel_angles.get(key,float('nan'));fixed=key.startswith('axle3_');bad=fixed and math.isfinite(angle) and abs(angle)>1e-8
            p.save();p.translate(c);p.rotate(-angle if math.isfinite(angle) else 0)
            p.setPen(QPen(QColor('#b42318' if bad else '#245f91'),2));p.setBrush(QColor('#f8fafc' if not self.values else '#87b9de'));p.drawRoundedRect(QRectF(-22,-9,44,18),3,3);p.restore()
            label=f"{i//2+1}桥{'左' if i%2==0 else '右'}轮 {display_number(angle)}°"
            if fixed:label+=('\n锁零异常' if bad else '\n固定零位' if math.isfinite(angle) else '')
            p.setPen(QColor('#b42318' if bad else '#30475d'))
            offset=(-82 if fixed else -49) if i%2==0 else (40 if fixed else 18)
            p.drawText(QRectF(c.x()-65,c.y()+offset,130,40),Qt.AlignCenter|Qt.TextWordWrap,label)
    def mousePressEvent(self,event):
        if self.screen_centers:
            i=min(range(12),key=lambda n:(self.screen_centers[WHEELS[n]]-event.position()).manhattanLength())
            if (self.screen_centers[WHEELS[i]]-event.position()).manhattanLength()<50:self.wheel_selected.emit(i)

class CylinderGauge(QWidget):
    def __init__(self,cylinder,parent=None):
        super().__init__(parent);self.minimum=cylinder.stroke_min_m;self.maximum=cylinder.stroke_max_m
        self.position=float('nan');self.setMinimumSize(115,80);self.setMaximumWidth(155)
        self.setToolTip(f'有效位移范围 {self.minimum*1000:.3f}～{self.maximum*1000:.3f} mm；安装偏置 {cylinder.stroke_offset_m*1000:.3f} mm')
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.Antialiasing);p.fillRect(self.rect(),QColor('white'))
        bad=math.isfinite(self.position) and not self.minimum<=self.position<=self.maximum
        p.setPen(QPen(QColor('#b42318' if bad else '#607d8b'),2));p.setBrush(QColor('#eef4f9'))
        r=QRectF(18,self.height()/2-18,self.width()-36,36);p.drawRect(r)
        f=np.clip((self.position-self.minimum)/(self.maximum-self.minimum),0,1) if math.isfinite(self.position) else .5
        x=r.left()+f*r.width();p.setPen(QPen(QColor('#245f91'),5));p.drawLine(QPointF(3,r.center().y()),QPointF(self.width()-3,r.center().y()))
        p.fillRect(QRectF(x-4,r.top()+2,8,r.height()-4),QColor('#245f91'));p.setPen(QColor('#b42318' if bad else '#30475d'))
        p.drawText(QRectF(0,self.height()-24,self.width(),24),Qt.AlignCenter,'实际越界' if bad else '对称双出杆示意')

class ChannelOverview(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent);self.frame=pd.DataFrame();self.dialogs=[];self.plots=[];self.gauges=[];self.labels=[];self.cursors=[]
        from steering_sim.hydraulics_engineering import load_parameters
        parameters=load_parameters(ROOT/'configs/j1r2/engineering_hydraulics.json')
        outer=QVBoxLayout(self);outer.setContentsMargins(0,0,0,0)
        self.link=QCheckBox('四通道共用时间轴缩放');self.link.setChecked(True);outer.addWidget(self.link)
        scroll=QScrollArea();scroll.setWidgetResizable(True);self.content=QWidget();grid=QGridLayout(self.content)
        for i,(key,name) in enumerate(zip(CHANNELS,CHANNEL_NAMES)):
            card=QGroupBox(name);card.setMinimumHeight(250);layout=QHBoxLayout(card)
            left=QVBoxLayout();gauge=CylinderGauge(parameters.channel(key).cylinder);label=QLabel('尚未计算');label.setWordWrap(True)
            left.addWidget(gauge);left.addWidget(label);button=QPushButton('放大曲线');button.clicked.connect(lambda _=False,n=i:self.open_detail(n));left.addWidget(button)
            layout.addLayout(left);plot=EngineeringPlot(name,'行程 (mm)','时间 (s)');plot.setMinimumSize(240,160);plot.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Ignored);layout.addWidget(plot,1)
            grid.addWidget(card,i//2,i%2);self.plots.append(plot);self.gauges.append(gauge);self.labels.append(label)
            plot.hover_formatter=lambda t,y,n=i:self.hover_text(n,t)
        scroll.setWidget(self.content);outer.addWidget(scroll,1)
        self.link.toggled.connect(self._link_axes);self._link_axes(True)
    def _link_axes(self,checked):
        for p in self.plots[1:]:p.setXLink(self.plots[0] if checked else None)
    def hover_text(self,index,t):
        if self.frame.empty:return '尚未计算'
        i=int(np.abs(self.frame.time_s.to_numpy()-t).argmin());r=self.frame.iloc[i];key=CHANNELS[index]
        x=r[f'{key}_x_m']*1000;target=r[f'{key}_x_ref_eff_m']*1000
        return f'{CHANNEL_NAMES[index]}\n时间 {r.time_s:.3f} s\n目标 {target:.3f} mm\n实际 {x:.3f} mm\n偏差 {x-target:.3f} mm'
    def set_samples(self,frame):
        self.frame=pd.DataFrame(frame).copy();self.cursors=[]
        for key,plot in zip(CHANNELS,self.plots):
            plot.replace_curves([] if self.frame.empty else [('目标',self.frame.time_s,self.frame[f'{key}_x_ref_eff_m']*1000,'#78909c'),('实际',self.frame.time_s,self.frame[f'{key}_x_m']*1000,'#1976d2')])
            cursor=pg.InfiniteLine(angle=90,pen=pg.mkPen('#d97706',style=Qt.DashLine));plot.addItem(cursor,ignoreBounds=True);self.cursors.append(cursor)
    def set_sample(self,values):
        self.current_time=values.get('time_s',0)
        for i,key in enumerate(CHANNELS):
            value=lambda suffix:values.get(f'{key}_{suffix}',float('nan'))
            x,target=value('x_m')*1000,value('x_ref_eff_m')*1000
            self.gauges[i].position=value('x_m');self.gauges[i].update()
            self.labels[i].setText('尚未计算' if not values else f'目标 {display_number(target)} mm\n实际 {display_number(x)} mm\n偏差 {display_number(x-target,3)} mm\n速度 {display_number(value("v_m_s")*1000,3)} mm/s\nA/B {display_number(value("pA_mpa_g"))} / {display_number(value("pB_mpa_g"))} MPa')
            if i<len(self.cursors):self.cursors[i].setPos(values.get('time_s',0))
        for dialog,plot,cursor in tuple(self.dialogs):
            if dialog.isVisible():cursor.setPos(values.get('time_s',0))
    def open_detail(self,index):
        if self.frame.empty:return
        dialog=QDialog(self);dialog.setAttribute(Qt.WA_DeleteOnClose,True);dialog.setWindowTitle(CHANNEL_NAMES[index]+'曲线详情');dialog.resize(1050,650);layout=QVBoxLayout(dialog)
        plot=EngineeringPlot(CHANNEL_NAMES[index],'行程 (mm)','时间 (s)');key=CHANNELS[index]
        plot.replace_curves([('目标',self.frame.time_s,self.frame[f'{key}_x_ref_eff_m']*1000,'#78909c'),('实际',self.frame.time_s,self.frame[f'{key}_x_m']*1000,'#1976d2')]);plot.hover_formatter=lambda t,y:self.hover_text(index,t)
        cursor=pg.InfiniteLine(pos=getattr(self,'current_time',0),angle=90,pen='#d97706');plot.addItem(cursor,ignoreBounds=True);layout.addWidget(plot);self.dialogs.append((dialog,plot,cursor))
        dialog.destroyed.connect(lambda:self._forget_dialog(dialog));dialog.show()
    def _forget_dialog(self,dialog):self.dialogs=[r for r in self.dialogs if r[0] is not dialog]
    def clear(self):
        for dialog,_,_ in self.dialogs:dialog.close();dialog.deleteLater()
        self.dialogs=[];self.set_samples({});self.set_sample({})
