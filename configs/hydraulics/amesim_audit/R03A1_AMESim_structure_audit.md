# R03-A1 AMESim 全模型结构审计

## 目的与只读保护

仅回答对象清单、当前实际submodel、端口级连接；未开发液压机理、控制或联合求解。

原模型：E:\15_project\qh1_1.ame。SHA256：7613615723973d66a7122c74956c5161f720a64b243139fe9736cb270303b767。

以rb方式打开归档；解包文件仅写入本目录raw_extract；不启动归档EXE/DLL，不调用模型保存、不修改原文件属性；前后SHA256/大小/mtime核对记录于manifest。

## 环境与Git

sys.executable=E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe。初始CONDA_PREFIX为空，暂停Python后显式指定已知steering_sim再验证。

初始分支=r02-mechanical-demo-entry；HEAD=7d4ec43d3e727627b33668ff02287860d6dca4bb。

任务开始前工作区clean；没有commit/merge/reset/clean，机械src与人工演示均未修改。

## 技术路线与官方API调查

安装目录：E:\Simcenter\2021.1\Amesim。

官方AME.py包含AMEGetComponentsAndLines、AMEGetSubmodelInfos、AMEGetConnectionInformation、AMEGetNumberOfPorts；明确区分当前submodel与AMEListAvailableSubmodels兼容列表。

ame_apy在本项目Python3.11环境中导入失败（DLL初始化失败），未能成功使用Circuit API查询。安装树存在Python3.6痕迹，版本适配问题尚未单独定位；不改变环境或安装文件。

因此采用internal archive路线：TAR归档内当前.cir、直接SUBMODEL/SUB_NAME及SUB_LABEL；官方安装.spe/.c可用性作为后续文档索引。API探测完整stderr见manifest。

归档成员数=103；活动circuit=qh1_1_.cir；XML叶节点显式规范化=723处；raw保持原字节。

## 全模型统计

- total_objects：773

- COMP_objects：403

- LINE_objects：370

- top_level_objects：462

- nested_objects：311

- supercomponents：10

- distinct_submodels：47

- hydraulic_physical_components：177

- signal_control：111

- mechanical_boundary：18

- junction_node：159

- unknown：0

- missing_submodel：0

- missing_library：305

- missing_description：10

- inferred_classifications：766

- manual_classifications：7

- unknown_group：511

对象包括COMP与LINE，并递归进入全部10个supercomponent。全结构对象共出现47种submodel标识，其中42种属于COMP对象、5种属于LINE对象；这不是截图图标数，也不是去重BOM。

missing_library=305全部对应object_kind=LINE、submodel=DIRECT；COMP对象的library missing=0。因此该数字不表示有305个液压元件缺失library。

hydraulic_physical_components=177按提取器中的液压工程类型集合统计：包含112个COMP液压器件，以及65个被分类为volume_line的LINE对象（HL0000、HL0002、HL011、HL012）；排除fluid_property、sensor_measurement、signal_control、mechanical_boundary、junction_node和305个LINE/DIRECT对象。父supercomponent壳和内部液压器件可能同时计数，因此177不是去重后的物理BOM。

另保留7条`CIRCUIT_EXTENSIONS/STICKER`工厂注释标签作为附属对象证据，见`r03a1_auxiliary_object_inventory.csv`。它们不是AMESim求解组件，不计入773个结构对象、47种submodel、177个液压物理组件或878条连接统计。

## 当前submodel清单

- CONS00：15

- CV010：6

- CV012：1

- DIRECT：305

- FORC：6

- FP04：1

- FX00：38

- GRAV0：1

- H3NODE1：59

- H3NODE2：2

- H3NODE3：14

- H4NODE1：2

- H4NODE4：4

- HA001：2

- HJ0022：3

- HJ020：3

- HJ021：1

- HL0000：12

- HL0002：10

- HL011：6

- HL012：37

- HN222A：37

- HYDCONSHTL0：6

- HYDORF0：7

- HYDORT0：8

