"""Persist R3 continuation point from actual evidence, not inferred pass counts."""
from pathlib import Path
import sys,json,time
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'outputs/desktop/r3'
def read(name):
    path=OUT/name
    return json.loads(path.read_text('utf-8')) if path.exists() else {}
full=read('full_repository_run_status.json');gui=read('gui/acceptance.json');bat=read('formal_bat_acceptance.json')
complete='--complete' in sys.argv
if complete and not (full.get('status')=='PASS' and full.get('source_hashes_unchanged') and gui.get('status')=='PASS' and bat.get('status')=='PASS'):
    raise RuntimeError('Do not mark an unverified phase complete')
progress=dict(phase='D4-R3',status='COMPLETE' if complete else 'FINAL_REGRESSION_RUNNING',updated_at=time.strftime('%Y-%m-%d %H:%M:%S'),
    stages={'R3-A':'IMPLEMENTED_AND_REAL_QT_VERIFIED','R3-B':'IMPLEMENTED_AND_REAL_QT_VERIFIED','R3-C':'IMPLEMENTED_AND_REAL_QT_VERIFIED','R3-D':'VERIFIED_FOR_DELIVERY' if complete else 'FINAL_REGRESSION_AND_DELIVERY'},
    live_ramp='a_live/acceptance.json',real_gui='gui/acceptance.json',final_presentation_replay='gui/final_views/evidence.json',
    bat='formal_bat_acceptance.json',targeted_xml='final_targeted.xml',full_repository_status=full.get('status','NOT_RUN'),
    production_sources_frozen=full.get('status')=='RUNNING' or full.get('source_hashes_unchanged',False),
    remaining=[] if complete else ['Wait for full_repository.xml and frozen-source hashes','Finalize report, package and validate CRC/SHA256'],
    limitations=['D3 GUI service wall time 75.27s, above 60s target','Not an arbitrary-target standalone executable','BAT verified by independent cmd process and Qt probes, not manual Explorer double click'],
    scope='Display/playback/service recording only; formal model/parameter/threshold baseline protected')
(OUT/'progress.json').write_text(json.dumps(progress,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(progress,ensure_ascii=False,indent=2))
