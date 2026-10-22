"""Package only verified R4 evidence and current incremental source.

The report may disclose a missed speed target; packaging never converts a speed
limitation into a pass. Numerical equivalence, actual GUI checks and one complete
frozen-source regression are mandatory. No old runs are aggregated into a pass.
"""
from __future__ import annotations
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts.d4.run_r4_full_tests import junit_counts,protected_hashes,source_hashes

OUT=ROOT/'outputs/desktop/r4'
TARGET=ROOT/'handoff_to_chatgpt/phase_D4_R4.zip'
PYTHON=Path(r'E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe')
RESULT_EXTENSIONS={'.json','.csv','.xlsx','.npz','.png','.md','.log','.txt','.xml','.pstats'}


def sha(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):value.update(block)
    return value.hexdigest()


def read(path):
    path=Path(path)
    if not path.is_file():raise RuntimeError(f'缺少验收记录：{path}')
    return json.loads(path.read_text('utf-8-sig'))


def inside(path,base=ROOT):
    path=Path(path)
    if not path.is_absolute():path=ROOT/path
    path=path.resolve()
    if not path.is_relative_to(base.resolve()):raise RuntimeError(f'路径不在要求目录：{path}')
    return path


def passed(path):
    path=inside(path,OUT);record=read(path)
    if not isinstance(record,dict) or record.get('status')!='PASS':raise RuntimeError(f'验收记录不是PASS：{path}')
    return record


def checked_tests(path):
    counts=junit_counts(Path(path))
    if not counts or counts['tests']<1 or counts['failed'] or counts['errors']:
        raise RuntimeError(f'测试没有完整成功结果：{path}: {counts}')
    return counts


