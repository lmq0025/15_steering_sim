# R03-B1 配置

本目录三个 JSON 文件由以下命令从冻结审计表生成：

```powershell
& "$env:CONDA_PREFIX\python.exe" scripts/hydraulics/generate_r03b1_config.py
```

生成器读取 `configs/hydraulics/amesim_audit/r03a25_resolved_key_parameters.csv` 和 `hydraulic_parameters.csv`。JSON 中的 `provenance` 是必填项；不得在液压组件类内复制这些模型参数。

当前配置只覆盖 `dirvalve_6 / SC_1`、`actuator001 / HJ020` 与 fluid index 0 对应的 `FP04`。它不是整个 AMESim 网络的配置。

