"""Visible current Qt preset execution and Chinese FAST-grid evidence."""
import sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from steering_sim.desktop.app import MainWindow,STYLE
from steering_sim.desktop.services import DesktopCalculationService
OUT=ROOT/'outputs/desktop/r2/gui'
app=QApplication([]);app.setStyleSheet(STYLE);window=MainWindow()
window.service=DesktopCalculationService(OUT/'calculations');window.showMaximized()
def finished(task,result):
    assert task=='batch' and result['row_count']==3111
    metadata={k:result[k] for k in ('kind','grids','row_count','output_dir','runtime_s','note')}
    metadata['validation_source']='LIVE_QT_DESKTOP_PRESET_AND_FAST_SERVICE'
    (OUT/'batch_last_run.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    def capture():
        app.processEvents();app.primaryScreen().grabWindow(int(window.winId())).save(str(OUT/'05b_3111真实网格覆盖摘要.png'))
        print(json.dumps(metadata,ensure_ascii=False),flush=True);window.close();app.quit()
    QTimer.singleShot(250,capture)
def failed(task,message,detail):print(detail,flush=True);app.exit(2)
window.controller.finished.connect(finished);window.controller.failed.connect(failed)
QTimer.singleShot(500,window.pages[0]._batch)
raise SystemExit(app.exec())
