"""Check actual saved sample counts, parameter quantiles and terminal records."""
from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/'src')]
assert Path(sys.executable)==Path(r'E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe')
import numpy as np,pandas as pd
from steering_sim.degradation.forecast import physical_curves
from steering_sim.degradation import load_d3_config
from steering_sim.hydraulics_engineering import load_parameters
from steering_sim.desktop.services import HEALTHY,D3_CONFIG
OUT=ROOT/'outputs/desktop/r3';accept=json.loads((OUT/'gui/acceptance.json').read_text('utf-8'))
config=load_d3_config(D3_CONFIG);healthy=load_parameters(HEALTHY);records=[]
for run in accept['tasks']:
    if run['task']!='degradation':continue
    folder=Path(run['output_dir']);meta=json.loads((folder/'metadata.json').read_text('utf-8'))
    with np.load(folder/'gamma_damage_paths.npz',allow_pickle=False) as archive:
        paths=archive['paths'];keys=tuple(archive['keys'].tolist());days=archive['day']
    assert paths.shape==(len(days),run['sample_count'],20)
    assert np.isfinite(paths).all() and np.all(paths>=0) and np.all(np.diff(paths,axis=0)>=0)
    values,units=physical_curves(paths,keys,healthy,config)
    key='pump:front:volumetric_efficiency';matrix=values[key]
    q=np.quantile(matrix,[.05,.5,.95],axis=1);assert np.all(q[0]<=q[1]) and np.all(q[1]<=q[2])
    assert np.all(np.diff(matrix,axis=0)<=1e-14)
    records.append(dict(output_dir=str(folder),samples=paths.shape[1],states=paths.shape[2],time_points=len(days),
        seed=meta['random_seed'],nonnegative_nondecreasing_damage=True,per_path_efficiency_nonincreasing=True,
        efficiency_terminal_p05_p50_p95=q[:,-1].tolist(),physical_mapping_before_statistics=True))
rdir=Path(next(x['output_dir'] for x in accept['tasks'] if x['task']=='rul'))
samples=pd.read_csv(rdir/'monte_carlo_rul_samples.csv')
with np.load(rdir/'monte_carlo_checkpoints.npz',allow_pickle=False) as archive:
    damage=archive['damage'];terminals=archive['terminal_cycles'];crossings=archive['first_mode_crossings'];ids=archive['sample_ids']
assert len(samples)==damage.shape[1]==len(ids)==128
for i,t in enumerate(terminals):
    assert np.isfinite(damage[:t+1,i]).all() and np.isnan(damage[t+1:,i]).all()
    assert np.all(crossings[i][crossings[i]>=0]==t)
    if samples.iloc[i]['status']=='FAILURE_REACHED':assert samples.iloc[i]['remaining_complete_cycles']==t-1
safe=int(samples.last_safe_checkpoint.min());assert np.isfinite(damage[:safe+1]).all()
payload=dict(status='PASS',page03=records,page05=dict(samples=len(samples),common_safe_cycle=safe,checkpoints=damage.shape[0],
    right_censored_count=int(samples.status.eq('RIGHT_CENSORED').sum()),terminal_records_valid=True,
    no_post_terminal_extension=True,resolution='CYCLE_END_CHECKPOINT',source=str(rdir)),
    note='记录完整性与统计口径校验，不代表实物寿命精度验收')
(OUT/'result_data_audit.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(payload,ensure_ascii=False,indent=2))
