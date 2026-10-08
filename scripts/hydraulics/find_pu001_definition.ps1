$AmeRoot = "E:\Simcenter\2021.1\Amesim"
$OutDir = "E:\15_project\hydraulic_audit"
$OutFile = Join-Path $OutDir "09C_PU001_file_search.txt"

"============================================================" | Out-File $OutFile -Encoding utf8
"PU001 Amesim Definition Search" | Out-File $OutFile -Append -Encoding utf8
"============================================================" | Out-File $OutFile -Append -Encoding utf8

"`n[1] FILE NAMES CONTAINING PU001" | Out-File $OutFile -Append -Encoding utf8

Get-ChildItem $AmeRoot -Recurse -File -ErrorAction SilentlyContinue |
Where-Object {
    $_.Name -match "PU001"
} |
ForEach-Object {
    $_.FullName
} |
Tee-Object -FilePath $OutFile -Append


"`n[2] TEXT FILES CONTAINING PU001" | Out-File $OutFile -Append -Encoding utf8

$extensions = @(
    ".c",
    ".h",
    ".txt",
    ".html",
    ".htm",
    ".xml",
    ".py",
    ".f",
    ".f90",
    ".sci",
    ".sub",
    ".data"
)

Get-ChildItem $AmeRoot -Recurse -File -ErrorAction SilentlyContinue |
Where-Object {
    $extensions -contains $_.Extension.ToLower()
} |
ForEach-Object {

    $file = $_

    try {
        $matches = Select-String `
            -Path $file.FullName `
            -Pattern "PU001" `
            -SimpleMatch `
            -ErrorAction SilentlyContinue

        if ($matches) {

            "`nFILE: $($file.FullName)" |
                Out-File $OutFile -Append -Encoding utf8

            foreach ($m in $matches | Select-Object -First 10) {

                "  Line $($m.LineNumber): $($m.Line.Trim())" |
                    Out-File $OutFile -Append -Encoding utf8
            }
        }
    }
    catch {
    }
}


"`n[3] LIKELY HYDRAULIC SUBMODEL DIRECTORY" |
    Out-File $OutFile -Append -Encoding utf8

$HydrPath = "E:\Simcenter\2021.1\Amesim\libhydr\submodels"

if (Test-Path $HydrPath) {

    Get-ChildItem $HydrPath -File -ErrorAction SilentlyContinue |
    Where-Object {
        $_.Name -match "PU001|PU00|pump"
    } |
    ForEach-Object {
        $_.FullName
    } |
    Out-File $OutFile -Append -Encoding utf8

}
else {

    "Directory not found: $HydrPath" |
        Out-File $OutFile -Append -Encoding utf8
}


Write-Host "============================================================"
Write-Host "PU001 SEARCH COMPLETE"
Write-Host "============================================================"
Write-Host "OUTPUT = $OutFile"