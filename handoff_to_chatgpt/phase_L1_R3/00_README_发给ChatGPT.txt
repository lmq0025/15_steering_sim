请将整个 phase_L1_R3.zip 上传给 ChatGPT 审核。

关键状态：
- SC1 AREA TABLE TRANSFER = PASS
- SC1 PORT FLOW VALIDATION = CONDITIONAL (63 pass / 3 fail)
- SUPPLY ALGEBRAIC MAPPING = PASS
- ALL NODE FLOW BALANCES = PASS
- Python chamber pressure: 384.663 -> 2.065 MPa
- 独立动态指标 <=10%: 10/54
- PYTEST = 222 passed
- READY FOR L2 = NO
- READY FOR MECHANICAL INTEGRATION = NO

从 01 报告开始审阅；04–11 是映射、守恒与独立指标证据，12 是完整配对时序，source_review/ 是本轮核心实现，tests/ 是行为回归，amesim_logs/ 与 evidence/ 是隔离副本运行证据。
