# Photo Organizer v2 Release Notes

## Development Launch

Run GUI directly:

```powershell
python -m photos.app --db .photos-data\photos.sqlite
```

Or use helper script:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_gui.ps1
```

## Smoke Check (Headless)

```powershell
python -m photos.app --smoke --db .test-tmp\release-smoke.sqlite
```

Expected: JSON with `"ok": true` and `"command": "gui-smoke"`.

## Deterministic Compile Check (Windows)

Use this instead of a shell glob so file order and expansion are deterministic:

```powershell
Get-ChildItem -Path src\photos -Filter *.py -File | Sort-Object FullName | ForEach-Object { python -m py_compile $_.FullName }
```

## Windows Packaging

Build portable executable with PyInstaller:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\package_windows.ps1
```

Default output path:

- `dist\PhotoOrganizerV2\PhotoOrganizerV2.exe`

## Packaging Acceptance

- Executable launches GUI without requiring user to run Python commands.
- Source/archive root can be changed after startup.
- Smoke command still passes in the same workspace.
- Packaging script preflight-compiles `src\photos\*.py` and packages `src\photos\app.py`.
