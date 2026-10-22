$ErrorActionPreference = 'Stop'
$PythonExe = 'E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location -LiteralPath $Root
& $PythonExe -m PyInstaller --noconfirm --clean --windowed `
  --name SteeringQualityPredictor `
  --paths "$Root\src" --paths $Root `
  --collect-all pyqtgraph `
  --add-data "src\steering_sim\desktop\assets;steering_sim\desktop\assets" `
  --add-data "configs;configs" --add-data "data\degradation;data\degradation" `
  --add-data "mechanics_ackermann_v2;mechanics_ackermann_v2" `
  --add-data "mechanics_ackermann_redesigned;mechanics_ackermann_redesigned" `
  --add-data "mechanical_model_input_spec_v1.0.yaml;." `
  "$Root\src\steering_sim\desktop\app.py"
Write-Host '构建完成：dist\SteeringQualityPredictor\SteeringQualityPredictor.exe'
