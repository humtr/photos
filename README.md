# photos

`photos` is a safety-first media triage project. The current target is a
Termux-verified core plus a Windows-handoff-ready v1 scaffold, not a claim that
Windows GUI performance, RAW color quality, or a real 4 TB drive run have been
fully validated from Termux.

## What v1 Does

- Index sample photos, RAW files, and videos into SQLite.
- Detect exact duplicates by SHA-256.
- Pair RAW and JPG files by folder and basename.
- Plan RAW-to-archival-JPG work and record validation evidence without deleting
  originals.
- Plan archive paths and storage-budgeted batches with a default 100 GB reserve.
- Persist grouped review decisions.
- Generate file-management reports for inventory, large folders, duplicate
  groups, RAW/JPG pairing queues, RAW-without-JPG queues, planned operations,
  path conflicts, and deletion candidates.
- Generate deletion manifests that require later explicit approval.
- Provide a Windows scaffold, setup/run scripts, and environment checks.

## Safety Rules

- Originals are preserved by default.
- No destructive action is executed by the core dry run.
- The user's real 4 TB Windows drive is out of scope unless separately approved.
- Windows-only concerns are represented by interfaces, scaffolds, environment
  checks, and documented validation steps until tested on Windows.

## Termux Development

From this repository:

```sh
python -m unittest discover -s tests
PYTHONPATH=src python -m photos check-env
PYTHONPATH=src python -m photos dry-run tests/fixtures/sample_media --db .photos-data/sample.sqlite --output .photos-data/dry-run --free-bytes 214748364800
PYTHONPATH=src python -m photos report --db .photos-data/sample.sqlite --output .photos-data/report.json
```

The dry run writes SQLite/runtime data under `.photos-data/`, which is ignored by
Git.

## Windows Handoff

The GitHub remote is:

```text
git@github.com:humetro15445005/photos.git
```

On Windows PowerShell:

```powershell
git clone git@github.com:humetro15445005/photos.git
cd photos
.\scripts\setup_windows.ps1
.\scripts\check_environment.ps1
.\scripts\run_windows.ps1 -CheckEnv
.\scripts\run_windows.ps1 -SampleDryRun
.\scripts\verify_windows.ps1
```

If PySide6 installation is blocked, run `.\scripts\setup_windows.ps1 -SkipGui`
to validate the core first, then install the GUI dependency separately.

See [docs/windows_handoff.md](docs/windows_handoff.md) for the full Windows
handoff and validation checklist.

## Notes on External Tools

The core is standard-library-only so it can be tested in Termux. Windows media
tooling is checked, not bundled:

- Python 3.11+
- FFmpeg
- ExifTool
- RAW processor such as darktable-cli, rawtherapee-cli, or ImageMagick where
  available
- Optional PySide6 for the desktop scaffold
