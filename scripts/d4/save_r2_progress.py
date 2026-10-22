"""Save current evidence; never replace it with the former static R2-A status."""
import hashlib
import json
from pathlib import Path
import subprocess
import argparse
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[2]
folder=ROOT/'outputs/desktop/r2'
baseline=json.loads((folder/'baseline.json').read_text('utf-8'))
summary_path=folder/'a/reference_step_matrix/ramp_acceptance_summary.json'
rows=json.loads(summary_path.read_text('utf-8')) if summary_path.exists() else []
payload={
    'phase':'D4-R2', 'overall_status':'IN_PROGRESS',
    'r2_a_exploratory_2ms_cases_completed':[row['case'] for row in json.loads((folder/'a/ramp_acceptance_summary.json').read_text('utf-8'))],
    'current_default_0p5ms_cases_completed':['0_to_p2']+[row['case'] for row in rows],
    'r2_a_status':'REFERENCE_CASES_COMPLETE; 0.5ms retained; long-ramp wall-time target not met',
    'stages':{'B':'explicit rate, strict duration, cache keys and templates implemented',
              'C':'D3 20-state history and reference physical parameters implemented',
              'D':'shared Gamma core, real 128/500/1000 paths and mapped parameter quantiles',
              'E':'Chinese UI, real Qt workflow, save/open, background export and cancellation'},
    'reference_0p5ms':rows,
    'next_stage':'Await full repository tests, final report and delivery integrity check',
    'tests': {},
    'baseline_hashes_unchanged':{path:hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==digest
                                 for path,digest in baseline['sha256'].items()},
    'git_status':subprocess.check_output(['git','status','--short'],cwd=ROOT,text=True),
    'final_zip_created':(ROOT/'handoff_to_chatgpt/phase_D4_R2.zip').exists(),
}
for name in ('targeted_tests','core_tests','core_final','ui_final_check','language_final','full_repository','tk_isolated','tk_single','tk_replay_isolated'):
    file=folder/f'{name}.xml'
    if file.exists():
        payload['tests'][name]=dict(ET.parse(file).getroot().find('testsuite').attrib)
for key,path in [('gui_acceptance','gui/gui_acceptance.json'),('stochastic_benchmark','cd/benchmark.json'),('final_test_run','full_repository_run_status.json')]:
    file=folder/path
    if file.exists():payload[key]=json.loads(file.read_text('utf-8'))
parser=argparse.ArgumentParser();parser.add_argument('--complete',action='store_true')
if parser.parse_args().complete:
    final=payload['tests'].get('full_repository',{})
    if not final or int(final.get('failures',0))+int(final.get('errors',0)):
        raise RuntimeError('Full repository tests missing or failing; cannot mark complete')
    if payload.get('final_test_run',{}).get('status')!='PASS':
        raise RuntimeError('Frozen-source final repository run has not passed')
    if payload.get('gui_acceptance',{}).get('status')!='PASS' or not all(payload['baseline_hashes_unchanged'].values()):
        raise RuntimeError('GUI or protected baseline check incomplete')
    payload['overall_status']='COMPLETED_WITH_RECORDED_LIMITATIONS'
    payload['next_stage']='STOP: no new algorithms or mechanical/hydraulic redesign'
(folder/'progress.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(payload,ensure_ascii=False,indent=2))
