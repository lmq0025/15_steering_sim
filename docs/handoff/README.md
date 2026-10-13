# Codex 交接附加资料（由脚本从活代码生成）

本目录下的三份机器可读资料由 `scripts/handoff/build_handoff_pack.py` 用
`ast` 从**当前源码**提取，不是手抄，可作为接口的唯一权威来源：

| 文件 | 内容 |
|---|---|
| `codex_interface_map.json` | 关键模块的类/方法/字段签名、配置键、液压状态布局、机械映射、时间序列列名 |
| `degradation_interface_audit.csv` | 退化参数逐个的作用点、源码行号、作用范围、是否真正进入动力学 |
| `degradation_feature_sources.csv` | 退化驱动特征在现有模型里的来源，并显式标出缺口 |
| `codex_handoff_baseline.json` | J1-R2 正式基线的实测数字（61 角、液压选型、3111 批算、18 工况动态、步长收敛、状态块） |

接口清单中：

* 关键模块数：19
* 配置键组数：4
* 液压状态维度：22（每通道 5）
* 时间序列列数：230
* 退化参数审计行数：18
