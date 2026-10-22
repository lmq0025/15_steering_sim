"""Chinese presentation only; stable API and raw export keys are unchanged."""
import re
from functools import lru_cache

KINDS={'pump':'齿轮泵','gear_pump':'齿轮泵','valve':'转向阀','steering_valve':'转向阀',
       'cylinder':'等效作动缸','hydraulic_cylinder':'等效作动缸'}
MODES={'leakage_wear':'内泄漏磨损','mechanical_loss':'机械损失增加',
       'response_lag':'响应迟滞','friction_growth':'摩擦阻力增加'}
IDS={'front':'前供油组','rear':'后供油组','rail_front':'前供油组','rail_rear':'后供油组',
     'channel_front':'一二桥作动组','channel_rear_1':'四桥作动组',
     'channel_rear_2':'五桥作动组','channel_rear_3':'六桥作动组'}
FIELDS={
 'component_type':'部件类型','component_id':'部件名称','degradation_mode':'退化模式',
 'damage':'累计损伤','equivalent_exposure':'累计等效载荷','failure_damage':'硬失效损伤阈值',
 'exposure_unit':'等效载荷单位','damage_unit':'损伤单位','rate':'退化速率',
 'parameter':'物理参数','parameter_value':'参数值','parameter_unit':'参数单位',
 'mechanism':'物理机理','drivers':'驱动量','source':'来源','calibration_status':'标定状态',
 'model_version':'模型版本','segment_id':'工况段编号','repeat_index':'重复序号',
 'speed_kmh':'车速（km/h）','target_outer_angle_deg':'一桥外轮最终转角（°）',
 'previous_outer_angle_deg':'起始外轮角（°）','segment_duration_s':'整段时间（s）',
 'seconds_per_degree':'每度转向时间（秒/度）','friction_coefficient':'附着系数',
 'pump_running':'泵运行','repeats':'重复次数','contamination_severity':'污染严重度',
 'oil_temperature_c':'油温（℃）','day':'任务时间（天）','elapsed_day':'累计时间（天）',
 'elapsed_s':'累计时间（s）','transition_time_s':'转向指令时间（s）','holding_time_s':'保持时间（s）',
 'metric':'指标','value':'数值','unit':'单位','mean':'均值','deterministic':'确定性预测',
 'p025':'P2.5','p05':'P05','p50':'P50（中位数）','p95':'P95','p975':'P97.5','std':'样本标准差',
 'leakage_coefficient':'内泄漏系数','volumetric_efficiency':'参考工况容积效率',
 'mechanical_efficiency':'机械效率','reference_leakage_lpm':'参考压差泄漏量（L/min）',
 'response_time_s':'阀响应时间常数（s）','lag_scale':'响应迟滞倍率',
 'friction_scale':'摩擦倍率','reference_friction_n':'参考摩擦力（N）',
 'internal_leakage_m3_s_per_pa':'内泄漏系数（m³/(s·Pa)）',
 'channel':'等效作动通道','purpose':'损伤用途','cylinder_friction_growth':'缸摩擦增长模式',
 'mission_cycle':'任务循环','mission_days_elapsed':'累计服役时间（天）',
 'maximum_damage':'最大累计损伤','cycle_completed':'任务完整完成',
 'sample_id':'随机路径编号','status':'状态','failure_cycle':'首次越限循环',
 'remaining_complete_cycles':'剩余完整任务次数','limiting_factors':'限制部件',
 'failure_reason':'失效原因','horizon_cycles':'预测上限循环','random_seed':'随机种子',
 'sample_count':'随机路径数','right_censored_count':'未越限路径数',
 'right_censored_fraction':'未越限路径比例','quality_grade':'整车质量等级',
 'rated_quality_grade':'额定工况质量等级','grade_causes':'降级原因','case_id':'测试工况',
 'state_label':'状态名称','state_source':'状态来源','completed':'计算完成',
 'max_tracking_error_deg':'最大液压跟踪误差（°）','rms_tracking_error_deg':'均方根跟踪误差（°）',
 'steady_tracking_error_deg':'稳态跟踪误差（°）','settling_delay_s':'整定延迟（s）',
 'maximum_cylinder_error_m':'最大缸位移误差（m）','minimum_pump_flow_margin_lpm':'最小供油流量余量（L/min）',
 'maximum_pump_demand_ratio':'最大供油需求比','minimum_supply_pressure_margin_mpa':'最小供压余量（MPa）',
 'maximum_valve_saturation_ratio':'阀命令饱和比例','peak_chamber_pressure_mpa':'腔压峰值（MPa）',
 'maximum_tracking_error_deg':'最大跟踪误差（°）','range_value':'循环载荷范围',
 'amplitude':'循环幅值','mean_value':'循环均值','count':'循环次数',
 'cycle_count':'循环次数','equivalent_load':'等效循环载荷','equivalent_exposure':'累计等效载荷',
 'sum_range_power':'范围幂次累计','start_index':'起点序号','end_index':'终点序号',
}
VALUES={**KINDS,**MODES,**IDS,
 'HEALTHY':'健康','SUBHEALTHY':'亚健康','DEGRADED':'退化','DANGEROUS':'危险',
 'SETTLED':'已满足稳定判据','FIXED_ZERO_NO_STEERING_REQUIRED':'固定零位／无需转向到位',
 'NOT_SETTLED_WITHIN_HORIZON':'未在观察期稳定','RIGHT_CENSORED':'预测上限内未越限（右删失）',
 'FAILURE_REACHED':'已检测到失效阈值','FAILURE_BRACKETED':'失效位于已验证区间',
 'NOT_REACHED_WITHIN_HORIZON':'预测范围内未达到失效阈值','INDETERMINATE':'模型或数值不足以确定',
 'ENGINEERING_DESIGN_ASSUMPTION':'工程设计假设','PENDING_CLIENT_CALIBRATION':'待甲方试验标定',
 'equivalent operating hour':'等效运行小时','equivalent shaft-load hour':'等效轴负载小时',
 'equivalent pressure-flow-cycle exposure':'等效压差流量动作载荷',
 'equivalent spool-travel cycle':'等效阀芯动作循环',
 'equivalent loaded sliding exposure':'等效受载滑动载荷',
 'equivalent sliding-plus-reversal exposure':'等效滑动与反转载荷',
 'True':'是','False':'否','None':'未记录','healthy':'全新健康状态','step':'阶跃兼容输入','ramp':'角度斜坡输入',
 'LIVE_RUN':'本次实际计算','D3_RUL_CHECKPOINT':'寿命动态检查点',
}
FIELDS.update({
 'requested_quality_checkpoint_count':'请求质量检查点数',
 'executed_quality_checkpoint_count':'已执行动态质量检查点数',
 'executed_quality_case_count':'已执行标准动态工况数',
 'quality_checkpoint_cycles':'实际动态检查点循环',
 'maximum_mode_damage':'最大模式损伤',
 'degradation_state_json':'对应二十模式退化状态', 'mode_key':'部件与模式',
 'healthy_value':'健康值','current_value':'当前值','change':'变化量',
 'last_safe_checkpoint':'最后安全循环检查点','first_exceedance_checkpoint':'首次越限循环检查点',
 'failure_mode_keys':'首次越限模式','detection_resolution':'检测时间分辨率',
 'case_count':'工况数','checkpoint_day':'检查日（天）',
 'equivalent_range':'等效载荷范围','maximum_range':'最大载荷范围',
 'stress_diagnostic_excluded':'应力诊断独立处理标志',
 '侧向加速度_mps2':'侧向加速度（m/s²）','车速_kmh':'车速（km/h）',
 'equivalent_load':'等效载荷','total_count':'循环计数','range':'载荷范围',
 'equivalent_force_range_n':'等效推力范围（N）','weighted_cycles':'加权循环数',
 'total_runtime_s':'总计算耗时（s）','deterministic_runtime_s':'确定性计算耗时（s）',
 'monte_carlo_runtime_s':'随机计算耗时（s）','failure_time_days':'首次越限时间（天）',
 'termination_basis':'寿命终止依据','initial_state':'初始状态',
 'wheel':'车轮','final_target_deg':'最终目标角（°）','final_actual_deg':'最终实际角（°）',
 'maximum_tracking_error_deg':'最大跟踪误差（°）','first_arrival_s':'指令完成后首次到位（s）',
 'whole_run_first_arrival_s':'全过程首次进入终值容差（s）','settled_time_s':'稳态建立时间（s）',
 'additional_convergence_s':'指令后额外收敛时间（s）','settled_status':'稳态状态',
 'speed_at_settling_deg_s':'稳态建立时角速度（°/s）','final_speed_deg_s':'最终角速度（°/s）',
 'final_target_m':'最终目标行程（m）','final_actual_m':'最终实际行程（m）',
 'final_error_m':'最终行程偏差（m）','speed_at_settling_m_s':'稳态建立时速度（m/s）',
 'final_velocity_m_s':'最终活塞速度（m/s）','requested_checkpoint_day':'请求检查点（天）',
 'cylinder_displacement_error_mm':'缸位移误差（mm）','pump_demand_ratio':'泵需求比',
 'minimum_available_pump_flow_lpm':'最小可用泵流量（L/min）',
 'valve_saturation_fraction':'阀命令饱和比例','peak_pressure_utilization':'峰值压力利用率',
 'peak_pressure_mpa_g':'峰值腔压（MPa）','actuator_force_utilization':'作动能力利用率',
 'peak_hydraulic_force_n':'峰值液压力（N）','tail_pressure_ripple_mpa':'稳态压力纹波（MPa）',
 'scenario_source':'场景来源','case_category':'工况类别','hydraulic_state_count':'液压状态数',
 'hydraulic_model':'液压模型编号','mechanical_mode':'机械模型编号',
 'target_path_adhesion_ratio':'目标轨迹附着利用率','adhesion_risk_excluded_from_grade':'附着风险独立报告',
 'mechanism_ackermann_error_deg':'机构几何固有偏差（°）','component_health_grade':'部件健康等级',
 'threshold_source':'阈值来源','interpretation':'解释','pressure_pa':'参考压差（Pa）',
 'temperature_c':'参考油温（℃）','cylinder_velocity_m_s':'参考活塞速度（m/s）',
})
VALUES.update({'RECORDED_CYCLE_OR_FAILURE_SEGMENT_END':'已计算循环末或失效段末',
 'simulation':'联合仿真','batch':'准稳态批量估计','degradation':'部件退化预测',
               'quality':'当前质量评估','rul':'剩余任务循环预测',
 'supply pressure':'供油压差','pump speed':'泵转速','running time':'运行时间',
 'contamination':'污染水平','temperature':'温度','working pressure':'工作压力',
 'valve pressure difference':'阀压差','throughput':'通过流量','action count':'动作次数',
 'cumulative spool travel':'阀芯累计行程','pressure-flow load':'压力流量载荷',
 'chamber pressure difference':'两腔压差','absolute sliding distance':'绝对滑动距离',
 'load level':'受载水平','load':'负载','pressure difference':'压差',
 'rainflow force reversals':'雨流载荷反转','rated':'额定工况','medium_speed':'中速工况',
 'stochastic path lifetime quantile':'随机路径寿命分位数',
})
VALUES.update({
 'specified_light':'轻度指定退化','specified_medium':'中度指定退化','specified_heavy':'重度指定退化',
 'current':'当前状态','CYCLE_END_CHECKPOINT':'循环末检查点检测',
 'standard':'标准工况','D4_REAL_22_STATE':'正式22状态动态计算',
 'FAST_BATCH_ESTIMATE':'准稳态作动能力估计（非完整动态仿真）',
 'ACKERMANN_TARGET_MISMATCH':'机构几何与阿克曼目标存在固有偏差','OK':'检查正常',
 'VEHICLE_DYNAMIC_INFEASIBLE':'目标行驶轨迹不可行（独立于液压跟踪）',
 'NON_FINITE':'非有限数值','22_STATE_SIMULATION_NOT_COMPLETED':'22状态仿真未完成',
 'ValueError':'数值或格式错误','TypeError':'参数类型错误','SpectrumError':'任务谱输入错误',
 'FileNotFoundError':'找不到文件','PermissionError':'文件访问被拒绝',
 'InterruptedError':'任务已取消','RuntimeError':'运行状态异常',
 'UnicodeDecodeError':'文件编码不匹配','JSONDecodeError':'JSON格式错误',
 'STD_L10':'额定低速左转10°','STD_L30':'额定低速左转30°',
 'STD_R10':'额定低速右转10°','STD_R30':'额定低速右转30°',
 'STD_MID_SPEED':'代表性中速转向','STD_ZERO':'直行零位',
 'gear-pair/end-face wear increases pressure-driven internal leakage':'齿轮副及端面磨损使压差驱动的内泄漏增大',
 'gear/bearing mechanical friction increases shaft loss and lowers mechanical efficiency':'齿轮及轴承机械摩擦增加轴功率损失，降低机械效率',
 'spool/sleeve contamination wear increases P-T internal leakage':'阀芯阀套污染磨损增加供油到回油的内泄漏',
 'contamination and spool friction increase first-order spool response time':'污染及阀芯摩擦以一阶响应时间常数增大表示',
 'seal sliding wear increases A-B chamber leakage':'密封滑动磨损增加两腔之间内泄漏',
 'seal/guide wear and load reversals increase Coulomb and viscous resistance':'密封导向磨损及载荷反转增加库仑和黏性摩擦',
 'D1_DAY30':'从当前任务谱生成的D1第30天初态',
 'd1_day30':'从当前任务谱生成的D1第30天初态',
})
for i in range(1,7):
    FIELDS[f'axle_mass_{i}_t']=f'第{i}桥轴荷（t）'
    for side,label in [('left','左'),('right','右')]:
        VALUES[f'axle{i}_{side}']=f'{i}桥{label}轮'

