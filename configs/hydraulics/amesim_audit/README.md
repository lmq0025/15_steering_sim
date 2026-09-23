## R03-A2.5 收口衍生表

- `r03a25_global_parameter_resolution.csv` 保留原始 reference、目标、深度和完整解析链。
- `r03a25_scalar_variable_keys.csv` 与 `r03a25_scalar_state_keys.csv` 区分 AMESim base/group id 和唯一标量键。
- `r03a25_validation_channels_rekeyed.csv` 保留 A2 old id，并新增唯一 channel id。
- `r03a25_baseline_validation_channels.csv` 是冻结的最小正式验证集合；A2 的 608 条仍是 candidate pool。
- `r03a25_valvedynamics0_definition.csv` 与专项说明只记录官方模式证据，不实现液压方程。
- 所有 A2.5 CSV 均为现有 A1/A2 表的衍生审计结果，不覆盖旧表。

# R03-A1 审计数据字典

本目录含客户模型结构；CSV/JSON及raw_extract已由本地.gitignore防止误提交。

- component_id=外层alias/内部alias，稳定唯一；原CIRCUIT_SCOPE_ID及全局内部索引另存。
- 原始端口从0计数，与安装目录AME.py的AMEGetConnectionInformation文档一致。
- ports为JSON数组：index/type/name；COMP同时保留原始port_connect和connections。
- COMP全局索引为深度优先前序；LINE为电路前序、各电路全部LINES_LIST；全部740端点反查验证。
- PORT_CONNECT 1=直接组件引用，2=线引用，4=远程信号引用；映射经双向引用验证。
- 正式图保留所有线对象，线对象的端口0/1为START/END；from/to按稳定字典序，不代表物理流向。
- supercomponent_port_alias为父子等价端口关系；不得当作额外物理管路。
- 直接/远程双向记录仅合并镜像记录，raw保留全部证据；不得把节点当作丢失连接。
- source/confidence描述核心提取证据；工程类型的classification_source/confidence单独标记。
- group_source独立标记，front/rear没有可信映射故不推断；control_signal和supply_return仅工程分类。
- library对COMP采用COMP_LIBRARY_ID；LINE采用SUB_DIR，DIRECT缺失写missing。
- documentation_ref=available表示发现本机.spe/.c/PDF证据，不代表已读完方程帮助。
- equation_priority为后续审计优先级，不是精度判断；SC_1全部HIGH。
- 缺失submodel描述保留missing，不以图标描述填充。工程类型不参与submodel Ground Truth断言。
- hydraulic_physical_components只统计定义的液压器件类型，另报junction/fluid_property/sensor；父壳和内部器件均计数，不能解读为不重叠物理BOM。
- raw组件行=773；raw连接证据行=1386；正式图边=878；分解={'line_attachment': 740, 'direct_attachment': 81, 'supercomponent_port_alias': 47, 'remote_signal': 10}。
- r03a1_auxiliary_object_inventory.csv另存7条CIRCUIT_EXTENSIONS/STICKER定义；它们是非求解器注释标签，不计入773个COMP/LINE对象、液压物理组件或连接统计。
- XML包含未转义的&&和<表达式；只规范化单行叶节点文本并逐项记录，原归档字节完整保留。
- 未展开参数/初始状态/变量表；内部原文件只作为证据，绝不执行其中EXE/DLL。

## R03-A2 参数、初值与变量

- hydraulic_parameters.csv：当前正式参数；CIR原始VALUE优先，表达式/引用不以data求值结果覆盖。
- hydraulic_initial_states.csv：只有.state明确列出的项标为dynamic_state；名称明确含initial但不在.state者单列initial_condition_parameter。
- hydraulic_variables.csv：.var/.ssf具名变量加SC_1的IVAR_EXPOSED父级接口；HIDDEN/_DUMMY仅保留raw。
- r03a2_raw_parameters.csv：.param/.data逐行证据、SC父GLOBALPARAM、模型global及父级exposed参数。
- r03a2_raw_states.csv：359条.state原始记录及其初值参数匹配。
- r03a2_raw_variables.csv：2736条.var/.ssf记录及142条SC父级IVAR_EXPOSED记录。
- r03a2_sc1_mapping.csv：端口、P/T/A/B、signal、parent/internal参数、变量和关键内部连接映射。
- value=missing不代表raw丢失；表达式、reference和table保留在raw_value。
- null表示AMESim明确的无量纲单位；missing表示没有可靠单位证据。
- 57个离散状态只有modelinfo总数，缺少逐项名称，不构造虚假state行。
