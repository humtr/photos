# photos

`photos` is a safety-first media triage project. The current target is a
Termux-verified core plus a Windows-handoff-ready v1 scaffold, not a claim that
Windows GUI performance, RAW color quality, or a real 4 TB drive run have been
fully validated from Termux.

## What v1 Does

- Index sample photos, RAW files, and videos into SQLite.
- Detect exact duplicates by SHA-256.
- Resume SHA-256 hashing in bounded batches after a fast inventory pass.
- Pair RAW and JPG files by folder and basename.
- Plan RAW-to-archival-JPG work and record validation evidence without deleting
  originals.
- Plan archive paths and storage-budgeted batches with a default 100 GB reserve.
- Persist grouped review decisions.
- Generate file-management reports for inventory, large folders, duplicate
  groups, RAW/JPG pairing queues, RAW-without-JPG queues, planned operations,
  path conflicts, candidate counts, missing files, current/historical scan
  errors, and hash backlog.
- Generate review packages with CSV queues and Windows `.url` shortcuts for
  exact duplicates, RAW/JPG pairs, RAW files needing conversion, likely
  non-person images, and videos.
- Import external person/non-person classifier results and edited keep/delete
  decisions without moving or deleting originals; decision imports validate
  allowed values before committing.
- Generate candidate review manifests separately from approved delete manifests.
  Candidate manifests are not execution manifests.
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
PYTHONPATH=src python -m photos analyze tests/fixtures/sample_media --db .photos-data/analyze.sqlite --output .photos-data/analyze --max-review-shortcuts 25
PYTHONPATH=src python -m photos hash --db .photos-data/analyze.sqlite --max-files 1000
PYTHONPATH=src python -m photos report --db .photos-data/sample.sqlite --output .photos-data/report.json --max-detail-items 1000
PYTHONPATH=src python -m photos review-export --db .photos-data/analyze.sqlite --output .photos-data/review_package
```

The dry run writes SQLite/runtime data under `.photos-data/`, which is ignored by
Git.

Termux temporary-path rule: do not hard-code `/tmp` in commands, tests, scripts,
or documentation for this project. Use `$TMPDIR` in shell commands and Python
`tempfile` APIs in code/tests. Android/Termux can expose `/tmp` even when it is
not writable by the Termux app user; `$TMPDIR` points to the Termux-owned
temporary directory.

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
.\scripts\run_windows.ps1 -AnalyzeRoot "D:\Photos" -AnalyzeOutput ".photos-data\real-drive-first-pass" -SkipHash
.\scripts\run_windows.ps1 -Hash -HashMaxFiles 1000
.\scripts\verify_windows.ps1
```

Use `-SkipHash` for a fast first inventory pass on a large drive. Remove it
when you are ready to compute SHA-256 hashes for exact duplicate detection; the
database keeps previous scan data so hashing can resume. Use `-HashMaxFiles`
to process a bounded batch, then rerun `-Hash` until the report shows no hash
backlog. Use the generated `candidate_manifest.json` for review only; write a
separate decision manifest after importing explicit delete decisions.

If PySide6 installation is blocked, run `.\scripts\setup_windows.ps1 -SkipGui`
to validate the core first, then install the GUI dependency separately.

See [docs/windows_handoff.md](docs/windows_handoff.md) for the full Windows
handoff and validation checklist.

The repository also includes a Windows GitHub Actions workflow at
`.github/workflows/windows-ci.yml`. After pushing to `main`, check the
`Windows CI` workflow on GitHub. A passing run means the Windows setup script,
Windows verifier script, core package, installed CLI dry run, and
file-management report/review-package workflow have all run on `windows-latest`
for Python 3.11 and 3.12.

## Notes on External Tools

The core is standard-library-only so it can be tested in Termux. Windows media
tooling is checked, not bundled:

- Python 3.11+
- FFmpeg
- ExifTool
- RAW processor such as darktable-cli, rawtherapee-cli, or ImageMagick where
  available
- Optional PySide6 for the desktop scaffold
