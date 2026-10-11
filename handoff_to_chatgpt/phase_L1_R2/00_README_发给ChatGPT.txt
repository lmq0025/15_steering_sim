PHASE L1-R2 审核包

将整个 phase_L1_R2.zip 上传给 ChatGPT。

结论：Amesim S0/S1/S2 已恢复并安全运行，但 44 个独立宏观动态量中 0 个达到 10%；供油测点/路径与 SC_1 宏观孔口映射尚不可信。不得把泵流量参数转移、S0 的 R_eq 标定点或规定机械运动当作独立验证。

受保护模型未修改；SHA-256 见报告和 JSON。动态状态 16，管路状态 0。L2 标定和机械集成都未就绪。

复现命令见 reproduction_commands.txt。核心代码在 source_review，测试在 tests，原始 Amesim API 日志在 amesim_logs。
