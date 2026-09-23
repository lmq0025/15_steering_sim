# R03-A2 AMESim 参数—初值—变量—SC_1映射审计

## 1. 任务边界

本轮仅数字化当前保存参数、初值、变量及SC_1内部映射；未实现液压方程、控制器、联合仿真或精度结论。

## 2. 原模型和完整性检查

模型：E:\15_project\qh1_1.ame。开始/结束SHA256均为7613615723973d66a7122c74956c5161f720a64b243139fe9736cb270303b767；size=87357440，mtime_ns=1780635133163901600，只读一致=True。

## 3. Python环境

sys.executable=E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe。未改PATH、未使用AMESim Python或其他Conda环境。

## 4. 参数数据来源

当前值以.cir的VALUE原文本优先；.param提供Param_Id、名称、单位和Data_Path；.data按4142行一一对应提供编译/求值后的保存值。引用不被数值覆盖，默认值仅记入notes，不与当前值混淆。

## 5. param/state/var/data结构

.param/.data各4142行；.var/.ssf各2736行；其中2229行变量具有可映射Data_Path，507行是HIDDEN/_DUMMY raw证据；.state为359行，modelinfo NUM_STATES=359、NUM_DISCRETE_STATES=57。未发现独立离散状态名称表，因此57个离散状态不冒充具名动态状态。

## 6. hydraulic_parameters.csv统计

正式参数行=4334，覆盖组件=293，有可靠单位=2966，缺单位=1368。

## 7. 参数value_type统计

{"boolean": 2, "expression": 78, "global_reference": 84, "local_reference": 44, "numeric": 3791, "string": 2, "table": 333}

## 8. 参数unit coverage

2966/4334=68.44%；'null'视为AMESim明确给出的无量纲单位，missing才是无单位证据。

## 9. global/local/reference/expression

全局引用=84，局部引用=44，表达式=78，table=333。SC父GLOBALPARAM与内部USES_SC_GP分层保留；模型级11个global因无R03-A1 component_id只保留在raw。

## 10. hydraulic_initial_states.csv统计

正式行=369；类型={"dynamic_state": 359, "initial_condition_parameter": 10}。

## 11. dynamic state区分

只有明确出现在.state的359项标为dynamic_state；仅参数名含initial但不在.state者标为initial_condition_parameter；.var中其余量标为algebraic_or_output，不把理论上可能的压力或位移自动当成state。

## 12. hydraulic_variables.csv统计

可映射变量=2371；优先级={"A": 1034, "B": 518, "N/A": 152, "C": 667}。

## 13. AMESim到Python验证通道

已绑定608条A/B候选到具体component_id、variable_id和单位；A级用于压力、流量、缸运动/力、泵速和阀开度等核心比较。

## 14. SC_1专项结构

10个实例全部进入审计；mapping行=605。外部端口使用R03-A1已验证SC_PORTS_MAP_LIST，signal端口单列signal_mapping；VALVEDYNAMICS0、HYDVORF0、FX00的内部连接和参数引用均保留。

