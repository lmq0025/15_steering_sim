# R03-B1.5 派生试验清单

状态：`PREPARED — WAITING_FOR_AMESIM_EXPERIMENT_RESULTS`

两个拟建模型均为 **DERIVED TEST MODEL — NOT CUSTOMER BASELINE**：

- `R03B15_HYDVORF0_characterization.ame`
- `R03B15_HJ020_characterization.ame`

它们尚未由本轮自动生成，也没有伪造占位 `.ame` 文件。原因是本机虽存在
`AMERun.exe`、`STDSIMBatch.exe` 及官方 batch API，但在“不修改 PATH、不使用
AMESim Python、不改安装环境”的边界下，没有找到可安全创建、submodel 化并编译
新 `.ame` 模型的受支持命令行入口。必须先按人工指南在 Simcenter AMESim 2021.1
GUI 中建立并编译派生模型；之后才可评估对该派生模型使用原生 batch runner。

## 来源与完整性

- 客户健康基线：`E:\15_project\qh1_1.ame`
- 基线 SHA256：`7613615723973D66A7122C74956C5161F720A64B243139FE9736CB270303B767`
- 基线大小：`87,357,440 bytes`
- 基线 mtime (UTC)：`2026-06-05T04:52:13.1639016Z`
- AMESim：Simcenter AMESim 2021.1
- 冻结配置：`configs/hydraulics/r03b1/*.json`
- 审计来源：`configs/hydraulics/amesim_audit/r03a25_resolved_key_parameters.csv`

派生模型建成后，应在本文件追加：模型 SHA256、大小、mtime、搭建人、日期、
AMESim exact build、solver 设置与任何偏离指南之处。不得修改以上客户基线记录。

## 文件职责

- 两张 `*_experiment_matrix.csv`：唯一测试计划，含 identification/validation 冻结分组。
- `r03b15_amesim_variable_export_list.csv`：AMESim 保存变量清单。
- `results_templates/`：只含表头，不是试验结果。
- 真实导出必须另存到 `results_raw/`，不得覆盖模板或矩阵。

