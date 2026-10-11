请将整个 phase_L1_Fast.zip 上传给 ChatGPT 审核。

最终状态：FAST ENGINEERING CANDIDATE = PASS；独立 Amesim 宏观精度 = NOT_VERIFIED。
供油模式：regulated_constant_pressure；动态状态 16；管路动态状态 0；RHS 内部 Newton 已禁用。
固定步长 2 ms 因数值误差及自主模式稳定性未采用；正式步长为 0.5 ms。
实测 100 s 动态运行时间为 68.794948 s，未达到 1 s 目标。
全仓回归测试：230 passed in 111.47 s。

复现命令：
& "E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe" .\scripts\hydraulics\run_phase_l1_fast.py
& "E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe" -m pytest -q
