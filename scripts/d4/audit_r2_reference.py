"""Audit existing raw 0.5ms/2ms histories, without repeating long integration."""
import sys,json,cProfile,pstats
from pathlib import Path
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from steering_sim.desktop.response_analysis import ResponseCriteria,analyze_response
from steering_sim.desktop.services import _runner
from steering_sim.j0_coupling.config import J0CaseConfig
from steering_sim.desktop.response_analysis import linear_ramp_profile

def main():
    folder=ROOT/'outputs/desktop/r2/a/reference_step_matrix'
    rows=json.loads((folder/'ramp_acceptance_summary.json').read_text('utf-8'))
    old=json.loads((ROOT/'outputs/desktop/r2/a/ramp_acceptance_summary.json').read_text('utf-8'))
    old={r['case']:r for r in old}
    audits=[]; comparisons=[];metrics=[]
    for row in rows:
        data=pd.read_csv(ROOT/row['timeseries_csv']);t=data.time_s.to_numpy()
        angle=row['initial_outer_angle_deg']+np.minimum(t/row['command_completion_s'],1)*(row['final_outer_angle_deg']-row['initial_outer_angle_deg'])
        raw={c:data[c].to_numpy() for c in data}
        outer=np.where(angle>=0,data.wheel_axle1_right_command_deg,data.wheel_axle1_left_command_deg)
        for speed in (.001,.0001,.00001):
            response=analyze_response(raw,row['command_completion_s'],ResponseCriteria(piston_speed_threshold_m_s=speed))
            audits.append(dict(case=row['case'],piston_threshold_m_s=speed,command_s=row['command_completion_s'],horizon_s=t[-1],
                exact_reference_max_error_deg=float(np.max(abs(data.outer_angle_reference_deg-angle))),
                outer_wheel_target_max_error_deg=float(np.max(abs(outer-angle))),
                system_settled_s=response['system_settled_s'],cylinder_settled_s=response['all_cylinders_settled_s'],
                final_max_piston_speed_m_s=max(abs(data[c].iloc[-1]) for c in data if c.endswith('_v_m_s'))))
        if row['case'] in old:
            other=pd.read_csv(ROOT/old[row['case']]['timeseries_csv'])
            for step,frame,entry in [(.0005,data,row),(.002,other,old[row['case']])]:
                response=analyze_response({c:frame[c].to_numpy() for c in frame},entry['command_completion_s'],ResponseCriteria())
                metrics.append(dict(case=row['case'],hydraulic_step_s=step,
                    maximum_wheel_tracking_error_deg=max(float(np.max(abs(frame[c]-frame[c.replace('_actual_deg','_command_deg')]))) for c in frame if c.endswith('_actual_deg')),
                    peak_front_supply_mpa=float(frame.supply_pressure_front_mpa_g.max()),
                    peak_rear_supply_mpa=float(frame.supply_pressure_rear_mpa_g.max()),
                    system_settled_s=response['system_settled_s'],runner_wall_s=entry['runner_wall_s'],
                    final_max_piston_speed_m_s=max(abs(frame[c].iloc[-1]) for c in frame if c.endswith('_v_m_s'))))
            for suffix,kind in [('_actual_deg','轮角'),('_x_m','缸位移'),('_v_m_s','活塞速度'),('_mpa_g','压力')]:
                columns=[c for c in data if c.endswith(suffix) and c in other]
                diffs={c:float(np.max(abs(data[c]-np.interp(t,other.time_s,other[c])))) for c in columns}
                comparisons.append(dict(case=row['case'],quantity=kind,maximum_difference=max(diffs.values(),default=0),details=json.dumps(diffs)))
    pd.DataFrame(audits).to_csv(folder/'raw_history_stability_audit.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(comparisons).to_csv(folder/'full_history_timestep_comparison.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(metrics).to_csv(folder/'timestep_tracking_pressure_settling_summary.csv',index=False,encoding='utf-8-sig')
    # One bounded hotspot attempt: no change to equations, timestep or controller.
    runner=_runner();prof=cProfile.Profile();prof.enable()
    result=runner.run_case(J0CaseConfig(id='R2_PROFILE',target_outer_angle_deg=10,speed_kmh=5,duration_s=.2),
                           profile=linear_ramp_profile(60),reference_space='outer_angle')
    prof.disable();assert result.completed
    with (folder/'bounded_hotspot_profile.txt').open('w',encoding='utf-8') as stream:
        pstats.Stats(prof,stream=stream).sort_stats('cumulative').print_stats(35)
    print(pd.DataFrame(audits).to_string(index=False))
if __name__=='__main__':main()
