"""Prepare new explicit-rate CSV/JSON without modifying historical spectra."""
import sys
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
import pandas as pd
from steering_sim.degradation.spectrum import COLUMN_LABELS,load_task_spectrum

out=ROOT/'data/degradation/r2';out.mkdir(parents=True,exist_ok=True)
frame=pd.read_csv(ROOT/'data/degradation/task_spectrum_30day_example.csv')
frame['seconds_per_degree']=6.0
for example in (True,False):
    name='task_spectrum_30day_example' if example else 'task_spectrum_template'
    current=frame.copy() if example else frame.iloc[:0].copy()
    current.rename(columns=COLUMN_LABELS).to_csv(out/f'{name}.csv',index=False,encoding='utf-8-sig')
    # A single editable zero-motion row in the blank workbook illustrates units.
    matrix=[list(current.rename(columns=COLUMN_LABELS).columns)]+current.values.tolist()
    (out/f'{name}.json').write_text(json.dumps(matrix,ensure_ascii=False),encoding='utf-8')
load_task_spectrum(out/'task_spectrum_30day_example.csv')
print(out)
