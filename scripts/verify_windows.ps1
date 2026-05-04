param(
    [switch]$Gui
)

$ErrorActionPreference = "Stop"
$Python = ".\.venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Missing .venv. Run .\scripts\setup_windows.ps1 first."
}

& $Python .\scripts\verify_handoff.py
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

if ($Gui) {
    & $Python -m photos gui
    exit $LASTEXITCODE
}
