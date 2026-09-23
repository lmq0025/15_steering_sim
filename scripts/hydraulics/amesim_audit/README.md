## R03-A2.5

只复用已验收的 A1/A2 表并生成收口衍生文件：

    & "$env:CONDA_PREFIX\python.exe" scripts/hydraulics/amesim_audit/audit_closure.py
    & "$env:CONDA_PREFIX\python.exe" -m pytest -q tests/unit/test_amesim_structure_audit.py tests/unit/test_amesim_parameter_audit.py tests/unit/test_amesim_a25_closure.py

脚本默认拒绝覆盖 A2.5 产物；只有明确复核后才可使用
`--overwrite-r03a25`。脚本不会重跑结构审计、不会修改
`qh1_1.ame`、不会生成液压机理代码。

# R03-A1 只读结构审计工具

先验证唯一正式Python环境，然后执行：

    & "$env:CONDA_PREFIX\python.exe" -c "import sys; print(sys.executable)"
    & "$env:CONDA_PREFIX\python.exe" scripts/hydraulics/amesim_audit/audit_structure.py

默认输入是项目根目录 qh1_1.ame；默认输出是
configs/hydraulics/amesim_audit。可用 --model、--output、--amesim-root
集中指定路径。已有非空输出目录会明确报错；只有显式 --overwrite 才重新生成。

    & "$env:CONDA_PREFIX\python.exe" -m pytest -q tests/unit/test_amesim_structure_audit.py

当前实现针对已验证的 AMESim 2021.1 CIR 结构；未知版本和解析失败明确报错。
端口级算法以原始线端点和COMP_PORT反向引用一致性为必要条件，不能静默猜索引。
工程类型来自版本化映射，人工类型仅限任务提供的7条确认记录。
SC_1 的实际名称从归档直接获取，未用人工答案替换。
非求解器CIRCUIT_EXTENSIONS/STICKER定义单独写入附属对象证据表，
不混入正式COMP/LINE、submodel或端口图统计。

原文件以只读方式访问，完整解包仅在raw_extract，原始文件逐项SHA256记录。
归档内EXE/DLL仅为不执行的取证副本。未经转义的叶节点表达式显式规范化，
日志保留前后文本，原始.cir不改。API import探测只在steering_sim子进程运行，
不修改安装环境、不打开原模型、不执行任何保存接口。

CSV/JSON及raw_extract包含客户模型结构，由审计目录.gitignore保护。
脚本生成的报告仅就本轮结构审计作结论，详细表格不应未经许可上传。

R03-A2继续复用已验收的raw_extract，不重跑R03-A1：

    & "$env:CONDA_PREFIX\python.exe" scripts/hydraulics/amesim_audit/audit_parameters.py
    & "$env:CONDA_PREFIX\python.exe" -m pytest -q tests/unit/test_amesim_structure_audit.py tests/unit/test_amesim_parameter_audit.py

audit_parameters.py默认拒绝覆盖已有R03-A2文件；仅修正不完整的R03-A2结果时才显式使用
--overwrite-r03a2。脚本按.param/.data、.var/.ssf的严格同行关系解析，并以Data_Path
映射回R03-A1 component_id；CIR中的GLOBALPARAM、USES_SC_GP、参数/变量exposure另层保留。
