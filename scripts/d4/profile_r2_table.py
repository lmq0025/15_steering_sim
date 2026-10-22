"""Visible Qt XLSX import/bulk assignment timing, with actual event heartbeat."""
import sys,time,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/'src')]
import pandas as pd
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from steering_sim.desktop.app import MainWindow,STYLE
app=QApplication([]);app.setStyleSheet(STYLE);w=MainWindow();w.showMaximized();w.navigation.setCurrentRow(1)
def run():
    start=time.perf_counter();df=pd.read_excel(ROOT/'data/degradation/r2/task_spectrum_30day_example.xlsx');read=time.perf_counter()-start
    start=time.perf_counter();w.pages[1].load_frame(df);fill=time.perf_counter()-start
    source=pd.read_csv(ROOT/'outputs/desktop/r2/cd/paths_1000/statistics.csv')
    start=time.perf_counter();w.pages[2].statistics_table.set_frame(source);table=time.perf_counter()-start
    start=time.perf_counter();w.pages[2].statistics_table.proxy.sort(4);sort=time.perf_counter()-start
    payload=dict(xlsx_read_s=read,visible_task_table_fill_s=fill,result_rows=len(source),result_table_set_s=table,typed_sort_s=sort)
    (ROOT/'outputs/desktop/r2/table_performance.json').write_text(json.dumps(payload,indent=2),encoding='utf-8');print(payload,flush=True)
    w.close();app.quit()
QTimer.singleShot(1000,run);raise SystemExit(app.exec())
