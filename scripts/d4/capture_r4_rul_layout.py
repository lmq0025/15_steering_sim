"""Visible Qt replay of this R4 run for legend layout; no new computation."""
from pathlib import Path
import hashlib
import json
import sys
import time
import traceback

ROOT=Path(__file__).resolve().parents[2]
assert Path(sys.executable)==Path(r'E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe')
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
import numpy as np
import pandas as pd
from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication
from steering_sim.desktop.app import MainWindow,STYLE
from steering_sim.desktop.services import HEALTHY
from steering_sim.hydraulics_engineering import load_parameters


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    out=ROOT/'outputs/desktop/r4/rul_gui_layout'
    if (out/'acceptance.json').exists():raise RuntimeError('保留现有布局验收，不覆盖')
    out.mkdir(parents=True,exist_ok=True)
    acceptance=ROOT/'outputs/desktop/r4/rul_gui/acceptance.json'
    origin=json.loads(acceptance.read_text('utf-8'));assert origin['status']=='PASS'
    source=Path(next(row['output_dir'] for row in origin['runs'] if row['checkpoints_requested']==10))
    hashes={str(acceptance.relative_to(ROOT)):sha(acceptance),str(HEALTHY.relative_to(ROOT)):sha(HEALTHY)}
    def recorded(name):
        path=source/name;hashes[str(path.relative_to(ROOT))]=sha(path);return path
    result=dict(kind='rul',summary=json.loads(recorded('rul_prediction_summary.json').read_text('utf-8')),
        mc_models=json.loads(recorded('component_failure_thresholds.json').read_text('utf-8'))['modes'],
        physical_reference_parameters=load_parameters(HEALTHY),output_dir=str(source))
    for key,name in dict(history='mission_cycle_history.csv',deterministic_modes='component_parameter_trajectories.csv',
            quality='quality_over_mission_cycles.csv',quality_cases='quality_checkpoint_case_details.csv',
            mc_summary='monte_carlo_rul_summary.csv',mc_samples='monte_carlo_rul_samples.csv',modes='component_degradation_modes.csv').items():
        result[key]=pd.read_csv(recorded(name))
    with np.load(recorded('monte_carlo_checkpoints.npz'),allow_pickle=False) as data:
        result['mc_checkpoints']={key:data[key].copy() for key in data.files}
    app=QApplication([]);app.setFont(QFont('Microsoft YaHei UI',11));app.setStyleSheet(STYLE)
    window=MainWindow();page=window.pages[4];window.navigation.setCurrentRow(4)
    window.setWindowTitle('D4-R4 本轮已计算寿命结果重放｜未重新求解或抽样')
    attempted=[];shots=[];started=time.perf_counter()
    def forbidden(*_args,**_kwargs):
        attempted.append('unexpected_calculation');raise RuntimeError('布局验收禁止求解和抽样')
    window.controller.start=forbidden
    window.showMaximized()
    def fail(kind,value,tb):
        record=dict(status='FAIL',method='EXPLICIT_THIS_R4_RESULT_LAYOUT_REPLAY',
            source_hashes=hashes,error=''.join(traceback.format_exception(kind,value,tb)),screenshots=shots)
        (out/'acceptance.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
        window.close();app.exit(2)
    sys.excepthook=fail
    def prepare():
        page.restore_quality_settings(dict(quality_density=10,quality_checkpoints=10))
        page.task_finished(result);page.random_view.path_count.setCurrentIndex(1)
        page.banner.set_status('本轮已计算结果重放：原10个检查点、128条随机路径；仅验证图例布局，未重新求解或抽样。','info')
        QTimer.singleShot(600,capture)
    def capture():
        view=page.random_view;legend=view.plot.plotItem.legend
        labels=[label.text for _,label in legend.items]
        assert legend.columnCount==3 and legend.rowCount<=5
        assert all(f'样本ID {i}' in labels for i in range(10))
        bounds=legend.sceneBoundingRect();plot_bounds=view.plot.sceneBoundingRect()
        assert bounds.bottom()<=plot_bounds.bottom() and bounds.right()<=plot_bounds.right()
        target=out/'01_本轮结果明确重放_十路径三列完整图例.png'
        assert app.primaryScreen().grabWindow(int(window.winId())).save(str(target),'PNG')
        shots.append(dict(path=str(target),sha256=sha(target)))
        assert not attempted and all(sha(ROOT/path)==value for path,value in hashes.items())
        record=dict(status='PASS',method='EXPLICIT_THIS_R4_RESULT_LAYOUT_REPLAY',
            screenshot_method='Actual visible MainWindow QScreen.grabWindow',source_folder=str(source),
            source_hashes=hashes,original_accepted_calculation=str(acceptance),
            new_solver_calls=0,new_random_draw_calls=0,original_sample_count=128,displayed_sample_ids=view.displayed_ids,
            legend_columns=legend.columnCount,legend_rows=legend.rowCount,legend_labels=labels,
            all_legend_labels_within_plot=True,screenshots=shots,wall_s=time.perf_counter()-started)
        (out/'acceptance.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(record,ensure_ascii=False),flush=True);window.close();app.exit(0)
    QTimer.singleShot(800,prepare)
    return app.exec()


if __name__=='__main__':raise SystemExit(main())
