# PHASE M2 交付包 — 六桥阿克曼转向纠偏与全工况覆盖

## 先读

1. `phase_M2_report.md` —— 物理正确性报告（含五、六桥反号的完整归因）
2. `results/ideal_ackermann_check.json` —— ±30° 理想阿克曼角独立校核
3. `results/linkage_audit.json` —— 四杆装配分支与可解范围审计

## 三条必须记住的结论

1. **理想阿克曼角在 ±30° 内全部可算**，本包内独立实现与 M1 的最大差
   1.865e-14°；公式与推导见报告 §1。
2. **五、六桥同桥左右轮反号不是转录错误**：甲方 Word 表 7 个点逐点核对一致，
   拓扑与两张手绘结构图一致，几何左右严格镜像。真正原因是这两桥的
   "摆臂—边拉杆—车轮"四杆机构距死点只有 9.7°/6.6°（一、二、四桥为 76~85°），
   导致单侧车轮角**只能单向偏转**。详见报告 §3。
3. **工程等效模式只在真实机构确实做不到的地方启用**（五、六桥），
   四桥仍用真实闭链；等效角一律标记 `ENGINEERING_EQUIVALENT_ACKERMANN`，
   与 `CUSTOMER_LINKAGE_GEOMETRY` 分开保存。详见报告 §4。

## 目录

```
phase_M2_report.md                物理正确性报告
results/ideal_ackermann_check.json  ±30° 理想阿克曼角校核
results/envelope_check.json        机构坐标连续延拓包络与停止原因
results/linkage_audit.json         四杆装配分支、可达范围、距死点
results/m2_summary.json            全工况表汇总
results/full_cases.csv             3111 组全工况表（66 列）
results/full_cases.xlsx            同上（XLSX）
templates/case_template.csv/.xlsx  甲方工况输入模板
source/mechanics_ackermann_v2/     修订后的机械模型与配置
source/ackermann/                  PHASE M2 新增模块
source/demo/                       演示软件改动（数值表、旧结果标注）
source/scripts/                    审计、批算与打包脚本
source/baseline_pre_m2/            M2 修改前的快照与校验和
tests/                             新增与扩充的测试
figures/<工况>/                    改进后的机械转向图与十二轮数值表
```

## 复现

```powershell
$py = 'E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe'
& $py scripts/m2/audit_axle_linkage.py
& $py scripts/m2/run_m2_batch.py --xlsx-all
& $py -m pytest -q tests/ackermann tests/demo
```
