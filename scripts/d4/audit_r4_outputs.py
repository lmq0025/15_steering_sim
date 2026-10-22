"""Summarize measured R4 timing/protection without inventing missing runs."""
from pathlib import Path
import csv, hashlib, json, sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts.d4.run_r4_full_tests import protected_hashes
OUT=ROOT/'outputs/desktop/r4'
assert Path(sys.executable)==Path(r'E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe')
def read(p):return json.loads(Path(p).read_text('utf-8-sig'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def main():
    protected={name:dict(before=value,after=sha(ROOT/name),unchanged=sha(ROOT/name)==value)
               for name,value in protected_hashes().items()}
    baseline=read(OUT/'baseline.json')
    changed=[name for name,value in baseline['source_hashes'].items() if sha(ROOT/name)!=value]
    audit=dict(status='PASS' if all(item['unchanged'] for item in protected.values()) else 'FAIL',
        protected=protected,changed_since_local_r3_snapshot=changed,
        note='Core implementations intentionally changed; physical configuration, mechanical source, angle reference, response criteria and degradation laws are protected separately.')
    (OUT/'baseline_final_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    rows=[]
    for angle in (2,5,10):
        a=read(OUT/f'baseline/angle_{angle}/result.json');b=read(OUT/f'optimized/angle_{angle}/result.json')
        p=read(OUT/f'precision/angle_{angle}/precision_comparison.json')
        timing=b['summary']['performance_timing']
        rows.append(dict(angle_deg=angle,physical_horizon_s=b['simulation_horizon_s'],
            command_completion_s=b['response']['command_completion_s'],settled_s=b['response']['system_settled_s'],
            before_service_s=a['service_runtime_s'],after_service_s=b['service_runtime_s'],
            service_speedup=a['service_runtime_s']/b['service_runtime_s'],
            before_runner_s=a['runtime_s'],after_runner_s=b['runtime_s'],
            before_rhs_s=a['rk_stage_wall_s'],after_rhs_s=b['rk_stage_wall_s'],
            after_rk4_s=timing['rk4_wall_s'],after_pid_s=timing['control_wall_s'],
            after_recorder_s=timing['recording_wall_s'],after_loop_s=timing['integration_loop_wall_s'],
            precision_status=p['status'],exact_matching_columns=p['exact_matching_columns'],
            compared_columns=p['compared_columns'],compared_elements=p['compared_elements'],
            raw_step_s=b['summary']['actual_hydraulic_step_s']))
    gui_path=OUT/'simulation_gui/acceptance.json'
    gui=read(gui_path) if gui_path.exists() else None
    long_path=OUT/'historical_30_verified/comparison.json'
    long=read(long_path) if long_path.exists() else None
    summary=dict(hardware=read(OUT/'hardware.json'),same_session_benchmarks=rows,
        gui_simulation=gui,long_case_comparison=({k:long[k] for k in ('status','coverage_level','timings','limitations')} if long else None),
        ten_degree_gui_under_60s=(gui['original_service_wall_s']<=60 if gui and gui['mode']=='LIVE_QT_QTHREAD_FULL_22_STATE' else None),
        ten_degree_benchmark_under_60s=rows[-1]['after_service_s']<=60,
        profiling_scope='before/after cProfile: first2s of12s angle ramp, diagnostic only; not a settled2degree acceptance',
        timing_scope='Serial measured wall times; benchmark includes all-step acceptance copy. GUI timing is separate, no assumption of identical historical system load.')
    (OUT/'performance_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    with (OUT/'performance_comparison.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    print(json.dumps(dict(protected=audit['status'],protected_files=len(protected),benchmarks=rows,
                         gui_status=gui.get('status') if gui else None,long_status=long.get('status') if long else None),ensure_ascii=False))
    if audit['status']!='PASS' or any(row['precision_status']!='PASS' for row in rows):raise SystemExit(1)

if __name__=='__main__':main()