- HYDPG0：1

- HYDPRV0：3

- HYDVORF0：43

- JUN3P：4

- MAS001：1

- MAS004：6

- PM000：4

- PU001：4

- PV00022：6

- RV010：3

- RV011：1

- SC_1：10

- SIGRECEI0：10

- SIGTRANS0：10

- SIN0：9

- SPLT0：37

- SSINK：10

- STEP0：2

- TFFD04：1

- TK000：5

- UD00：7

- VALVEDYNAMICS0：10

## 连接质量与分组

- connections：878

- hydraulic_connections：554

- signal_connections：290

- mechanical_connections：34

- other_connections：0

- unknown_connections：0

- dangling_connections：0

- unconnected_object_ports：0

- unknown_ports：0

- references_to_missing_components：0

- duplicate_connections：0

- unsupported_records：0

关系分解：{'line_attachment': 740, 'direct_attachment': 81, 'supercomponent_port_alias': 47, 'remote_signal': 10}。

所有370条线的740个端点同时验证COMP_PORT反向引用；直接/远程引用也需双向一致。47个父壳端口根据线端点别名映射到内部端口，并对照SC_PORTS_MAP_LIST覆盖。from/to只表示稳定排序；不能据此推断流向。hflow/signal/remote/lshaft/rshaft按原端口类型区分。

前桥/后桥没有显式可靠标签，保留unknown；未依据截图位置或机械对象猜测对应桥号。

## GUI Ground Truth

- dirvalve_6：SC_1 / 提取SC_1 → PASS

- dirvalve_8：SC_1 / 提取SC_1 → PASS

- shuttle_control_1：HYDCONSHTL0 / 提取HYDCONSHTL0 → PASS

- actuator001：HJ020 / 提取HJ020 → PASS

- presscontrol01_1：RV010 / 提取RV010 → PASS

- accumulator：HA001 / 提取HA001 → PASS

- dirvalve_1_piecewiselinear_6：UD00 / 提取UD00 → PASS

类型采用用户人工确认字段，classification_source=gui_manual、manual_confirmed；7条submodel都由归档独立读取，没有用Ground Truth覆盖。

## missing / inferred / manual

分类推断766行、人工类型7行；missing library=305、missing description=10、unknown group=511、unknown element_type=0。

完整逐项清单可按正式CSV对应列筛选；原始字段均为ame_internal/confirmed，仅说明模型保存的结构事实，不说明工程分类已由客户验收。

缺失submodel描述的对象：dirvalve_1, dirvalve_2, dirvalve_6, dirvalve_3, dirvalve_8, dirvalve_9, dirvalve_10, dirvalve_11, dirvalve_12, dirvalve_13

## SC_1

已确认10个局部supercomponent使用SC_1，dirvalve_6/8均通过检查；后两者各具有4个hflow端口和1个signal端口，内部对象及线路已逐层保留。归档含可审计内部HYDVORF0、FX00、VALVEDYNAMICS0等组成；各SC_1实例结构未必相同。

SUB_LABEL/SUB_DIR缺失，完整方程与独立官方帮助尚未确认，documentation_ref=needs_manual_help_lookup、equation_priority=HIGH；绝不直接等同标准四通阀公式。

## 下一阶段 R03-A2

逐实例核对SC_1内部连接、端口映射及公开参数关联；查询所选子模型的安装.spe/.c及官方帮助，再决定参数/初始状态/变量审计范围；请客户确认前后桥分组与物理接口。本轮不解析或建立完整参数、状态、变量CSV。

## 验收

审计工具专项自检：`13 passed`（仅测试R03-A1审计工具；未修改或重跑机械测试）。CSV schema、原模型指纹、端点完整性、重复边、Ground Truth及附属注释隔离均纳入检查。

结构审计判定：PASS（以前后原模型哈希一致为最终前提，见manifest）。

此结论仅为R03-A1结构审计，不表示液压模型实现、动态精度或AMESim到Python重构已经完成。
