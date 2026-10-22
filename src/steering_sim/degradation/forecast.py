"""Thirty-day D3 twenty-mode histories and conditional Gamma path statistics."""
import time
import numpy as np
import pandas as pd

from .damage import ComponentDamageState
from .multimode import parameters_from_multimode
from .rul import advance_segment
from .stochastic import gamma_advance
from steering_sim.hydraulics_engineering.model import FRICTION_VELOCITY_EPS_M_S

REFERENCE = {'pressure_pa': 21e6, 'temperature_c': 40.0,
             'cylinder_velocity_m_s': 0.01,
             'interpretation': '固定参考工况；转速为各供油组额定转速；温度为标注条件，未建随机温度过程'}


def physical_curves(damage, keys, healthy, config):
    """Evaluate each path BEFORE quantiles; affine coefficients come from the
    authoritative D3 mapping at D=0 and D=1, not an alternative wear model.
    """
    from .multimode import MultiModeDegradationState
    zero = MultiModeDegradationState.healthy()
    full = type(zero)({k: ComponentDamageState(1.0) for k in zero.modes})
    p0 = parameters_from_multimode(healthy, zero, config)
    p1 = parameters_from_multimode(healthy, full, config)
    lookup = {k: damage[...,i] for i,k in enumerate(keys)}
    values, units = {}, {}
    def put(key, value, unit):
        values[key], units[key] = value, unit
    for supply in ('front','rear'):
        leak = lookup[f'pump:{supply}:leakage_wear']
        mech = lookup[f'pump:{supply}:mechanical_loss']
        a,b = p0.degradation.pump(supply),p1.degradation.pump(supply)
        coefficient = a.internal_leakage_m3_s_per_pa + leak*(b.internal_leakage_m3_s_per_pa-a.internal_leakage_m3_s_per_pa)
        put(f'pump:{supply}:leakage_coefficient',coefficient,'m³/(s·Pa)')
        put(f'pump:{supply}:volumetric_efficiency',np.clip(1-coefficient*REFERENCE['pressure_pa']/healthy.supplies[supply].ideal_flow_m3_s,0,1),'无量纲')
        mechanical=config.mode('pump','mechanical_loss')
        put(f'pump:{supply}:mechanical_efficiency',np.maximum(
            float(mechanical['minimum_mechanical_efficiency']),
            1-float(mechanical['efficiency_loss_at_maximum_damage'])*mech),'无量纲')
    for channel in healthy.channels:
        name=channel.name
        for kind in ('valve','cylinder'):
            getter0=getattr(p0.degradation,kind); getter1=getattr(p1.degradation,kind)
            a,b=getter0(name),getter1(name)
            leak=lookup[f'{kind}:{name}:leakage_wear']
            coefficient=a.internal_leakage_m3_s_per_pa+leak*(b.internal_leakage_m3_s_per_pa-a.internal_leakage_m3_s_per_pa)
            put(f'{kind}:{name}:leakage_coefficient',coefficient,'m³/(s·Pa)')
            put(f'{kind}:{name}:reference_leakage_lpm',coefficient*REFERENCE['pressure_pa']*60000,'L/min')
            if kind=='valve':
                scale=a.lag_scale+lookup[f'valve:{name}:response_lag']*(b.lag_scale-a.lag_scale)
                put(f'valve:{name}:lag_scale',scale,'倍')
                put(f'valve:{name}:response_time_s',scale*channel.valve.lag_time_s,'s')
            else:
                scale=a.friction_scale+lookup[f'cylinder:{name}:friction_growth']*(b.friction_scale-a.friction_scale)
                put(f'cylinder:{name}:friction_scale',scale,'倍')
                v=REFERENCE['cylinder_velocity_m_s']
                force=channel.cylinder.coulomb_friction_n*np.tanh(v/FRICTION_VELOCITY_EPS_M_S)+channel.cylinder.viscous_damping_n_s_per_m*v
                put(f'cylinder:{name}:reference_friction_n',scale*force,'N')
    return values,units


