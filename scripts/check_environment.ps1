$ErrorActionPreference = "Stop"

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

$Python = ".\.venv\Scripts\python.exe"
if (Test-Path $Python) {
    Invoke-Native -FilePath $Python -Arguments @("-m", "photos", "check-env")
} else {
    Invoke-Native -FilePath "python" -Arguments @(".\scripts\check_environment.py")
}
