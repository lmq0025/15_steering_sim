# R03-B1.5 试验准备报告

## 结论

AMESim 自动化能力判定为 **PARTIAL**。本机确认存在 `AMERun.exe`、标准 batch/run
工具及官方 Python batch API；但批准环境中的官方 Python DLL 初始化已知不可用，且
任务禁止 AMESim Python、PATH 修改和安装环境变更。没有发现可在这些约束下从零安全
创建、submodel 化、编译两个派生 `.ame` 的受支持 CLI。因此不伪造运行结果，转入
`MANUAL BUILD/RUN + AUTOMATED IMPORT/ANALYSIS`。

已完成：346 点 HYDVORF0 矩阵（216/130）、186 点 HJ020 矩阵、独立集合冻结、变量
导出表、空结果模板、逐步 GUI 指南、分析脚本与测试。`results_templates` 只有表头，
绝不计为 AMESim 观测。

## 自动化证据边界

安装目录只读调查确认 `PS00`、`QS00`、`Q000`、`VELC02`、`V001` 官方 submodel 标签；
未修改 `.spe/.c`。对命令行程序的 `-h` 探测只弹出 Invalid arguments，已关闭进程；
没有加载客户模型、没有保存模型、没有运行未知 DLL。

## 当前阻塞

需项目负责人按指南完成两个派生模型并导出真实 CSV。导回后分析器才能冻结 observed
behavior、候选关系及 validation error。此前 HYDVORF0.flow 与 HJ020.rhs 保持原状。

