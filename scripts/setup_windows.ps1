param(
    [switch]$SkipGui
)

$ErrorActionPreference = "Stop"

function Resolve-Python {
    $Candidates = @(
        @{ Exe = "py"; Args = @("-3.12") },
        @{ Exe = "py"; Args = @("-3.11") },
        @{ Exe = "py"; Args = @("-3") },
        @{ Exe = "python"; Args = @() }
    )

    foreach ($Candidate in $Candidates) {
        if (Get-Command $Candidate.Exe -ErrorAction SilentlyContinue) {
            return $Candidate
        }
    }

    throw "Python 3.11+ was not found. Install Python, reopen PowerShell, and rerun this script."
}

$Python = Resolve-Python

if (-not (Test-Path ".venv")) {
    $VenvArgs = @($Python.Args) + @("-m", "venv", ".venv")
    & $Python.Exe @VenvArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create .venv."
    }
}

.\.venv\Scripts\python.exe -m pip install --upgrade pip

if ($SkipGui) {
    .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
} else {
    .\.venv\Scripts\python.exe -m pip install -e ".[dev,gui]"
}

Write-Host "Windows development environment is ready."
Write-Host "Run .\scripts\verify_windows.ps1 next."