- dirvalve_1: ext0(hydraulic,P)->two_port_node_bottom_1:port1, ext1(hydraulic,T)->two_port_node_bottom_2:port1, ext2(hydraulic,B)->two_port_node_top_3:port1, ext3(hydraulic,A)->two_port_node_top_4:port1, ext4(signal,missing)->table_fractional_spool_position:port1
- dirvalve_2: ext0(hydraulic,P)->two_port_node_bottom_1:port1, ext1(hydraulic,T)->two_port_node_bottom_2:port1, ext2(hydraulic,B)->two_port_node_top_3:port1, ext3(hydraulic,A)->two_port_node_top_4:port1, ext4(signal,missing)->table_fractional_spool_position:port1
- dirvalve_3: ext0(hydraulic,P)->two_port_node_bottom_1:port1, ext1(hydraulic,T)->two_port_node_bottom_2:port1, ext2(hydraulic,A)->two_port_node_top_3:port1, ext3(signal,missing)->table_fractional_spool_position:port1
- dirvalve_6: ext0(hydraulic,P)->two_port_node_bottom_1:port1, ext1(hydraulic,T)->two_port_node_bottom_2:port1, ext2(hydraulic,B)->two_port_node_top_3:port1, ext3(hydraulic,A)->two_port_node_top_4:port1, ext4(signal,missing)->table_fractional_spool_position:port1
- dirvalve_8: ext0(hydraulic,P)->two_port_node_bottom_1:port1, ext1(hydraulic,T)->two_port_node_bottom_2:port1, ext2(hydraulic,B)->two_port_node_top_3:port1, ext3(hydraulic,A)->two_port_node_top_4:port1, ext4(signal,missing)->table_fractional_spool_position:port1
- dirvalve_9: ext0(hydraulic,P)->two_port_node_bottom_1:port1, ext1(hydraulic,T)->two_port_node_bottom_2:port1, ext2(hydraulic,B)->two_port_node_top_3:port1, ext3(hydraulic,A)->two_port_node_top_4:port1, ext4(signal,missing)->table_fractional_spool_position:port1
- dirvalve_10: ext0(hydraulic,P)->two_port_node_bottom_1:port1, ext1(hydraulic,T)->two_port_node_bottom_2:port1, ext2(hydraulic,A)->two_port_node_top_3:port1, ext3(signal,missing)->table_fractional_spool_position:port1
- dirvalve_11: ext0(hydraulic,P)->two_port_node_bottom_1:port1, ext1(hydraulic,T)->two_port_node_bottom_2:port1, ext2(hydraulic,B)->two_port_node_top_3:port1, ext3(hydraulic,A)->two_port_node_top_4:port1, ext4(signal,missing)->table_fractional_spool_position:port1
- dirvalve_12: ext0(hydraulic,P)->two_port_node_bottom_1:port1, ext1(hydraulic,T)->two_port_node_bottom_2:port1, ext2(hydraulic,B)->two_port_node_top_3:port1, ext3(hydraulic,A)->two_port_node_top_4:port1, ext4(signal,missing)->table_fractional_spool_position:port1
- dirvalve_13: ext0(hydraulic,P)->two_port_node_bottom_1:port1, ext1(hydraulic,T)->two_port_node_bottom_2:port1, ext2(hydraulic,A)->two_port_node_top_3:port1, ext3(signal,missing)->table_fractional_spool_position:port1

P/T/A/B字母来自父SUBMODEL的显式IVAR_EXPOSED p_/q_映射：dirvalve_6/8均为ext0=P、ext1=T、ext2=B、ext3=A、ext4=signal。信号口映射到table_fractional_spool_position(FX00) port1，FX00输出连接VALVEDYNAMICS0 port1，VALVEDYNAMICS0 port0连接frac_spool_pos_node。

dirvalve_6/8的HYDVORF路径由显式exposed映射确认：orifice_13=P-B、orifice_14=P-A、orifice_24=T-A、orifice_23=T-B；每个orifice的port0接同号FX00表，液压port1/2进入内部网络。

FX00只按官方/模型元数据称为function of one variable（函数/表表达式对象），不推断额外物理方程。

## 15. 10个SC_1实例差异

逐实例比较结论：{"external_ports": "false", "internal_component_count": "false", "internal_submodel_set": "false", "parameter_names": "true", "parameter_values": "false", "valve_dynamics_parameters": "false", "flow_path_parameters": "false", "signal_source_interface": "false", "exposed_parent_parameters": "false", "dynamic_states": "true"}。同名SC_1并不代表结构和参数完全相同；4口/5口、内部组件数、流路及表达式差异均保留。

dirvalve_6与dirvalve_8的外端口、内部submodel集合、VALVEDYNAMICS0参数、HYDVORF0参数、父GLOBALPARAM和信号接口一致，但4个FX00开口表达式（table_13/14/23/24）不同，因此参数并非完全一致。

## 16. dirvalve_6 GUI Ground Truth

检查状态={'PASS': 9}。indexf=0、density=850 kg/m**3、viscosity=60 cSt来自父GLOBALPARAM；fractional spool position、P-A/P-B/T-A/T-B和valve dynamics标题均从归档独立追溯。

