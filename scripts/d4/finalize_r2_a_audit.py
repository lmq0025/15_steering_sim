"""Audit persisted real histories after the R2-A acceptance matrix completes."""
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
for value in (ROOT,ROOT/'src'):
    sys.path.insert(0,str(value))
from steering_sim.desktop.response_analysis import ResponseCriteria,analyze_response

folder=ROOT/'outputs/desktop/r2/a'
summary=folder/'ramp_acceptance_summary.json'
rows=json.loads(summary.read_text('utf-8'))
corrected=json.loads((folder/'corrected_initial_load/ramp_acceptance_summary.json').read_text('utf-8'))[0]
rows=[corrected if row['case']==corrected['case'] else row for row in rows]
for row in rows:
    # This finalizer combines the first R2-A exploratory runs, which were
    # launched with the former 2 ms setting before convergence review.
    row['hydraulic_step_s']=0.002
    row['validation_status']='EXPLORATORY_2MS_NOT_CURRENT_DEFAULT'
assert len(rows)==5 and all(row['calculation_success'] for row in rows)
audit=[]
for row in rows:
    data=pd.read_csv(row['timeseries_csv'])
    t=data.time_s.to_numpy()
    command=row['initial_outer_angle_deg']+np.minimum(t/row['command_completion_s'],1)*(
        row['final_outer_angle_deg']-row['initial_outer_angle_deg'])
    error=float(np.max(np.abs(data.outer_angle_reference_deg-command)))
    assert error<1e-10
    outer=np.where(command>=0,data.wheel_axle1_right_command_deg,data.wheel_axle1_left_command_deg)
    for threshold in (0.001,0.0001,0.00001):
        response=analyze_response({key:data[key].to_numpy() for key in data},
                                 row['command_completion_s'],
                                 ResponseCriteria(piston_speed_threshold_m_s=threshold))
        audit.append({'case':row['case'],'exact_input_max_error_deg':error,
            'represented_outer_target_max_error_deg':float(np.max(np.abs(outer-command))),
            'piston_speed_threshold_m_s':threshold,
            'all_cylinders_settled_s':response['all_cylinders_settled_s'],
            'system_settled_s':response['system_settled_s']})
summary.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
pd.DataFrame(rows).to_csv(folder/'ramp_acceptance_summary.csv',index=False,encoding='utf-8-sig')
pd.DataFrame(audit).to_csv(folder/'reference_and_settling_audit.csv',index=False,encoding='utf-8-sig')
print(json.dumps(audit,indent=2))
