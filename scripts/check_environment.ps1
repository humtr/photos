$ErrorActionPreference = "Stop"

$Python = ".\.venv\Scripts\python.exe"
if (Test-Path $Python) {
    & $Python -m photos check-env
} else {
    python .\scripts\check_environment.py
}
