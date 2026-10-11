# Windows Handoff

This document separates code transfer from Windows-only validation. GitHub is
the code handoff path; it does not prove that external media tools, GUI
performance, or a real 4 TB drive workflow are ready.

## Session Takeover Summary

Use this section first if you are picking up the work on a Windows machine.
It tells you what this branch already contains, what was changed during this
session, and what remains to be proven on real Windows hardware.

### What This Session Focused On

- Kept `PhotoOrganizerService` as the only frontend mutation boundary.
- Preserved the current repo strengths: `report-page`, reparse-safe scanning,
  scan-error and missing-file repair behavior, rich candidate and deletion
  manifests, report paging/detail limits, and the root Tkinter GUI.
- Merged the commercial backend safety model into the current tree instead of
  replacing the repo wholesale.
- Expanded the CLI with commercial execution and recovery commands while
  keeping `report-page`.
- Added structured progress and recovery cues across scan, hash, analysis,
  dry-run, `plan-dry-run`, execute, reconcile, resume, and rollback flows.
- Made the GUI surface backend recovery hints in both the warning/detail text
  and the status bar.
- Added Windows verifier switches for copied-fixture commercial smoke and
  temp-only filesystem probes.
- Kept the goal ledger and handoff docs aligned with the current proof so
  later sessions can see what was verified and what is still unproven.

### What Was Fixed In This Branch

These are the main user-facing and safety-related fixes already present in the
current branch:

- CLI interruption now returns a structured envelope instead of a traceback.
- The envelope records the interrupted command and a command-specific
  `next_safe_action`.
- `batch-resume` points back to `resume_batch` so interrupted work can continue
  from recorded state.
- `dry-run` and `plan-dry-run` now show stage-based progress instead of only a
  raw operation token.
- The root GUI status bar names analysis and dry-run stages explicitly.
- Service-boundary failures show the backend recovery hint in the GUI warning
  and status text.
- Scan, hash, analysis, and batch progress are bounded so large libraries do
  not flood the console with per-item spam.
- The copied-fixture commercial smoke and rollback path are already verified in
  the available Termux environment.

### Latest Proof Available Here

- `python scripts/verify_handoff.py` passed with 59 tests.
- `git diff --check` was clean at the last verified state.
- The copied-fixture commercial smoke passed analyze, plan, dry-run, approve,
  execute, integrity, rollback, and rollback-manifest validation.
- The 500,000-row synthetic public database validation passed in 81.444
  seconds.
- The wheel proof was built with `python -m pip wheel . --no-deps
  --no-build-isolation` in this restricted environment.

### What Windows Still Has To Prove

These are the remaining proof gaps. They are not code regressions in the
current branch; they are Windows-only runtime validations that still need to be
run on a Windows machine:

- Real NTFS and exFAT behavior, including long paths, junctions/reparse points,
  permissions, locking, and case-collision handling.
- Real Tkinter rendering, responsiveness, and large-library interaction.
- Installer creation, signing, upgrade, uninstall, and installed-runtime
  behavior.
- RAW/EXIF/FFmpeg tool discovery and output-quality validation.
- Hardware throughput and soak behavior on representative Windows media.

### Windows Resume Order

When you open the repo on Windows, run the checks in this order:

1. `.\scripts\verify_windows.ps1`
2. `.\scripts\verify_windows.ps1 -CommercialSmoke`
3. `.\scripts\verify_windows.ps1 -WindowsFilesystemProbes`
4. `.\scripts\run_windows.ps1 -Gui`
5. A copied-sample `-SampleDryRun`
6. A read-only first pass on a real folder only after the previous steps are
   clean and you have separate approval

If any of those fail, fix the smallest visible issue first and rerun the same
command before moving to the next step.

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
because Tkinter support and Pillow wheels are predictable there. If none are
found, install Python 3.11 or newer from python.org or the Microsoft Store,
reopen PowerShell, and rerun setup.

To validate the core without installing Pillow, use:

```powershell
.\scripts\setup_windows.ps1 -SkipGui
.\scripts\verify_windows.ps1
```