## 17. PU001参数审计

{'submodel': 'PU001', 'object_kind': 'COMP', 'instance_count': 4, 'instances_with_parameters': 4, 'parameter_rows': 12, 'rows_with_units': 8, 'rows_missing_units': 4, 'numeric_count': 4, 'expression_count': 0, 'reference_count': 8, 'table_curve_count': 0, 'missing_value_count': 0, 'coverage_status': 'covered', 'notes': 'Counts current saved parameters; absence can be valid for structural objects.'}；状态/变量={'submodel': 'PU001', 'instance_count': 4, 'instances_with_dynamic_states': 0, 'dynamic_state_count': 0, 'initial_condition_count': 0, 'algebraic_variable_count': 12, 'unknown_state_type_count': 0, 'coverage_status': 'covered', 'notes': 'Dynamic states come only from .state; algebraic/output count comes from .var minus .state.'}。

## 18. HJ020/HJ0022/HJ021

HJ020:参数={'submodel': 'HJ020', 'object_kind': 'COMP', 'instance_count': 3, 'instances_with_parameters': 3, 'parameter_rows': 45, 'rows_with_units': 39, 'rows_missing_units': 6, 'numeric_count': 36, 'expression_count': 0, 'reference_count': 9, 'table_curve_count': 0, 'missing_value_count': 0, 'coverage_status': 'covered', 'notes': 'Counts current saved parameters; absence can be valid for structural objects.'}, 状态/变量={'submodel': 'HJ020', 'instance_count': 3, 'instances_with_dynamic_states': 3, 'dynamic_state_count': 6, 'initial_condition_count': 3, 'algebraic_variable_count': 9, 'unknown_state_type_count': 0, 'coverage_status': 'covered', 'notes': 'Dynamic states come only from .state; algebraic/output count comes from .var minus .state.'}; HJ0022:参数={'submodel': 'HJ0022', 'object_kind': 'COMP', 'instance_count': 3, 'instances_with_parameters': 3, 'parameter_rows': 51, 'rows_with_units': 45, 'rows_missing_units': 6, 'numeric_count': 42, 'expression_count': 0, 'reference_count': 9, 'table_curve_count': 0, 'missing_value_count': 0, 'coverage_status': 'covered', 'notes': 'Counts current saved parameters; absence can be valid for structural objects.'}, 状态/变量={'submodel': 'HJ0022', 'instance_count': 3, 'instances_with_dynamic_states': 3, 'dynamic_state_count': 6, 'initial_condition_count': 3, 'algebraic_variable_count': 9, 'unknown_state_type_count': 0, 'coverage_status': 'covered', 'notes': 'Dynamic states come only from .state; algebraic/output count comes from .var minus .state.'}; HJ021:参数={'submodel': 'HJ021', 'object_kind': 'COMP', 'instance_count': 1, 'instances_with_parameters': 1, 'parameter_rows': 16, 'rows_with_units': 14, 'rows_missing_units': 2, 'numeric_count': 16, 'expression_count': 0, 'reference_count': 0, 'table_curve_count': 0, 'missing_value_count': 0, 'coverage_status': 'covered', 'notes': 'Counts current saved parameters; absence can be valid for structural objects.'}, 状态/变量={'submodel': 'HJ021', 'instance_count': 1, 'instances_with_dynamic_states': 1, 'dynamic_state_count': 2, 'initial_condition_count': 1, 'algebraic_variable_count': 3, 'unknown_state_type_count': 0, 'coverage_status': 'covered', 'notes': 'Dynamic states come only from .state; algebraic/output count comes from .var minus .state.'}

## 19. RV010/RV011/HYDPRV0

