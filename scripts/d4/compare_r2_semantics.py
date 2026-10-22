"""Quantify explicit 6s/deg versus untouched legacy mission semantics."""
from pathlib import Path
import sys,json
import pandas as pd
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from steering_sim.desktop.services import _runner,D1_CONFIG,D3_CONFIG,HEALTHY,EXAMPLE_SPECTRUM
from steering_sim.degradation import (D1Predictor,load_degradation_config,load_d3_config,
    load_task_spectrum,MultiModeDegradationState)
from steering_sim.degradation.rul import advance_segment
from steering_sim.hydraulics_engineering import load_parameters
from scripts.d3.run_phase_d3 import corrected_profile_factory

def main():
    out=ROOT/'outputs/desktop/r2/b';out.mkdir(parents=True,exist_ok=True)
    cfg=load_degradation_config(D1_CONFIG);d3=load_d3_config(D3_CONFIG);healthy=load_parameters(HEALTHY)
    predictor=D1Predictor(_runner(healthy),cfg);results=[];profiles=[]
    for name,path in [('legacy',ROOT/'data/degradation/task_spectrum_30day_example.csv'),('explicit_6s',EXAMPLE_SPECTRUM)]:
        spectrum=load_task_spectrum(path);prediction=predictor.predict(spectrum)
        pd.DataFrame(prediction.segment_records).to_csv(out/f'{name}_segment_loads.csv',index=False,encoding='utf-8-sig')
        state=MultiModeDegradationState.healthy()
        profile=corrected_profile_factory(predictor,healthy,cfg,d3,spectrum)(state,0)
        for segment in profile.segments:state,_=advance_segment(state,segment,d3)
        results.append({key:v.damage for key,v in state.modes.items()})
    frame=pd.DataFrame({'legacy':results[0],'explicit_6s':results[1]})
    frame['difference']=frame.explicit_6s-frame.legacy
    frame['relative_change_percent']=100*frame.difference/frame.legacy.where(frame.legacy!=0)
    frame.to_csv(out/'twenty_state_semantics_comparison.csv',encoding='utf-8-sig',index_label='component_mode')
    print(frame.to_string())
if __name__=='__main__':main()
