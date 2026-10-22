"""Adapter for the single D3 twenty-mode mission history used by page 03."""
import json
import time
from pathlib import Path
import numpy as np
import pandas as pd

from steering_sim.degradation.forecast import mission_forecast
from steering_sim.degradation import (D1Predictor, load_degradation_config,
    load_d3_config, MultiModeDegradationState, parameters_from_multimode,
    component_mode_rows, load_task_spectrum)
from steering_sim.hydraulics_engineering import load_parameters


def run_degradation(service,path,initial_source,progress,cancel,stochastic,samples,seed):
    from .services import _runner,HEALTHY,D1_CONFIG,D3_CONFIG
    from scripts.d3.run_phase_d3 import corrected_profile_factory
    started=time.perf_counter()
    out=service.output_dir/'degradation'/f"mission_{time.strftime('%Y%m%d_%H%M%S')}_{time.time_ns()}"
    out.mkdir(parents=True,exist_ok=True)
    original=Path(path).resolve()
    snapshot=out/('mission_input'+original.suffix.lower())
    snapshot.write_bytes(original.read_bytes())
    provenance=service.provenance(str(snapshot))
    spectrum=load_task_spectrum(snapshot)
    config=load_d3_config(D3_CONFIG); d1=load_degradation_config(D1_CONFIG)
    healthy=load_parameters(HEALTHY)
    predictor=D1Predictor(_runner(healthy),d1)
    state=MultiModeDegradationState.healthy()
    if initial_source=='d1_day30':
        state=MultiModeDegradationState.from_d1(predictor.predict(spectrum).final_state)
    progress(.1,'正在构建与剩余寿命共用的二十模式载荷暴露')
    profile=corrected_profile_factory(predictor,healthy,d1,config,spectrum)(state,0.0)
    result=mission_forecast(profile,state,healthy,config,sample_count=int(samples) if stochastic else 0,
                            random_seed=int(seed),progress=progress,is_cancelled=cancel)
    if not result or cancel():
        return {}
    parameters=parameters_from_multimode(healthy,result['final_state'],config)
    result.update(kind='degradation', component_frame=pd.DataFrame(component_mode_rows(result['final_state'],config,parameters)),
        rainflow_frame=pd.DataFrame([{'channel':k,**v,'purpose':'cylinder_friction_growth'} for k,v in profile.rainflow_equivalents.items()]),
        risks=[row for row in profile.source_records if row.get('load_flags')],
        initial_state_source=initial_source, initial_state=state,
        assumption='工程假设预测，退化系数与Gamma尺度待甲方试验标定',
        models=config.raw['modes'])
    checkpoints=[]
    for day in (0,10,20,30):
        available=result['statistics'].loc[result['statistics'].day>=day-1e-9]
        if not available.empty:
            frame=available.loc[available.day==available.day.min()].copy()
            frame['requested_checkpoint_day']=day
            checkpoints.append(frame)
    result['checkpoint_frame']=pd.concat(checkpoints,ignore_index=True)
    from .localization import chinese_frame
    raw=out/'raw'; raw.mkdir()
    for key,name in [('curve_frame','twenty_mode_and_parameters.csv'),('statistics','prediction_intervals.csv'),
                     ('segment_frame','segment_damage.csv'),('component_frame','final_modes.csv'),
                     ('checkpoint_frame','checkpoints.csv'),('rainflow_frame','rainflow.csv')]:
        result[key].to_csv(raw/name,index=False,encoding='utf-8-sig')
        chinese_frame(result[key]).to_csv(out/name,index=False,encoding='utf-8-sig')
    if result['paths'] is not None:
        np.savez_compressed(out/'gamma_damage_paths.npz',paths=result['paths'],
                            keys=np.array(result['mode_keys']),day=result['curve_frame'].day.to_numpy())
    (out/'final_twenty_state.json').write_text(json.dumps({
        'schema_version':'D3.0','interpretation':'本次未来30天确定性二十模式末态，可在05页自定义JSON初态中直接选择；不是随机均值状态',
        'modes':{key:{'damage':value.damage,'exposure':value.exposure}
                 for key,value in result['final_state'].modes.items()}},ensure_ascii=False,indent=2),encoding='utf-8')
    metadata={k:result[k] for k in ('sample_count','random_seed','reference_conditions','random_assumptions','load_approximation','initial_state_source')}
    metadata.update(provenance)
    metadata.update(original_input_path=str(original),input_snapshot=snapshot.name)
    metadata['runtime_s']=time.perf_counter()-started
    metadata['component_table_semantics']='同次预测的确定性参考末态；随机均值和分位数见预测分布，不强制一致'
    (out/'metadata.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    result['output_dir']=str(out); result['runtime_s']=metadata['runtime_s']
    result['provenance']=metadata
    progress(.98,'二十模式、物理参数与预测区间已整理')
    return result