Install the `gui` extra before testing image previews. Tkinter is supplied by
the Python installation, not by pip.

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

Missing tools are expected on a fresh machine. Install required tools, rerun the
check, and keep the report with later validation notes. The shipped GUI uses the
root Tkinter route, which still requires a real Windows GUI validation run.

## Run

```powershell
.\scripts\run_windows.ps1 -CheckEnv
.\scripts\run_windows.ps1 -SampleDryRun
.\scripts\run_windows.ps1 -AnalyzeRoot "D:\Photos" -AnalyzeOutput ".photos-data\real-drive-first-pass" -SkipHash
.\scripts\run_windows.ps1 -Hash -HashMaxFiles 1000
.\scripts\run_windows.ps1 -Gui
.\scripts\verify_windows.ps1
```

Optional copied-fixture commercial safety smoke:

```powershell
.\scripts\verify_windows.ps1 -CommercialSmoke
```

`run_windows.ps1 -Gui` invokes the installed `python -m photos gui` route. That
route and the installed `photo-organizer` console script both load
`photo_organizer_app.main()`, the feature-complete root Tkinter GUI. The GUI
reports a clear runtime error when the wheel is missing the root module or the
Python installation lacks Tkinter. Real Windows UI behavior is not validated
by Termux tests.

Use `-SkipHash` for the first real-drive inventory so the app can surface media
counts, folder pressure, RAW/JPG pairing candidates, likely non-person images,
and videos before spending time hashing 4 TB of data. Remove `-SkipHash` for
the exact duplicate pass; hashing is incremental because already-hashed files
remain recorded in SQLite.

Use `-HashMaxFiles` for a bounded hash batch on the first real run. Rerun
`.\scripts\run_windows.ps1 -Hash` to continue until the file-management report
shows `scan_health.hash_backlog.count` is `0`.

If a long-running CLI command is interrupted with Ctrl-C, the CLI now exits
with code `130` and prints a structured envelope that records the interrupted
command plus a command-specific recovery-oriented `next_safe_action`. For
`dry-run`, that `next_safe_action` is `sample_dry_run`; for `batch-resume`,
it is `resume_batch`; for `service-smoke` and `batch-reconcile`, it matches
the corresponding recovery workflow. Use `batch-resume` to continue from the
recorded batch state instead of replaying completed items.

If the root GUI receives a backend service failure, the warning/detail text
now carries the backend `next_safe_action`, and the status bar echoes that
recovery step so the next action is visible in both the dialog and the
persistent UI state instead of hidden behind a generic error.

Long-running hash and batch execution/recovery commands also emit structured
progress frames to stderr while the final JSON envelope continues to print on
stdout. The same pattern now covers analysis and dry-run as well, so the root
GUI and CLI both surface stage transitions and item counts during long-running
work. `plan-dry-run` now follows the same stage-based envelope, and the root
GUI status bar reflects those dry-run stages during the service gate with
stage-specific transitions. Scan, hash, and batch execution/recovery progress
are throttled to a bounded cadence so 500k-file runs stay useful instead of
flooding stderr on every item.

`verify_windows.ps1` runs the same safety-core checks expected after handoff:
unit tests, environment report, sample dry run, manifest inspection,
file-management report inspection, review package inspection, and a
non-destructive safety assertion.

With `-CommercialSmoke`, `verify_windows.ps1` copies
`tests\fixtures\sample_media` into a temp workspace and runs the commercial
execution path against only that copy: analyze, plan creation, action listing,
dry-run, approval, execution, execution manifest validation, integrity check,
rollback, and rollback manifest validation. It creates and removes only temp
workspace files and does not mutate real media roots.

Opt-in temp-workspace Windows filesystem probes:

```powershell
.\scripts\verify_windows.ps1 -WindowsFilesystemProbes
```

