$AmeRoot = "E:\Simcenter\2021.1\Amesim"
$OutFile = "E:\15_project\hydraulic_audit\09F_q0top_definition_search.txt"

"============================================================" |
    Out-File $OutFile -Encoding utf8

"q0top FUNCTION SEARCH" |
    Out-File $OutFile -Append -Encoding utf8

"============================================================" |
    Out-File $OutFile -Append -Encoding utf8


Write-Host "Searching q0top definition..."


$extensions = @(
    ".c",
    ".h",
    ".cpp",
    ".f",
    ".f90",
    ".txt",
    ".py"
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
            -Pattern "q0top" `
            -SimpleMatch `
            -ErrorAction SilentlyContinue

        if ($matches) {

            "`n============================================================" |
                Out-File $OutFile -Append -Encoding utf8

            "FILE: $($file.FullName)" |
                Out-File $OutFile -Append -Encoding utf8

            foreach ($m in $matches) {

                "Line $($m.LineNumber): $($m.Line.Trim())" |
                    Out-File $OutFile -Append -Encoding utf8
            }
        }
    }
    catch {
    }
}


Write-Host ""
Write-Host "============================================================"
Write-Host "SEARCH COMPLETE"
Write-Host "============================================================"
Write-Host "OUTPUT = $OutFile"