for channel,label in [('channel_front','一二桥作动组'),('channel_rear_1','四桥作动组'),
                      ('channel_rear_2','五桥作动组'),('channel_rear_3','六桥作动组')]:
    FIELDS[f'{channel}_valve_spool_state']=f'{label}实际阀芯归一化位移（无量纲）'


def cn(value):
    return _translate(str(value))


@lru_cache(maxsize=16384)
def _translate(text):
    if text.startswith('limiter_count:'):
        return '限制因素出现次数：'+cn(text[len('limiter_count:'):])
    for prefix,label in [('increment_','本循环损伤增量：'),('exposure_','等效载荷：')]:
        if text.startswith(prefix): return label+cn(text[len(prefix):])
    flat=re.fullmatch(r'(pump|valve|cylinder)_(channel_rear_[123]|channel_front|front|rear)_(leakage_wear|mechanical_loss|response_lag|friction_growth)',text)
    if flat: return cn(':'.join(flat.groups()))
    for prefix,label in [('increment:','本段损伤增量：'),('exposure:','本段等效载荷：')]:
        if text.startswith(prefix): return label+cn(text[len(prefix):])
    if len(text.split(':'))==2 and text.split(':')[0] in KINDS:
        kind,name=text.split(':')
        return IDS.get(name,name)+KINDS[kind]
    if text in FIELDS: return FIELDS[text]
    if text in VALUES: return VALUES[text]
    if ':' in text and len(text.split(':'))==3 and text.split(':')[0] in KINDS:
        kind,name,metric=text.split(':')
        return f'{IDS.get(name,name)}{KINDS[kind]}：{FIELDS.get(metric,MODES.get(metric,metric))}'
    if any(c in text for c in ('\\','/')) and ('.csv' in text or '.json' in text or ':\\' in text):
        return text
    for key in sorted({**FIELDS,**VALUES},key=len,reverse=True):
        if key in text:
            text=text.replace(key,({**FIELDS,**VALUES})[key])
    return text


def chinese_frame(frame):
    result=frame.copy()
    result.columns=[cn(c) for c in result.columns]
    for column in result.select_dtypes(include=['bool','boolean']).columns:
        result[column]=result[column].map({True:'是',False:'否'})
    for column in result.select_dtypes(include=['object','str']).columns:
        result[column]=result[column].map(lambda value:cn(value) if isinstance(value,str) else value)
    return result
