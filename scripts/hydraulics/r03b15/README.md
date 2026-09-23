# R03-B1.5 结果分析工具

使用唯一正式环境：

```powershell
& "E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe" scripts/hydraulics/r03b15/analyze_hydvorf.py <AMESim-HYDVORF0-CSV>
& "E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe" scripts/hydraulics/r03b15/analyze_hj020.py <AMESim-HJ020-CSV>
```

脚本会严格核对 schema、test_id、identification/validation 分离和量纲列；结果不完整时
明确失败。生成的候选关系标为 `DIAGNOSTIC_ONLY_NOT_APPROVED_FOR_R03B1`，不会自动
修改 `HYDVORF0.flow()` 或 `HJ020Cylinder.rhs()`。

