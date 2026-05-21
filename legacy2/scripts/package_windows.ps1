param(
    [string]$Name = "PhotoOrganizerV2",
    [string]$Entry = "src/photos/app.py",
    [string]$DistDir = "dist",
    [string]$BuildDir = "build"
)

$ErrorActionPreference = "Stop"

Get-ChildItem -Path "src/photos" -Filter "*.py" -File |
  Sort-Object FullName |
  ForEach-Object { python -m py_compile $_.FullName }

python -m pip install --upgrade pip
python -m pip install pyinstaller

python -m PyInstaller `
  --name $Name `
  --noconsole `
  --clean `
  --distpath $DistDir `
  --workpath $BuildDir `
  --paths src `
  $Entry

Write-Host "Packaged executable: $DistDir\\$Name\\$Name.exe"
