param(
    [string]$PythonLauncher = "py",
    [string]$PythonVersion = "-3"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path ".venv")) {
    $VenvArgs = @()
    if ($PythonVersion) {
        $VenvArgs += $PythonVersion
    }
    $VenvArgs += @("-m", "venv", ".venv")
    & $PythonLauncher @VenvArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create .venv with $PythonLauncher $PythonVersion"
    }
}

.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev,gui]"

Write-Host "Windows development environment is ready."
Write-Host "Run .\scripts\check_environment.ps1 next."
