param(
    [switch]$Gui,
    [switch]$CheckEnv,
    [switch]$SampleDryRun,
    [string]$SamplePath = "tests\fixtures\sample_media"
)

$ErrorActionPreference = "Stop"
$Python = ".\.venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Missing .venv. Run .\scripts\setup_windows.ps1 first."
}

if ($CheckEnv) {
    & $Python -m photos check-env
    exit $LASTEXITCODE
}

if ($SampleDryRun) {
    & $Python -m photos dry-run $SamplePath --db ".photos-data\sample.sqlite" --output ".photos-data\dry-run" --free-bytes 214748364800
    exit $LASTEXITCODE
}

if ($Gui) {
    & $Python -m photos gui
    exit $LASTEXITCODE
}

& $Python -m photos --help
