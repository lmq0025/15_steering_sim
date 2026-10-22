"""Run the actual desktop preset through the FAST service and retain grids."""
import sys,json,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/'src')]
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from steering_sim.desktop.pages import SimulationPage
from steering_sim.desktop.services import DesktopCalculationService
app=QApplication([]);page=SimulationPage();payloads=[]
page.run_requested.connect(lambda _,payload:payloads.append(payload));page._batch()
out=ROOT/'outputs/desktop/r2/gui'
result=DesktopCalculationService(out/'calculations').run_batch_estimate(
    **payloads[0],progress=lambda *_:None,is_cancelled=lambda:False)
assert result['row_count']==3111
assert result['grids']['speed_kmh']==list(range(0,81,5))
assert result['grids']['target_outer_angle_deg']==list(range(-30,31))
assert result['grids']['friction_coefficient']==[.70,.75,.80]
metadata={key:result[key] for key in ('kind','grids','row_count','output_dir','runtime_s','note')}
metadata['validation_source']='CURRENT_DESKTOP_PRESET_AND_LIVE_FAST_SERVICE; not a new visible GUI screenshot'
(out/'batch_last_run.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(metadata,ensure_ascii=False,indent=2));page.close()
