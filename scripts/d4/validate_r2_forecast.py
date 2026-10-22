"""Reproducible twenty-state/Gamma benchmark (not full-path dynamics)."""
from pathlib import Path
import sys,json,time,platform
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from steering_sim.desktop.services import DesktopCalculationService,EXAMPLE_SPECTRUM
from steering_sim.degradation.forecast import mission_forecast
from steering_sim.degradation import (load_d3_config,load_degradation_config,
    MultiModeDegradationState,D1Predictor,load_task_spectrum)
from steering_sim.desktop.services import _runner,HEALTHY,D1_CONFIG,D3_CONFIG
from steering_sim.hydraulics_engineering import load_parameters
from scripts.d3.run_phase_d3 import corrected_profile_factory
from steering_sim.degradation.stochastic import monte_carlo_rul

def main():
    out=ROOT/'outputs/desktop/r2/cd';out.mkdir(parents=True,exist_ok=True)
    start=time.perf_counter();cfg=load_d3_config(D3_CONFIG);healthy=load_parameters(HEALTHY)
    state=MultiModeDegradationState.healthy(); predictor=D1Predictor(_runner(healthy),load_degradation_config(D1_CONFIG))
    spectrum=load_task_spectrum(EXAMPLE_SPECTRUM)
    profile=corrected_profile_factory(predictor,healthy,predictor.config,cfg,spectrum)(state,0.)
    preparation=time.perf_counter()-start
    rows=[];quantiles=[]
    for n in (0,128,500,1000):
        started=time.perf_counter()
        result=mission_forecast(profile,state,healthy,cfg,sample_count=n,random_seed=20261013)
        elapsed=time.perf_counter()-started
        target=out/f'paths_{n}';target.mkdir(exist_ok=True)
        for key in ('statistics','curve_frame','segment_frame'):
            result[key].to_csv(target/f'{key}.csv',index=False,encoding='utf-8-sig')
        if n:
            np.savez_compressed(target/'all_twenty_state_paths.npz',paths=result['paths'],keys=np.array(result['mode_keys']),day=result['curve_frame'].day)
            assert result['paths'].shape[1]==n and np.all(np.diff(result['paths'],axis=0)>=0)
        final=result['statistics'].loc[result['statistics'].day==30].copy(); final['sample_count']=n
        quantiles.append(final)
        rows.append(dict(samples=n,forecast_and_statistics_wall_s=elapsed,segments=len(profile.segments),mode_count=len(result['mode_keys'])))
        print(json.dumps(rows[-1]),flush=True)
    pd.concat(quantiles).to_csv(out/'sample_count_convergence.csv',index=False,encoding='utf-8-sig')
    comparable=monte_carlo_rul(state,profile,cfg,sample_count=1000,random_seed=20261013,
                              maximum_cycles=1,stored_paths=1000)
    page05=pd.DataFrame(comparable.path_rows);cross=[]
    for j,key in enumerate(result['mode_keys']):
        a=result['paths'][-1,:,j];b=page05[key.replace(':','_')].to_numpy()
        se=np.sqrt(a.var(ddof=1)/1000+b.var(ddof=1)/1000)
        cross.append(dict(mode=key,page03_mean=a.mean(),page05_mean=b.mean(),standard_error=se,
                          difference_in_standard_errors=abs(a.mean()-b.mean())/se if se else 0))
    pd.DataFrame(cross).to_csv(out/'actual_mission_03_05_first_cycle_statistics.csv',index=False,encoding='utf-8-sig')
    payload=dict(python=sys.executable,hardware=platform.uname()._asdict(),processor=platform.processor(),preparation_s=preparation,runs=rows,
                 provenance=DesktopCalculationService(out).provenance(str(EXAMPLE_SPECTRUM)),model_version=cfg.model_version,random_seed=20261013,
                 interpretation='固定初态修正载荷暴露，逐段独立Gamma状态推进；1000条路径并非1000次22状态积分')
    (out/'benchmark.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__':main()
