# Windows Handoff

This document separates code transfer from Windows-only validation. GitHub is
the code handoff path; it does not prove that external media tools, GUI
performance, or a real 4 TB drive workflow are ready.

## Clone

```powershell
git clone git@github.com:humetro15445005/photos.git
cd photos
```

If SSH is not configured on Windows, use the HTTPS repo URL from GitHub instead.

## Setup

```powershell
.\scripts\setup_windows.ps1
```

The setup script creates `.venv`, upgrades `pip`, and installs the project with
the `gui` and `dev` extras.

If script execution is blocked on a fresh Windows machine, use a process-scoped
policy for the current terminal:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

The setup script tries Python 3.12, 3.11, 3.13, the generic `py -3`, and then
`python`. It only accepts Python 3.11 or newer. Python 3.12/3.11 are preferred
for the Windows GUI scaffold because desktop dependency wheels tend to be most
predictable there. If none are found, install Python 3.11 or newer from
python.org or the Microsoft Store, reopen PowerShell, and rerun setup.

If PySide6 installation blocks initial setup, validate the core first:

```powershell
.\scripts\setup_windows.ps1 -SkipGui
.\scripts\verify_windows.ps1
```

The GUI scaffold can be tested later after installing the `gui` extra.

## Environment Check

```powershell
.\scripts\check_environment.ps1
```

The check reports:

- Python version
- Git availability
- FFmpeg availability
- ExifTool availability
- RAW tool candidates
- PySide6 import status

Missing tools are expected on a fresh machine. Install them, rerun the check,
and keep the report with later validation notes.

## Run

```powershell
.\scripts\run_windows.ps1 -CheckEnv
.\scripts\run_windows.ps1 -SampleDryRun
.\scripts\run_windows.ps1 -AnalyzeRoot "D:\Photos" -AnalyzeOutput ".photos-data\real-drive-first-pass" -SkipHash
.\scripts\run_windows.ps1 -Hash -HashMaxFiles 1000
.\scripts\run_windows.ps1 -Gui
.\scripts\verify_windows.ps1
```

The GUI command launches a scaffold window when PySide6 is installed. Real
Windows UI performance is not validated by Termux tests.

Use `-SkipHash` for the first real-drive inventory so the app can surface media
counts, folder pressure, RAW/JPG pairing candidates, likely non-person images,
and videos before spending time hashing 4 TB of data. Remove `-SkipHash` for
the exact duplicate pass; hashing is incremental because already-hashed files
remain recorded in SQLite.

Use `-HashMaxFiles` for a bounded hash batch on the first real run. Rerun
`.\scripts\run_windows.ps1 -Hash` to continue until the file-management report
shows `scan_health.hash_backlog.count` is `0`.

`verify_windows.ps1` runs the same safety-core checks expected after handoff:
unit tests, environment report, sample dry run, manifest inspection,
file-management report inspection, review package inspection, and a
non-destructive safety assertion.

## Review Package Workflow

`photos analyze` writes a `review_package` folder under the selected output
directory. It contains:

- `decisions_template.csv` for keep/delete/defer notes.
- Per-queue CSVs for exact duplicates, RAW/JPG pairs, RAW files without JPG,
  likely non-person images, and videos.
- Windows `.url` shortcuts for a bounded number of items per queue, so Explorer
  can open candidates without copying large media files.

After editing the `decision` column, import decisions and write a non-destructive
delete manifest:

```powershell
.\.venv\Scripts\python.exe -m photos import-decisions ".photos-data\real-drive-first-pass\review_package\decisions_template.csv"
.\.venv\Scripts\python.exe -m photos decision-manifest --output ".photos-data\decision_manifest.json"
```

The manifest is evidence for review. It does not delete files.

## Windows-Only Validation Checklist

- Check the GitHub Actions `Windows CI` workflow after each push to `main`.
  It runs `setup_windows.ps1 -SkipGui`, `verify_windows.ps1`, the installed
  CLI, sample dry run, and report generation on `windows-latest`.
- Confirm paths such as `D:\Photos` are accepted in dry-run mode.
- Confirm FFmpeg and ExifTool are found on `PATH`.
- Confirm at least one RAW tool candidate is installed or document the missing
  tool.
- Run a sample dry run on a copied sample folder, not the real 4 TB drive.
- Confirm the SQLite database and deletion manifest are written to the intended
  workspace.
- Confirm `scan_health.hash_backlog.count` reaches `0` before trusting exact
  duplicate results.
- Confirm the review package contains `decisions_template.csv` and per-queue
  CSVs before using it for real decisions.
- Confirm no file is deleted or moved during dry-run commands.
- Save the output of `.\scripts\verify_windows.ps1` with the validation notes.
- Only after separate approval, run any real-drive scan in read-only mode first.

## Known Handoff Boundary

Termux verification covers the safety core and sample dry-run behavior. Windows
must still validate real PySide6 rendering, external tool installation
differences, real RAW conversion quality, large-drive throughput, Windows file
locking, long paths, and drive permissions.
