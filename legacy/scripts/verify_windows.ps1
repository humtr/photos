param(
    [switch]$Gui
)

$ErrorActionPreference = "Stop"
$Python = ".\.venv\Scripts\python.exe"

function Invoke-Native {
    param(
        [string]$FilePath,
        [string[]]$Arguments = @()
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE`: $FilePath $($Arguments -join ' ')"
    }
}

if (-not (Test-Path $Python)) {
    throw "Missing .venv. Run .\scripts\setup_windows.ps1 first."
}

Invoke-Native -FilePath $Python -Arguments @(".\scripts\verify_handoff.py")

if ($Gui) {
    Invoke-Native -FilePath $Python -Arguments @("-m", "photos", "gui")
    exit 0
}