def mission_forecast(profile, initial, healthy, config, *, sample_count=0,
                     random_seed=20261013, progress=lambda *_:None,
                     is_cancelled=lambda:False):
    started=time.perf_counter()
    keys=tuple(initial.modes)
    n=int(sample_count)
    if n<0 or n>10000:
        raise ValueError('随机路径数须在0～10000之间')
    deterministic=[np.array([initial.modes[k].damage for k in keys])]
    paths=np.empty((len(profile.segments)+1,n,len(keys))) if n else None
    if n:
        paths[0]=deterministic[0]
    rng=np.random.default_rng(random_seed)
    state=initial
    times=[0.0]
    records=[]
    for i,segment in enumerate(profile.segments):
        if is_cancelled():
            return {}
        state,increments=advance_segment(state,segment,config)
        deterministic.append(np.array([state.modes[k].damage for k in keys]))
        times.append(segment.elapsed_day)
        record={'segment_id':segment.segment_id,'elapsed_day':segment.elapsed_day}
        for j,key in enumerate(keys):
            record[key]=state.modes[key].damage
            record[f'increment:{key}']=increments[key]
            record[f'exposure:{key}']=segment.exposures[key]
            if n:
                kind,_,mode=key.split(':')
                paths[i+1,:,j]=gamma_advance(paths[i,:,j],segment.exposures[key],config.mode(kind,mode),rng)
        records.append(record)
        if i%20==0:
            progress(0.25+0.45*i/max(1,len(profile.segments)),f'已推进 {i+1}/{len(profile.segments)} 段，{n}条随机路径')
    deterministic=np.asarray(deterministic)
    curves={k:deterministic[:,j] for j,k in enumerate(keys)}
    physical,units=physical_curves(deterministic,keys,healthy,config)
    curves.update(physical)
    units.update({k:'无量纲' for k in keys})
    stats=[]
    representatives={}
    for j,(key,central) in enumerate(curves.items()):
        if is_cancelled():
            return {}
        if n:
            if key in keys:
                matrix=paths[:,:,keys.index(key)]
            else:
                # Map all samples with the same authoritative parameter map;
                # avoid retaining 38 additional full path tensors in memory.
                if j==len(keys):
                    stochastic_physical,_=physical_curves(paths,keys,healthy,config)
                matrix=stochastic_physical.pop(key)
            q=np.quantile(matrix,[.025,.05,.5,.95,.975],axis=1)
            mean,std=matrix.mean(axis=1),matrix.std(axis=1,ddof=1) if n>1 else np.zeros(len(times))
            representatives[key]=matrix[:,:min(10,n)].copy()
        else:
            q=np.repeat(central[None,:],5,axis=0); mean=central; std=np.zeros(len(times))
        for i,day in enumerate(times):
            stats.append({'day':day,'metric':key,'deterministic':central[i],
                          'mean':mean[i],'p025':q[0,i],'p05':q[1,i],
                          'p50':q[2,i],'p95':q[3,i],'p975':q[4,i],
                          'std':std[i],'unit':units[key]})
    frame=pd.DataFrame({'day':times,**curves})
    return {'final_state':state,'curve_frame':frame,'statistics':pd.DataFrame(stats),
            'segment_frame':pd.DataFrame(records),'paths':paths,'mode_keys':keys,
            'representatives':representatives,'units':units,
            'representative_sample_ids':tuple(range(min(10,n))),
            'sample_count':n,'random_seed':random_seed,
            'runtime_s':time.perf_counter()-started,
            'reference_conditions':dict(REFERENCE,
                pump_speed_rad_s={k:v.nominal_speed_rad_s for k,v in healthy.supplies.items()},
                pump_theoretical_flow_m3_s={k:v.ideal_flow_m3_s for k,v in healthy.supplies.items()}),
            'load_approximation':'D3 corrected profile at initial state, with D1 leakage feedback; shared frozen conditional exposures across paths; D3 RUL aggregates the same exposures per cycle',
            'random_assumptions':'条件独立Gamma残余过程；污染与温度为输入确定值，未模拟随机环境；上限截断会改变边界处期望；非线性总体均值无需等于确定性轨迹'}
