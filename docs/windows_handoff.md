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
.\scripts\run_windows.ps1 --check-env
.\scripts\run_windows.ps1 --sample-dry-run
.\scripts\run_windows.ps1 --gui
```

The GUI command launches a scaffold window when PySide6 is installed. Real
Windows UI performance is not validated by Termux tests.

## Windows-Only Validation Checklist

- Confirm paths such as `D:\Photos` are accepted in dry-run mode.
- Confirm FFmpeg and ExifTool are found on `PATH`.
- Confirm at least one RAW tool candidate is installed or document the missing
  tool.
- Run a sample dry run on a copied sample folder, not the real 4 TB drive.
- Confirm the SQLite database and deletion manifest are written to the intended
  workspace.
- Confirm no file is deleted or moved during dry-run commands.
- Only after separate approval, run any real-drive scan in read-only mode first.

## Known Handoff Boundary

Termux verification covers the safety core and sample dry-run behavior. Windows
must still validate real PySide6 rendering, external tool installation
differences, real RAW conversion quality, large-drive throughput, Windows file
locking, long paths, and drive permissions.
