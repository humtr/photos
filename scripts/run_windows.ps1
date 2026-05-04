param(
    [switch]$Gui,
    [switch]$CheckEnv,
    [switch]$SampleDryRun,
    [string]$SamplePath = "tests\fixtures\sample_media"
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

if ($CheckEnv) {
    Invoke-Native -FilePath $Python -Arguments @("-m", "photos", "check-env")
    exit 0
}

if ($SampleDryRun) {
    Invoke-Native -FilePath $Python -Arguments @(
        "-m",
        "photos",
        "dry-run",
        $SamplePath,
        "--db",
        ".photos-data\sample.sqlite",
        "--output",
        ".photos-data\dry-run",
        "--free-bytes",
        "214748364800"
    )
    exit 0
}

if ($Gui) {
    Invoke-Native -FilePath $Python -Arguments @("-m", "photos", "gui")
    exit 0
}

Invoke-Native -FilePath $Python -Arguments @("-m", "photos", "--help")
