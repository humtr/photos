param(
    [switch]$Gui,
    [switch]$CheckEnv,
    [switch]$SampleDryRun,
    [string]$AnalyzeRoot = "",
    [string]$AnalyzeOutput = ".photos-data\analyze",
    [switch]$SkipHash,
    [switch]$Hash,
    [int]$HashMaxFiles = 0,
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

if ($AnalyzeRoot -ne "") {
    $Arguments = @(
        "-m",
        "photos",
        "analyze",
        $AnalyzeRoot,
        "--db",
        ".photos-data\photos.sqlite",
        "--output",
        $AnalyzeOutput
    )
    if ($SkipHash) {
        $Arguments += "--skip-hash"
    }
    Invoke-Native -FilePath $Python -Arguments $Arguments
    exit 0
}

if ($Hash) {
    $Arguments = @(
        "-m",
        "photos",
        "hash",
        "--db",
        ".photos-data\photos.sqlite"
    )
    if ($HashMaxFiles -gt 0) {
        $Arguments += @("--max-files", "$HashMaxFiles")
    }
    Invoke-Native -FilePath $Python -Arguments $Arguments
    exit 0
}

if ($Gui) {
    Invoke-Native -FilePath $Python -Arguments @("-m", "photos", "gui")
    exit 0
}

Invoke-Native -FilePath $Python -Arguments @("-m", "photos", "--help")