def main():
    if Path(sys.executable).resolve()!=PYTHON.resolve():raise RuntimeError('请使用唯一工程Python')
    parser=argparse.ArgumentParser()
    parser.add_argument('--cards-evidence',type=Path,default=OUT/'cards_gui_verified/acceptance.json')
    parser.add_argument('--rul-evidence',type=Path,default=OUT/'rul_gui/acceptance.json')
    parser.add_argument('--simulation-evidence',type=Path,default=OUT/'simulation_gui/acceptance.json')
    parser.add_argument('--bat-evidence',type=Path,default=OUT/'formal_bat_acceptance.json')
    parser.add_argument('--precision-summary',type=Path,default=OUT/'precision/summary.json')
    parser.add_argument('--targeted-xml',type=Path,default=OUT/'final_targeted.xml')
    args=parser.parse_args()
    full=passed(OUT/'full_repository_run_status.json')
    if full.get('returncode')!=0 or not full.get('source_hashes_unchanged') or not full.get('protected_hashes_unchanged') or not full.get('junit_written_during_this_run'):
        raise RuntimeError('最终全仓未在冻结源码及保护配置上成功完成')
    frozen=full.get('source_hashes_after')
    if not frozen or frozen!=full.get('source_hashes_before') or source_hashes()!=frozen:
        raise RuntimeError('源码/配置/测试/复现脚本在全仓测试后发生了变化')
    protection=protected_hashes()
    if protection!=full.get('protected_hashes') or any(not (ROOT/name).is_file() or sha(ROOT/name)!=value for name,value in protection.items()):
        raise RuntimeError('机械坐标、健康/控制/退化/阈值配置或保护源码发生变化')
    full_counts=checked_tests(OUT/'full_repository.xml')
    if full_counts!=full.get('actual_test_counts'):raise RuntimeError('全仓XML与运行器原始计数不一致')
    targeted_counts=checked_tests(inside(args.targeted_xml,OUT))
    report=ROOT/'docs/desktop/phase_D4_R4_report.md'
    if not report.is_file() or not report.stat().st_size:raise RuntimeError('缺少R4正式报告')
    content=report.read_text('utf-8')
    if 'D4-R4' not in content or any(marker in content for marker in ('IN_PROGRESS','待最终填入','交付状态：待完成')):
        raise RuntimeError('R4报告仍标为阶段草稿')
    if read(OUT/'progress.json').get('status')!='COMPLETE':raise RuntimeError('R4进度未根据真实证据标记COMPLETE')

    files=set()
    def add(path,required=True):
        path=inside(path)
        if not path.is_file():
            if required:raise RuntimeError(f'缺少交付文件：{path}')
            return
        if '__pycache__' in path.parts or path.suffix=='.pyc' or path.name=='failure.txt':return
        files.add(path)
    def tree(folder,extensions):
        folder=inside(folder)
        for path in folder.rglob('*'):
            if path.is_file() and path.suffix.lower() in extensions and not any(part.startswith(('full_temp_','prior_full_attempts','failed_probe')) for part in path.parts):add(path)
    def evidence(path):
        path=inside(path,OUT);record=passed(path);add(path)
        for item in record.get('screenshots',[]):
            raw=item['path'] if isinstance(item,dict) else item
            target=Path(raw)
            if not target.is_absolute():target=path.parent/target
            target=inside(target,OUT);add(target)
            if isinstance(item,dict) and item.get('sha256') and sha(target)!=item['sha256']:
                raise RuntimeError(f'真实截图哈希变化：{target}')
        return record

    cards=evidence(args.cards_evidence);rul=evidence(args.rul_evidence);simulation=evidence(args.simulation_evidence);bat=evidence(args.bat_evidence)
    layout=evidence(OUT/'rul_gui_layout/acceptance.json')
    if (layout.get('method')!='EXPLICIT_THIS_R4_RESULT_LAYOUT_REPLAY'
            or layout.get('new_solver_calls')!=0 or layout.get('new_random_draw_calls')!=0
            or layout.get('original_sample_count')!=128
            or layout.get('displayed_sample_ids')!=list(range(10))
            or not layout.get('all_legend_labels_within_plot')):
        raise RuntimeError('寿命图例重放验收缺少真实来源或改变了计算口径')
    for name,value in layout.get('source_hashes',{}).items():
        source=inside(name);add(source)
        if sha(source)!=value:raise RuntimeError(f'寿命图例重放数据哈希变化：{source}')
    if not layout.get('source_hashes'):raise RuntimeError('寿命布局重放没有来源哈希')
    tree(OUT/'rul_gui_layout',RESULT_EXTENSIONS)
    if [int(task['sample_count']) for task in cards.get('tasks',[])]!=[0,128,1000,128]:
        raise RuntimeError('03没有实际完成确定性、128、1000及重复128路径验收')
    if not all(cards.get(key) for key in ('project_restore_preserves_inputs_not_stale_results','display_switch_reuses_same_paths','expected_validation_error','cooperative_cancellation')):
        raise RuntimeError('03取消、输入错误、显示复用或工程恢复验收不完整')
    if not rul.get('project_roundtrip') or not rul.get('display_only_changes_do_not_resample'):
        raise RuntimeError('05保存/恢复及显示切换验收不完整')
    runs=rul.get('runs',[])
    if [run.get('checkpoints_requested') for run in runs]!=[5,10]:raise RuntimeError('05必须记录真实5和10检查点两轮运行')

    import numpy as np
    import pandas as pd
    sources=[]
    for task in cards['tasks']:
        source=inside(task['output_dir'],OUT);metadata=read(source/'metadata.json')
        if int(metadata['sample_count'])!=int(task['sample_count']):raise RuntimeError('03实际样本数与GUI记录不一致')
        add(source/'twenty_mode_and_parameters.csv');add(source/'prediction_intervals.csv')
        if int(task['sample_count']) and not list(source.glob('*.npz')):raise RuntimeError('03缺少真实全路径压缩数据')
        tree(source,RESULT_EXTENSIONS);sources.append(source)
    for run in runs:
        count=int(run['checkpoints_requested']);source=inside(run['output_dir'],OUT)
        summary=read(source/'rul_prediction_summary.json')
        quality=pd.read_csv(source/'quality_over_mission_cycles.csv');cases=pd.read_csv(source/'quality_checkpoint_case_details.csv')
        if len(quality)!=count or summary['executed_quality_checkpoint_count']!=count or run['quality_checkpoints_executed']!=count:
            raise RuntimeError('质量检查点数量没有对应真实输出记录')
        if len(cases)!=run['quality_cases_executed'] or len(cases)!=summary['executed_quality_case_count'] or len(cases)!=count*2:
            raise RuntimeError('质量检查点标准工况调用数量不一致')
        if quality.mission_cycle.astype(int).tolist()!=summary['quality_checkpoint_cycles'] or quality.mission_cycle.astype(int).tolist()!=run['quality_cycles']:
            raise RuntimeError('实际质量检查位置与GUI说明不一致')
        with np.load(source/'monte_carlo_checkpoints.npz',allow_pickle=False) as packed:
            if packed['damage'].ndim!=3 or packed['damage'].shape[1:]!=(128,20) or packed['sample_ids'].tolist()!=list(range(128)):
                raise RuntimeError('05不是完整128条20状态随机路径记录')
        samples=pd.read_csv(source/'monte_carlo_rul_samples.csv')
        if len(samples)!=128:raise RuntimeError('05寿命样本表不完整')
        tree(source,RESULT_EXTENSIONS);sources.append(source)
    if not runs[-1].get('five_vs_ten_mc_comparison',{}).get('equal') or not runs[-1].get('five_vs_ten_deterministic_comparison',{}).get('equal'):
        raise RuntimeError('检查点展示设置意外改变了确定性推进或Gamma抽样结果')
    # Historical comparison can reveal and honestly report tiny changes from
    # equivalent core arithmetic; do not silently replace them with a PASS.
    historical_comparison=runs[0].get('r3_same_seed_comparison',{})

    if simulation.get('scenario',{}).get('target_outer_angle_deg')!=10 or simulation.get('scenario',{}).get('seconds_per_degree')!=6:
        raise RuntimeError('真实Qt斜坡验收不是要求的0→10°、6秒/度工况')
    if simulation.get('physical_horizon_s')!=70 or simulation.get('actual_hydraulic_step_s')!=.0005:
        raise RuntimeError('GUI验收的物理时长或参考积分步长不一致')
    mode=simulation.get('mode')
    if mode not in ('EXPLICIT_THIS_R4_RECORDED_INTEGRATION_REPLAY','LIVE_QT_QTHREAD_FULL_22_STATE'):
        raise RuntimeError('GUI证据没有区分本次实际求解与明确结果回放')
    csv_path=inside(simulation['csv_path'],OUT);add(csv_path)
    if simulation.get('csv_sha256') and sha(csv_path)!=simulation['csv_sha256']:raise RuntimeError('Qt实际积分CSV哈希变化')
    for name,value in simulation.get('source_file_sha256',{}).items():
        source=inside(Path(simulation['source_folder'])/name,OUT)
        if sha(source)!=value:raise RuntimeError('Qt使用的正式记录源文件哈希变化')
        add(source)
    if not bat.get('conda_prefix_and_default_env_cleared') or len(bat.get('launches',[]))<2:
        raise RuntimeError('缺少未激活环境下正式BAT独立启动证据')
    for index,launch in enumerate(bat['launches']):
        if launch.get('normal_qt_exit_code')!=0:raise RuntimeError('正式BAT应用未正常退出')
        if launch.get('pages_visited')!=[1,2,3,4,5]:raise RuntimeError('正式BAT没有实际验证全部五页')
        if index==0 and (launch.get('window_visible_s',0)<30 or not launch.get('health_simulation_finished')):
            raise RuntimeError('正式BAT首次启动没有稳定30秒并完成健康联合仿真')
        add(launch['log'])
        add(launch['screenshot'])
        add(OUT/f'bat_launch_{index+1}.stdout.log')
        add(OUT/f'bat_launch_{index+1}.stderr.log')

    precision_path=inside(args.precision_summary,OUT);precision=read(precision_path);add(precision_path)
    if not isinstance(precision,list) or not {2.,5.,10.}.issubset({float(row['angle_deg']) for row in precision}):
        raise RuntimeError('精度证据至少需要2°、5°、10°全程比较')
    precision_rows=[];benchmark_sources=set()
    for item in precision:
        if item.get('status')!='PASS':raise RuntimeError('有未通过的数值精度对照')
        path=inside(item['report'],OUT);record=passed(path);add(path)
        if record.get('failures') or not record.get('rows') or any(not row.get('passed') for row in record['rows']+record['response_checks']+record['status_checks']):
            raise RuntimeError('精度记录含失败字段或空比较')
        tree(path.parent,{'.json','.csv'})
        for role in ('baseline','candidate'):
            source=inside(record[f'{role}_path'],OUT);benchmark_sources.add(source)
            for name,value in record[f'{role}_file_sha256'].items():
                candidate=source/name;add(candidate)
                if sha(candidate)!=value:raise RuntimeError(f'精度比较原始数据改变：{candidate}')
            meta=read(source/'result.json')
            if role=='candidate':
                for name,value in meta['source_hashes'].items():
                    if sha(inside(ROOT/name))!=value:raise RuntimeError(f'数值验收后正式核心源码已变化：{name}')
        precision_rows.append(dict(angle_deg=item['angle_deg'],status=record['status'],timings=record['timings'],coverage=record['coverage'],
                                   profiling_enabled=record.get('profiling_enabled')))
    # Include a completed long-case record if available, and explicit profiling
    # results. Do not include incomplete probes or every old service CSV copy.
    for folder in (OUT/'baseline/angle_30',OUT/'optimized/angle_30',OUT/'optimized_long/angle_30'):
        if (folder/'result.json').is_file():benchmark_sources.add(folder)
    for folder in benchmark_sources:
        for name in ('result.json','samples.npz','rk_boundaries.npz','hotspots.csv','hotspots.txt','profile.pstats'):add(folder/name,required=False)
    profile_records=[]
    for path in OUT.glob('profile*/angle_*/result.json'):
        if (path.parent/'hotspots.csv').is_file():
            profile_records.append(path)
            for name in ('result.json','hotspots.csv','hotspots.txt','profile.pstats'):add(path.parent/name,required=False)
    if not profile_records:raise RuntimeError('缺少正式链的实际性能剖析结果及调用热点CSV')
    historical_long_comparison=None
    if (OUT/'historical_30_verified').is_dir():
        tree(OUT/'historical_30_verified',RESULT_EXTENSIONS)
        historical_manifest=read(OUT/'historical_30_verified/source_manifest.json')
        historical_long_comparison=read(OUT/'historical_30_verified/comparison.json')
        add(OUT/'historical_30/comparison.json',required=False)
        # This is only the earlier 10 ms recorder series, not an invented
        # 0.5 ms historical boundary record. Include exactly its hashed inputs.
        for name,value in historical_manifest['historical_and_config_files_sha256'].items():
            source=inside(name);add(source)
            if sha(source)!=value:raise RuntimeError(f'历史30°对照原始输入哈希变化：{source}')
        historical_candidate=inside(historical_manifest['candidate_folder'],OUT)
        for name,value in historical_manifest['candidate_file_sha256'].items():
            source=historical_candidate/name;add(source)
            if sha(source)!=value:raise RuntimeError(f'30°候选积分记录哈希变化：{source}')

    # Include current code and interfaces needed by this incremental delivery.
    for folder in ('src/steering_sim/desktop','src/steering_sim/j0_coupling','src/steering_sim/hydraulics_engineering',
                   'src/steering_sim/degradation','src/steering_sim/quality_assessment','tests'):
        tree(ROOT/folder,{'.py','.svg','.json','.csv','.yaml','.yml'})
    tree(ROOT/'data/degradation/r2',{'.csv','.xlsx','.json'})
    for name in ('src/steering_sim/demo/service.py','scripts/d3/run_phase_d3.py','pyproject.toml',
                 'requirements-desktop.txt','start_steering_desktop.bat','scripts/d4/launch_desktop.py',
                 'scripts/d4/check_desktop_environment.py','scripts/d4/build_pyinstaller.ps1'):
        add(ROOT/name)
    for path in (ROOT/'scripts/d4').glob('*r4*.py'):add(path)
    for name in protection:
        if name.startswith('configs/') or name=='mechanical_model_input_spec_v1.0.yaml':add(ROOT/name)
    # Explicit reference modules required by regression tests and the original
    # runner boundary used by timing comparisons;
    # the bulk pre-R4 snapshot and all historical deliveries are excluded.
    add(ROOT/'outputs/desktop/r3/baseline_r2/src/steering_sim/degradation/stochastic.py')
    for name in ('hydraulics_engineering/parameters.py','hydraulics_engineering/model.py','j0_coupling/geometry.py','j0_coupling/road_load.py','j0_coupling/runner.py'):
        add(OUT/'baseline_r3/src/steering_sim'/name)
    add(report);add(OUT/'baseline.json');add(OUT/'progress.json')
    for name in ('full_repository.xml','full_repository.log','full_repository_run_status.json'):add(OUT/name)
    add(args.targeted_xml)
    for path in OUT.glob('*.xml'):add(path)
    for path in OUT.glob('*.md'):add(path)
    for path in OUT.glob('*.csv'):add(path)
    for name in ('baseline_final_audit.json','performance_summary.json','hardware.json','formal_bat_acceptance.json','bat_main.png','bat_restart.png'):
        add(OUT/name,required=False)
    # Preserve the compact failed harness record for audit, never its prior
    # successful substeps as a substitute for the independent verified run.
    previous_cards_attempt=OUT/'cards_gui/acceptance.json'
    if previous_cards_attempt.is_file() and previous_cards_attempt.resolve()!=inside(args.cards_evidence,OUT):
        add(previous_cards_attempt)
    # Exact successful GUI folders only, including reports, screenshot pixels
    # and fresh result snapshots; never the entire outputs history.
    for path in (args.cards_evidence,args.rul_evidence,args.simulation_evidence):tree(Path(path).parent,RESULT_EXTENSIONS)

    entries=[dict(path=path.relative_to(ROOT).as_posix(),bytes=path.stat().st_size,sha256=sha(path)) for path in sorted(files)]
    manifest=dict(delivery='PHASE D4-R4',incremental_package=True,created_at=datetime.now().isoformat(timespec='seconds'),
        python=sys.executable,note='当前本地D4-R3的增量源码、正式结果和验收证据；不是独立EXE。',
        full_repository_test_counts=full_counts,targeted_test_counts=targeted_counts,
        source_hashes_unchanged_during_final_test=True,protected_files_unchanged=True,
        numerical_precision=precision_rows,gui_simulation_mode=mode,historical_seed_comparison=historical_comparison,
        rul_legend_validation_method=layout['method'],
        historical_long_case_comparison=historical_long_comparison,
        actual_quality_checkpoints=[run['quality_cycles'] for run in runs],
        earlier_gui_attempts_combined_with_verified_results=False,
        speed_target_is_not_fabricated_by_packaging=True,
        excluded=['整套历史快照（仅保留测试及积分边界所需6个参考源码）','测试临时目录','失败探针','中断全仓运行','历史大数据/ZIP','Conda','Amesim'],
        manifest_scope='全部payload文件；manifest自身哈希在外置完整性记录，避免递归自哈希。',files=entries)
    manifest_path=OUT/'delivery_manifest.json';manifest_bytes=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    manifest_path.write_bytes(manifest_bytes);files.add(manifest_path)
    TARGET.parent.mkdir(parents=True,exist_ok=True);building=TARGET.with_suffix('.zip.building')
    if building.exists():raise RuntimeError(f'存在未完成打包文件，先检查而不是覆盖：{building}')
    with zipfile.ZipFile(building,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for path in sorted(files):archive.write(path,path.relative_to(ROOT).as_posix())
    manifest_name=manifest_path.relative_to(ROOT).as_posix()
    with zipfile.ZipFile(building) as archive:
        if archive.testzip() is not None:raise RuntimeError('ZIP CRC校验失败')
        expected={entry['path'] for entry in entries}|{manifest_name}
        if set(archive.namelist())!=expected or len(archive.namelist())!=len(expected):raise RuntimeError('ZIP文件清单不一致或重名')
        if archive.read(manifest_name)!=manifest_bytes:raise RuntimeError('ZIP清单字节不同')
        for entry in entries:
            payload=archive.read(entry['path'])
            if len(payload)!=entry['bytes'] or hashlib.sha256(payload).hexdigest()!=entry['sha256']:raise RuntimeError('ZIP逐文件SHA256失败：'+entry['path'])
    if TARGET.exists():
        prior=TARGET.with_name(TARGET.stem+'_previous_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.zip')
        shutil.copy2(TARGET,prior)
        if TARGET.with_suffix('.zip.sha256').exists():shutil.copy2(TARGET.with_suffix('.zip.sha256'),prior.with_suffix('.zip.sha256'))
    building.replace(TARGET);digest=sha(TARGET)
    TARGET.with_suffix('.zip.sha256').write_text(f'{digest}  {TARGET.name}\n',encoding='ascii')
    integrity=dict(status='PASS',path=str(TARGET),bytes=TARGET.stat().st_size,file_count=len(files),sha256=digest,
        crc_testzip='PASS',manifest_payload_sha256_check='PASS',payload_files_verified=len(entries),
        archived_manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),full_repository_test_counts=full_counts,
        targeted_test_counts=targeted_counts,skips_preserved_as_skips=True)
    (OUT/'delivery_integrity.json').write_text(json.dumps(integrity,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(integrity,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