RV010:参数={'submodel': 'RV010', 'object_kind': 'COMP', 'instance_count': 3, 'instances_with_parameters': 3, 'parameter_rows': 12, 'rows_with_units': 9, 'rows_missing_units': 3, 'numeric_count': 12, 'expression_count': 0, 'reference_count': 0, 'table_curve_count': 0, 'missing_value_count': 0, 'coverage_status': 'covered', 'notes': 'Counts current saved parameters; absence can be valid for structural objects.'}, 状态/变量={'submodel': 'RV010', 'instance_count': 3, 'instances_with_dynamic_states': 0, 'dynamic_state_count': 0, 'initial_condition_count': 0, 'algebraic_variable_count': 6, 'unknown_state_type_count': 0, 'coverage_status': 'covered', 'notes': 'Dynamic states come only from .state; algebraic/output count comes from .var minus .state.'}; RV011:参数={'submodel': 'RV011', 'object_kind': 'COMP', 'instance_count': 1, 'instances_with_parameters': 1, 'parameter_rows': 5, 'rows_with_units': 4, 'rows_missing_units': 1, 'numeric_count': 5, 'expression_count': 0, 'reference_count': 0, 'table_curve_count': 0, 'missing_value_count': 0, 'coverage_status': 'covered', 'notes': 'Counts current saved parameters; absence can be valid for structural objects.'}, 状态/变量={'submodel': 'RV011', 'instance_count': 1, 'instances_with_dynamic_states': 0, 'dynamic_state_count': 0, 'initial_condition_count': 0, 'algebraic_variable_count': 2, 'unknown_state_type_count': 0, 'coverage_status': 'covered', 'notes': 'Dynamic states come only from .state; algebraic/output count comes from .var minus .state.'}; HYDPRV0:参数={'submodel': 'HYDPRV0', 'object_kind': 'COMP', 'instance_count': 3, 'instances_with_parameters': 3, 'parameter_rows': 48, 'rows_with_units': 36, 'rows_missing_units': 12, 'numeric_count': 45, 'expression_count': 0, 'reference_count': 0, 'table_curve_count': 3, 'missing_value_count': 0, 'coverage_status': 'covered', 'notes': 'Counts current saved parameters; absence can be valid for structural objects.'}, 状态/变量={'submodel': 'HYDPRV0', 'instance_count': 3, 'instances_with_dynamic_states': 0, 'dynamic_state_count': 0, 'initial_condition_count': 0, 'algebraic_variable_count': 18, 'unknown_state_type_count': 0, 'coverage_status': 'covered', 'notes': 'Dynamic states come only from .state; algebraic/output count comes from .var minus .state.'}

## 20. HA001

参数={'submodel': 'HA001', 'object_kind': 'COMP', 'instance_count': 2, 'instances_with_parameters': 2, 'parameter_rows': 12, 'rows_with_units': 8, 'rows_missing_units': 4, 'numeric_count': 12, 'expression_count': 0, 'reference_count': 0, 'table_curve_count': 0, 'missing_value_count': 0, 'coverage_status': 'covered', 'notes': 'Counts current saved parameters; absence can be valid for structural objects.'}；状态/变量={'submodel': 'HA001', 'instance_count': 2, 'instances_with_dynamic_states': 2, 'dynamic_state_count': 2, 'initial_condition_count': 2, 'algebraic_variable_count': 4, 'unknown_state_type_count': 0, 'coverage_status': 'covered', 'notes': 'Dynamic states come only from .state; algebraic/output count comes from .var minus .state.'}。

## 21. 管路/容腔模型