`-WindowsFilesystemProbes` currently runs `long_path_probe`, which creates,
reads, and deletes a nested temp path longer than 260 characters, and
`case_collision_probe`, which plans two temp media files whose names collide
case-insensitively and verifies planned destination paths remain
case-insensitively unique. It reports `junction_reparse_probe` and
`permission_lock_probe` as skipped with explicit reasons until those temp-root
fixtures are implemented. The deprecated `-WindowsProbePlaceholders` parameter
is accepted only as a backward-compatible alias for the real probe switch.
Passing these probes is bounded evidence, not a Windows release-readiness claim.

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
- Confirm long-running CLI commands handle Ctrl-C by returning a structured
  envelope and exit code `130`, then use `batch-resume` to continue recorded
  work instead of restarting from scratch; the envelope's `next_safe_action`
  should match the interrupted command's recovery workflow, including
  `dry-run`, `service-smoke`, and `batch-reconcile`.
- Save the output of `.\scripts\verify_windows.ps1` with the validation notes.
- Run `.\scripts\verify_windows.ps1 -CommercialSmoke` and save the JSON summary
  before any real-drive mutation workflow.
- Only after separate approval, run any real-drive scan in read-only mode first.

## Packaging And Proof Boundaries

Source checkout:

- `python .\photo_organizer_app.py` uses the repository root entrypoint.
- The root entrypoint prefers `vendor\PIL` and adds `src` so the local
  `photos` backend is available.

Installed project or wheel:

- `photos gui`, `python -m photos gui`, and `photo-organizer` launch the same
  root Tkinter GUI through `photos.gui`.
- The wheel includes `photo_organizer_app.py` and the `photos` backend.
- The wheel does not include `vendor\PIL`; install `photos-triage[gui]` for
  Pillow. Tkinter must be present in the selected Python installation.

PyInstaller:

- `PhotoOrganizer.spec` and `PhotoOrganizerFast.spec` analyze both `vendor` and
  `src`, preserving vendored Pillow discovery and including the `photos`
  service backend imported by the root GUI.
- A successful PyInstaller build is not an installer, signing, or Windows
  runtime proof.

Termux verification covers compilation, unit tests, wheel contents, and
non-interactive safety-core behavior. Windows must still validate Tkinter
rendering and performance, NTFS/exFAT behavior, long paths, junction/reparse
points, permissions and file locking, external RAW/EXIF tools, real conversion
quality, large-library hardware throughput, installer creation, and code
signing.

## Retired Source Copies

The working-tree cleanup removed `_zip_check/photos-triage-hardened` (40 files)
and `legacy2` (46 files). Both remain recoverable with their original Git blobs
from published commit `189caf91ff4cd244dd367110e14517b18f144cf6`, verified on
`origin/v3` before removal. Git's configured line-ending filters were accounted
for when comparing the working files. No active package, script, workflow, or
import uses these folders; `src/photos/store.py` mentions `legacy2` only as
migration provenance. The maintained backend is `src/photos`, with the root
Tkinter entrypoint and active `vendor` inputs described above.

The zip-check source is not completely superseded: it contains scan-run
tracking with current-versus-historical scan errors, stricter atomic review
import validation, additional approved-delete manifest metadata, and regression
tests absent from the maintained source. Its unique historical plan and
`session-summary.md` are preserved at the same commit. Removal does not merge
or establish those features in the maintained app. The retired v2 implementation,
its tests, `GOAL_PROGRESS.md`, and `RELEASE.md` are also preserved there.

Inspect a historical file without restoring a duplicate tree:

```bash
git show 189caf91ff4cd244dd367110e14517b18f144cf6:_zip_check/photos-triage-hardened/src/photos/scanner.py
git show 189caf91ff4cd244dd367110e14517b18f144cf6:legacy2/RELEASE.md
```

For a full comparison, extract only to a disposable location (Termux):

```bash
snapshot_root="$(mktemp -d "${TMPDIR:?}/photos-history.XXXXXX")"
git archive 189caf91ff4cd244dd367110e14517b18f144cf6 \
  _zip_check/photos-triage-hardened legacy2 | tar -x -C "$snapshot_root"
```

Keep `.photos-data`, real photos, settings, and active vendored dependencies
outside this cleanup. Generated `*.egg-info` is disposable package metadata.
