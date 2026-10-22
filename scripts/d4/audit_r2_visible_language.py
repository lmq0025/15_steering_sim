"""List untranslated human-facing table tokens from the actual current results."""
import sys,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/'src')]
import pandas as pd
from steering_sim.desktop.localization import cn
OUT=ROOT/'outputs/desktop/r2/gui'
degr=Path(json.loads((OUT/'degradation_last_run.json').read_text('utf-8'))['output_dir'])
rul=Path(json.loads((OUT/'rul_last_run.json').read_text('utf-8'))['output_dir'])
batch=Path(json.loads((OUT/'batch_last_run.json').read_text('utf-8'))['output_dir'])
paths=list((degr/'raw').glob('*.csv'))+[OUT/'quality_day0_day30_raw.csv']+[rul/name for name in ('mission_cycle_history.csv','quality_over_mission_cycles.csv','monte_carlo_rul_summary.csv','component_degradation_modes.csv')]+[batch/'raw_fast_batch_estimate.csv']
found=set()
for path in paths:
    frame=pd.read_csv(path)
    values=list(frame.columns)
    for column in frame.select_dtypes(include=['object','str']).columns:values+=list(frame[column].dropna().unique())
    for value in values:
        translated=cn(value)
        if re.search(r'[A-Za-z]{2,}',translated) and not any(x in translated for x in ('ENGINEERING_','D3_RUL_','m³','L/min','MPa','km/h','mm','m/s','m3','m_per','deg','rad')):
            found.add((str(value),translated))
print(json.dumps(sorted(found),ensure_ascii=False,indent=2))
(ROOT/'outputs/desktop/r2/language_audit.json').write_text(json.dumps({
    'audited_files':[str(p) for p in paths],'remaining_tokens':sorted(found),
    'scope':'本轮实际结果全表字段及字符串值；保留正式模型/版本技术编号及SI单位，内部API和原始字段导出不重命名'},ensure_ascii=False,indent=2),encoding='utf-8')
