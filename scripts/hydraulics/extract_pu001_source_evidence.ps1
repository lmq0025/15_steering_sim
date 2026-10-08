$Source = "E:\Simcenter\2021.1\Amesim\libhydr\submodels\PU001.c"
$Spe    = "E:\Simcenter\2021.1\Amesim\libhydr\submodels\PU001.spe"

$OutDir = "E:\15_project\hydraulic_audit"

$OutC = Join-Path $OutDir "09D_PU001_source_excerpt.txt"
$OutSpe = Join-Path $OutDir "09E_PU001_spe_excerpt.txt"


# ============================================================
# 1. 检查文件
# ============================================================

Write-Host "============================================================"
Write-Host "PU001 SOURCE EVIDENCE EXTRACTION"
Write-Host "============================================================"

if (-not (Test-Path $Source)) {
    Write-Host "ERROR: PU001.c not found"
    Write-Host $Source
    exit 1
}

if (-not (Test-Path $Spe)) {
    Write-Host "WARNING: PU001.spe not found"
}


# ============================================================
# 2. 读取 PU001.c
# ============================================================

$lines = Get-Content $Source


# ============================================================
# 3. 写完整关键片段
#
# 我们已经知道：
# init function 在大约 line 88
# main calculation function 在大约 line 183
#
# 为避免漏掉公式上下文，分别扩大范围。
# ============================================================

"============================================================" |
    Out-File $OutC -Encoding utf8

"PU001.c SOURCE EVIDENCE" |
    Out-File $OutC -Append -Encoding utf8

"FILE: $Source" |
    Out-File $OutC -Append -Encoding utf8

"============================================================" |
    Out-File $OutC -Append -Encoding utf8


"`n===== HEADER / DESCRIPTION / PARAMETERS =====" |
    Out-File $OutC -Append -Encoding utf8


$start = 1
$end = [Math]::Min(180, $lines.Count)

for ($i = $start; $i -le $end; $i++) {

    "{0,5}: {1}" -f $i, $lines[$i - 1] |
        Out-File $OutC -Append -Encoding utf8
}


"`n===== MAIN COMPUTATION =====" |
    Out-File $OutC -Append -Encoding utf8


$start = 181
$end = [Math]::Min(320, $lines.Count)

for ($i = $start; $i -le $end; $i++) {

    "{0,5}: {1}" -f $i, $lines[$i - 1] |
        Out-File $OutC -Append -Encoding utf8
}


# ============================================================
# 4. 搜索关键物理变量和计算语句
# ============================================================

"`n===== KEYWORD MATCHES =====" |
    Out-File $OutC -Append -Encoding utf8


$patterns = @(
    "displ",
    "wtyp",
    "qin",
    "qout",
    "pin",
    "pout",
    "torque",
    "speed",
    "rp[",
    "ip[",
    "PI",
    "2.0",
    "60",
    "1000",
    "1e",
    "pow",
    "eff",
    "loss",
    "leak"
)


foreach ($pattern in $patterns) {

    "`n--- $pattern ---" |
        Out-File $OutC -Append -Encoding utf8

    Select-String `
        -Path $Source `
        -Pattern $pattern `
        -SimpleMatch `
        -ErrorAction SilentlyContinue |
    ForEach-Object {

        "Line $($_.LineNumber): $($_.Line.Trim())" |
            Out-File $OutC -Append -Encoding utf8
    }
}


# ============================================================
# 5. 读取 .spe
# ============================================================

if (Test-Path $Spe) {

    $speLines = Get-Content $Spe

    "============================================================" |
        Out-File $OutSpe -Encoding utf8

    "PU001.spe EVIDENCE" |
        Out-File $OutSpe -Append -Encoding utf8

    "FILE: $Spe" |
        Out-File $OutSpe -Append -Encoding utf8

    "============================================================" |
        Out-File $OutSpe -Append -Encoding utf8

    for ($i = 1; $i -le $speLines.Count; $i++) {

        "{0,5}: {1}" -f $i, $speLines[$i - 1] |
            Out-File $OutSpe -Append -Encoding utf8
    }
}


# ============================================================
# 6. 控制台直接打印最关键匹配
# ============================================================

Write-Host ""
Write-Host "===== KEY PHYSICAL LINES ====="

Select-String `
    -Path $Source `
    -Pattern "displ|qout|qin|torque|speed|pin|pout|wtyp" |
ForEach-Object {

    Write-Host (
        "Line {0}: {1}" -f
        $_.LineNumber,
        $_.Line.Trim()
    )
}


Write-Host ""
Write-Host "============================================================"
Write-Host "EXTRACTION COMPLETE"
Write-Host "============================================================"

Write-Host "C SOURCE REPORT = $OutC"
Write-Host "SPE REPORT      = $OutSpe"