"""Compare complete R2-A histories, not only endpoint positions."""
import json
from pathlib import Path
import time
import numpy as np
import validate_ramp_timestep as old
from steering_sim.demo.scenario import DemoScenario
from steering_sim.demo.service import DemoService
from steering_sim.desktop.response_analysis import linear_ramp_profile, analyze_response, ResponseCriteria
from steering_sim.j0_coupling.runner import CHANNEL_ORDER, WHEELS

ROOT = Path(__file__).resolve().parents[2]
out = ROOT/'outputs/desktop/r2/a/timestep'
results = []
for dt in (0.0005, 0.002):
    service = DemoService(output_dir=out)
    service.runner.dt_h = dt
    service.runner.substeps = int(round(service.runner.dt_c/dt))
    service.runner.stride = int(round(0.01/dt))
    started = time.perf_counter()
    result = service.run(DemoScenario(target_outer_angle_deg=2, speed_kmh=5,
        friction_coefficient=0.8, axle_mass_t=(11.5,)*6, duration_s=17, case_id='R2_A'),
        profile=linear_ramp_profile(12), reference_time_s=12, reference_space='outer_angle',
        output_suffix=f'R2_{dt}', generate_figures=False)
    assert result.completed
    response = analyze_response(result.samples, 12, ResponseCriteria())
    results.append((result, response, time.perf_counter()-started))
    print('DONE', dt, results[-1][2], flush=True)
a,b=results
keys = [f'wheel_{w}_actual_deg' for w in WHEELS]
cyl = [f'{c}_x_m' for c in CHANNEL_ORDER]
payload = {
    'case': '0_to_2_6_s_per_degree_5_s_hold',
    'steps_s': [0.0005,0.002], 'wall_s': [a[2],b[2]],
    'maximum_whole_history_wheel_difference_deg': max(float(np.max(np.abs(a[0].samples[k]-b[0].samples[k]))) for k in keys),
    'maximum_whole_history_cylinder_difference_m': max(float(np.max(np.abs(a[0].samples[k]-b[0].samples[k]))) for k in cyl),
    'peak_supply_pressure_mpa': [max(float(np.max(r[0].samples[k])) for k in ('supply_pressure_front_mpa_g','supply_pressure_rear_mpa_g')) for r in results],
    'maximum_tracking_error_deg': [max(float(np.max(np.abs(r[0].samples[k]-r[0].samples[k.replace('_actual_', '_command_')]))) for k in keys) for r in results],
    'system_settled_s': [a[1]['system_settled_s'],b[1]['system_settled_s']],
}
(out/'comparison.json').write_text(json.dumps(payload,indent=2),encoding='utf-8')
print(json.dumps(payload,indent=2))
