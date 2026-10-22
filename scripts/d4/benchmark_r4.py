"""Serial, real-service timing and cProfile; no numerical substitutions."""
from pathlib import Path
import argparse, cProfile, csv, hashlib, importlib.util, json, platform, pstats, sys, time
from dataclasses import is_dataclass, asdict
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
assert Path(sys.executable) == Path(r'E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe')
sys.path.insert(0, str(ROOT))
from steering_sim.desktop.services import DesktopCalculationService
from steering_sim.j0_coupling.runner import J0Runner


class BoundaryRecorder:
    """Acceptance-only copy of every actual RK4 boundary; no interpolation.

    Each run's stage calls are k1,k2,k3,k4,then next k1. The terminal k1
    is evaluated by the existing runner too. Timing covers the original
    stage functions; copying happens after that timer and is separately
    included in service wall time. These are instrumentation, not GUI data.
    """
    def __init__(self):
        self.original_run = J0Runner.run_case
        self.original_stage = J0Runner._stage
        self.state_rows = []; self.command_rows = []; self.stage_count=0
        self.stage_seconds=0.; self.run_seconds=0.

    def __enter__(self):
        owner=self
        def stage(runner,t,state,commands,*args,**kwargs):
            start=time.perf_counter()
            result=owner.original_stage(runner,t,state,commands,*args,**kwargs)
            owner.stage_seconds+=time.perf_counter()-start
            if owner.stage_count%4==0:
                owner.state_rows.append(np.concatenate(([t],state.copy())))
                owner.command_rows.append(tuple(commands))
            owner.stage_count+=1
            return result
        def run(runner,*args,**kwargs):
            owner.state_rows=[];owner.command_rows=[];owner.stage_count=0;owner.stage_seconds=0.
            start=time.perf_counter();result=owner.original_run(runner,*args,**kwargs)
            owner.run_seconds=time.perf_counter()-start
            return result
        J0Runner._stage=stage;J0Runner.run_case=run
        return self

    def __exit__(self,*args):
        J0Runner.run_case=self.original_run;J0Runner._stage=self.original_stage


def serializable(value):
    if is_dataclass(value): return asdict(value)
    if hasattr(value, 'to_dict'): return value.to_dict(orient='records')
    if isinstance(value, np.ndarray): return value.tolist()
    if isinstance(value, np.generic): return value.item()
    raise TypeError(type(value).__name__)


def run(label, angles, profile=False, hold=10.):
    out = ROOT/'outputs/desktop/r4'/label
    out.mkdir(parents=True, exist_ok=True)
    source_paths = list((ROOT/'src/steering_sim/j0_coupling').glob('*.py')) + list((ROOT/'src/steering_sim/hydraulics_engineering').glob('*.py'))
    hashes = {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}
    for angle in angles:
        folder = out/f'angle_{angle:g}'
        folder.mkdir(parents=True, exist_ok=True)
        if (folder/'result.json').exists(): raise RuntimeError(f'Refuse overwrite {folder}')
        scenario = dict(command_type='ramp',initial_outer_angle_deg=0.,target_outer_angle_deg=angle,
                        seconds_per_degree=6.,hold_observation_s=hold,speed_kmh=5.,
                        friction_coefficient=.8,axle_mass_t=[11.5]*6,duration_s=1.25)
        profiler = cProfile.Profile() if profile else None
        started = time.perf_counter()
        last_progress=[-1]
        def progress(fraction,message):
            bucket=int(fraction*10)
            if bucket>last_progress[0]:
                last_progress[0]=bucket
                print(f'{label} {angle:g}deg {fraction:.0%}: {message}',flush=True)
        if profiler: profiler.enable()
        with BoundaryRecorder() as recorder:
            result = DesktopCalculationService(folder/'calculation').run_simulation(
                scenario=scenario, progress=progress, is_cancelled=lambda:False)
        if profiler: profiler.disable()
        elapsed = time.perf_counter()-started
        if profiler: profiler.dump_stats(str(folder/'profile.pstats'))
        np.savez_compressed(folder/'samples.npz', **result['samples'])
        np.savez_compressed(folder/'rk_boundaries.npz',state=np.asarray(recorder.state_rows),
                            commands=np.asarray(recorder.command_rows))
        metadata = {k:v for k,v in result.items() if k!='samples'}
        metadata.update(benchmark_wall_s=elapsed, profiling_enabled=profile, python=sys.executable,
                        platform=platform.platform(), source_hashes=hashes, scenario=scenario,
                        stage_calls=recorder.stage_count, rk_stage_wall_s=recorder.stage_seconds,
                        boundary_recording='all actual RK4 k1 boundaries; includes 22 states and held commands')
        (folder/'result.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2,default=serializable),encoding='utf-8')
        if profiler:
            profiler.dump_stats(str(folder/'profile.pstats'))
            stats = pstats.Stats(profiler)
            rows=[]
            for (filename,line,name),(primitive,calls,self_s,cumulative,callers) in stats.stats.items():
                rows.append(dict(file=filename,line=line,function=name,calls=calls,self_seconds=self_s,
                    cumulative_seconds=cumulative,average_cumulative_us=1e6*cumulative/calls,
                    cumulative_percent=100*cumulative/elapsed,self_percent=100*self_s/elapsed))
            rows.sort(key=lambda row:row['cumulative_seconds'],reverse=True)
            with (folder/'hotspots.csv').open('w',encoding='utf-8-sig',newline='') as f:
                writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
            with (folder/'hotspots.txt').open('w',encoding='utf-8') as f:
                pstats.Stats(profiler,stream=f).sort_stats('cumulative').print_stats(70)
        print(json.dumps(dict(label=label,angle=angle,service_s=result['service_runtime_s'],
            runner_s=result['runtime_s'],horizon_s=result['simulation_horizon_s'],
            settled_s=result['response']['system_settled_s'],complete=result['calculation_success']),ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--label',required=True)
    parser.add_argument('--angles',type=float,nargs='+',default=[2.]);parser.add_argument('--profile',action='store_true')
    parser.add_argument('--hold',type=float,default=10.)
    args=parser.parse_args();run(args.label,args.angles,args.profile,args.hold)
