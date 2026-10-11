# PHASE M1 六桥机械阿克曼模型

本目录是独立的机械计算层，不导入或修改 `hydraulics_lumped`、PID、电液联合、退化或寿命模块。

模型复用 R02B 冻结的甲方铰点坐标和刚性闭链求解器。坐标只表示绕 z 轴旋转副的中心位置，绝不是允许转角范围。M1 拓扑锁止三桥，只保留 `q_front`、`q4`、`q5`、`q6` 四个机构自由度；一二桥仍由真实纵拉杆共同求解。

运行默认全工况：

```powershell
& 'E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe' -m mechanics_ackermann_v2.run_phase_m1
```

自定义 CSV/XLSX 工况：

```powershell
& 'E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe' -m mechanics_ackermann_v2.run_phase_m1 --cases path\to\cases.xlsx
```

甲方真实数据：`mechanical_model_input_spec_v1.0.yaml` 中的硬点、杆件拓扑与由硬点导出的杆长；三桥第 20 点 `(-7290,-996) mm`；四至六桥缸安装点。

公开理论：共同 ICR/Ackermann、稳态侧向力平衡与横摆力矩平衡、线性侧偏刚度加 `mu Fz` 饱和、K&C 柔度思想、低速原地转向阻力的量级与速度分区。

工程假设：轮胎侧偏刚度、有效拖距、原地转向等效半径、速度过渡函数、四个机构等效转向刚度，以及因缺少前桥液压缸硬点而设置的前缸行程接口比例。所有这些参数均在 `config.json` 和输出 `model_parameters.csv` 中标记为 `ASSUMED_ENGINEERING_PARAMETER`，不是甲方实测值。

交付包中的 `reused_r02b_source` 是本模型实际复用的 R02B 机械闭链和基础类源码副本；`audit_sources` 保存 R02B、R02D、R02E 交接记录，便于复核。它们未在 M1 中修改。
