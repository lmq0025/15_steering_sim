"""Real R2-A acceptance, preserving all R1 output files."""
from pathlib import Path
import json
import numpy as np
import pandas as pd

import run_ramp_acceptance as acceptance
from steering_sim.desktop.response_analysis import ResponseCriteria, analyze_response

ROOT = Path(__file__).resolve().parents[2]
acceptance.OUTPUT = ROOT / 'outputs/desktop/r2/a/reference_step_matrix'
acceptance.run({'0_to_p2', '0_to_p10', '0_to_n10', 'p10_to_n10', '0_to_p30'})
rows = json.loads((acceptance.OUTPUT / 'ramp_acceptance_summary.json').read_text('utf-8'))
audit = []
for row in rows:
    data = pd.read_csv(row['timeseries_csv'])
    time = data.time_s.to_numpy()
    duration = row['command_completion_s']
    start = row['initial_outer_angle_deg']
    end = row['final_outer_angle_deg']
    expected = start+np.minimum(time/duration, 1)*(end-start)
    request_error = float(np.max(np.abs(data.outer_angle_reference_deg-expected)))
    # The linkage inverse fit has a finite tolerance; audit the represented
    # physical target separately from the exact scalar input command.
    outside = np.where(expected>=0, data.wheel_axle1_right_command_deg,
                       data.wheel_axle1_left_command_deg)
    fit_error = float(np.max(np.abs(outside-expected)))
    for velocity in (0.001, 0.0001, 0.00001):
        criteria = ResponseCriteria(piston_speed_threshold_m_s=velocity)
        response = analyze_response({key: data[key].to_numpy() for key in data}, duration, criteria)
        audit.append({'case': row['case'], 'input_reference_max_error_deg': request_error,
                      'represented_outer_wheel_max_error_deg': fit_error,
                      'piston_speed_threshold_m_s': velocity,
                      'system_settled_s': response['system_settled_s'],
                      'cylinders_settled_s': response['all_cylinders_settled_s']})
    assert request_error < 1e-10
pd.DataFrame(audit).to_csv(acceptance.OUTPUT/'reference_and_settling_audit.csv', index=False)
print(json.dumps(audit, indent=2))
