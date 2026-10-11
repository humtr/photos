# Large-Library And Windows Trust Gaps

## Synthetic Scale Proof

`tests/test_large_library.py` creates no physical media files. It directly
batch-inserts rows into the application's real SQLite schema, then queries the
public service/report surfaces used by clients.

The normal automated run uses 12,000 media rows, 12,000 plan actions, and
12,000 batch items. It verifies:

- media pages return the requested bounded row count and the exact total;
- management-report inventory totals and detail limits remain correct;
- a duplicate-detail report page returns only the requested page;
- plan-action and batch-item list calls remain paged and report exact totals;
- execution-batch recovery metadata reports the full batch item count.

The latest opt-in test shape was run with 500,000 rows per large table and
passed in 81.444 seconds on the current worktree:

```bash
env PYTHONPATH=src PHOTOS_LARGE_LIBRARY_ROWS=500000 \
  python -m unittest tests.test_large_library
```

This is synthetic public database paging/report/plan/batch validation. The
500,000-row pass does not prove scanner throughput, hashing throughput,
manifest write size, GUI rendering, filesystem mutation, rollback throughput,
Windows behavior, or hardware soak behavior.

## Available-Environment Safety Proof

The current bounded evidence also establishes:

- service-boundary GUI/CLI code and AST enforcement tests exist;
- the root GUI direct `shutil.move` gap is repaired;
- full unittest discovery passed 36 tests;
- `compileall` passed;
- `python scripts/verify_handoff.py` passed after the root Tkinter wording
  correction and includes 36 unittest tests;
- copied-fixture analyze, plan, actions, dry-run, approval, and execution
  completed 7 actions with 0 failures;
- the execution manifest validated with file verification and integrity status
  was `ok`;
- rollback completed 7 actions with 0 failures and its batch manifest
  validated;
- after rollback, the original execution manifest correctly became
  file-invalid because its executed destination state no longer existed.

These facts do not establish Windows release readiness.

## Packaging In This Environment

Build isolation attempts dependency resolution and requires an available package
index or cached build requirements. In the restricted Termux environment, use:

```bash
build_root="$(mktemp -d "${TMPDIR:?}/photos-build.XXXXXX")"
git archive HEAD | tar -x -C "$build_root"
PYTHONPYCACHEPREFIX="${XDG_CACHE_HOME:-$HOME/.cache}/photos/pycache" \
  python -m pip wheel "$build_root" -w "$build_root/wheels" \
  --no-deps --no-build-isolation
```

This recipe builds the committed `HEAD` source in `TMPDIR`, keeping generated
`build/` and `*.egg-info` out of the maintained checkout. The local Python must
already provide the declared build backend (`setuptools>=69`).

The earlier wheel proof produced `photos_triage-0.2.0-py3-none-any.whl`.
The wheel contains
`photo_organizer_app.py`, `photos/services.py`, and console scripts `photos`
and `photo-organizer`. It does not contain `vendor/PIL`.

This proves that the current source tree can produce that wheel with the locally
available build backend. A normal isolated build and an installed Windows
runtime check remain required release proofs.

## Windows-Only Validation Still Required

Termux and synthetic SQLite validation do not establish Windows release
readiness. Before trusting a real library, validate on representative Windows
hardware and copied media:

- NTFS and exFAT behavior, permissions, file locking, case collisions, long
  paths, junctions, symlinks, and reparse points;
- GUI paging/rendering responsiveness and memory use at representative scale;
- scanner, hash, plan, manifest, execute, reconcile, resume, rollback, and
  integrity-check throughput under interruption and low-space conditions;
- CLI interruption handling and resume continuity on long-running commands, so
  Ctrl-C returns a structured recovery envelope whose `next_safe_action`
  matches the interrupted command's recovery workflow, including
  `dry-run`, `service-smoke`, `batch-reconcile`, `batch-resume`, and
  `plan-execute`, so
  recorded state can be continued instead of replaying completed work;
- long-running hash and batch execution/recovery commands now emit structured
  progress frames, and analysis/dry-run now do too, including stage-based
  `plan-dry-run` progress in the GUI service gate, but representative Windows
  behavior still needs validation on real hardware and real file counts; the
  root GUI status bar now shows stage-specific dry-run transitions instead of
  only the operation name, and scan, hash, and batch execution/recovery
  progress are throttled to a bounded cadence so the same frames can scale to
  500k-file runs;
- root GUI service-boundary failures should surface the backend
  `next_safe_action` in the warning/detail text and status text so a user sees
  the next safe recovery step instead of a generic failure only;
- RAW/EXIF/FFmpeg external-tool discovery and output quality;
- wheel/installer contents, root GUI launch path, signing, upgrades, and
  uninstall behavior.

The AGY executable is available at `/data/data/com.termux/files/home/bin/agy`,
but no AGY-produced change is claimed.

The root GUI direct `shutil.move` boundary is repaired and covered by bounded
service-boundary/AST checks. Real Windows GUI behavior and filesystem mutation
remain unproven. This document does not claim final completion or Windows
release readiness.