HL0000:参数={'submodel': 'HL0000', 'object_kind': 'LINE', 'instance_count': 12, 'instances_with_parameters': 12, 'parameter_rows': 240, 'rows_with_units': 168, 'rows_missing_units': 72, 'numeric_count': 216, 'expression_count': 0, 'reference_count': 0, 'table_curve_count': 24, 'missing_value_count': 0, 'coverage_status': 'covered', 'notes': 'Counts current saved parameters; absence can be valid for structural objects.'}, 状态/变量={'submodel': 'HL0000', 'instance_count': 12, 'instances_with_dynamic_states': 12, 'dynamic_state_count': 12, 'initial_condition_count': 0, 'algebraic_variable_count': 48, 'unknown_state_type_count': 0, 'coverage_status': 'covered', 'notes': 'Dynamic states come only from .state; algebraic/output count comes from .var minus .state.'}; HL0002:参数={'submodel': 'HL0002', 'object_kind': 'LINE', 'instance_count': 10, 'instances_with_parameters': 10, 'parameter_rows': 230, 'rows_with_units': 170, 'rows_missing_units': 60, 'numeric_count': 210, 'expression_count': 0, 'reference_count': 0, 'table_curve_count': 20, 'missing_value_count': 0, 'coverage_status': 'covered', 'notes': 'Counts current saved parameters; absence can be valid for structural objects.'}, 状态/变量={'submodel': 'HL0002', 'instance_count': 10, 'instances_with_dynamic_states': 10, 'dynamic_state_count': 10, 'initial_condition_count': 0, 'algebraic_variable_count': 80, 'unknown_state_type_count': 0, 'coverage_status': 'covered', 'notes': 'Dynamic states come only from .state; algebraic/output count comes from .var minus .state.'}; HL011:参数={'submodel': 'HL011', 'object_kind': 'LINE', 'instance_count': 6, 'instances_with_parameters': 6, 'parameter_rows': 180, 'rows_with_units': 132, 'rows_missing_units': 48, 'numeric_count': 168, 'expression_count': 0, 'reference_count': 0, 'table_curve_count': 12, 'missing_value_count': 0, 'coverage_status': 'covered', 'notes': 'Counts current saved parameters; absence can be valid for structural objects.'}, 状态/变量={'submodel': 'HL011', 'instance_count': 6, 'instances_with_dynamic_states': 6, 'dynamic_state_count': 36, 'initial_condition_count': 0, 'algebraic_variable_count': 42, 'unknown_state_type_count': 0, 'coverage_status': 'covered', 'notes': 'Dynamic states come only from .state; algebraic/output count comes from .var minus .state.'}; HL012:参数={'submodel': 'HL012', 'object_kind': 'LINE', 'instance_count': 37, 'instances_with_parameters': 37, 'parameter_rows': 1147, 'rows_with_units': 851, 'rows_missing_units': 296, 'numeric_count': 1073, 'expression_count': 0, 'reference_count': 0, 'table_curve_count': 74, 'missing_value_count': 0, 'coverage_status': 'covered', 'notes': 'Counts current saved parameters; absence can be valid for structural objects.'}, 状态/变量={'submodel': 'HL012', 'instance_count': 37, 'instances_with_dynamic_states': 37, 'dynamic_state_count': 259, 'initial_condition_count': 0, 'algebraic_variable_count': 222, 'unknown_state_type_count': 0, 'coverage_status': 'covered', 'notes': 'Dynamic states come only from .state; algebraic/output count comes from .var minus .state.'}

## 22. missing/inferred/manual

missing value=0、missing unit=1368。工程优先级是inferred；参数值、Data_Path、state和variable结构为archive confirmed；GUI仅用于Ground Truth。

## 23. 官方帮助/.spe/.c

文档索引行=92；仅记录文件存在性及定义关键字证据，不执行或完整逆向.c。SC_1为模型本地supercomponent，继续needs_manual_help_lookup。

## 24. 尚不能确认

未能从归档获得57个离散状态的逐项名称；saved_by_default来自.ssf而非结果文件实测；SC_1端口P/T/A/B已由归档IVAR_EXPOSED映射确认，但端口连接记录本身无物理流向，不能据from/to猜瞬时流向；SC_1仍没有独立官方帮助条目。

## 25. 验收建议

若专项测试、原模型结束指纹和机械冻结区检查均通过，建议R03-A2为CONDITIONAL PASS：参数、具名连续状态、变量和SC映射已可追溯，但57个离散状态缺少逐项名称，SC_1仍缺独立官方帮助定义，部分单位只可保留missing。

## 26. 对R03-B的建议

仅在项目负责人验收后，以A级通道和关键submodel参数表冻结R03-B输入；不要从本报告直接推导或实现方程。

## 最终自检

执行环境：E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe。

命令：python可执行文件的绝对路径加 -m pytest -q tests/unit/test_amesim_structure_audit.py tests/unit/test_amesim_parameter_audit.py。

结果：25 passed in 1.00s，其中R03-A1回归13项、R03-A2专项12项；原模型结束指纹一致，机械冻结区Git diff为0。
