# Photos Trusted Windows App Goal

## Goal Prompt

Use this prompt to start the goal:

```text
/goal GOAL.md를 기준 문서와 수락 원장으로 삼아 /data/data/com.termux/files/home/prj/photos 레포를 Windows에서 실제로 믿고 실행할 수 있는 사진 정리 앱으로 구현한다. 현재 레포를 보존한 상태에서 /sdcard/termux/import/photos/2/photos-commercial-v1.zip(SHA-256 e3c92bd336725bcd8c06caeb075372d156d1f2aca60f06c8ed69d2e18ed22a37)의 commercial backend 안전 모델을 병합하되, commercial zip으로 현재 레포를 blind replacement/overwrite 하지 않는다. 현재 레포의 report-page, os.scandir reparse-safe scanner, scan error/missing-file repair, rich candidate_manifest.json plus legacy deletion_manifest.json, report detail limits/recent scan errors, GUI workflow, vendor/PIL을 보존하거나 더 강한 검증된 대체로만 바꾼다. 현재 CLI는 report-page를 보존하면서 plan/create/approve/execute/manifest/reconcile/resume/rollback/integrity 계열 명령을 제공한다. PhotoOrganizerService를 유일한 frontend mutation boundary로 삼고 GUI/AGY/CLI가 SQLite, scanner, execution internals, 또는 실제 move/delete/rename을 직접 호출하지 못하게 한다. 실제 mutation은 plan creation, DB approval, immediate dry-run/preflight, runtime confirmation, operation lock, copy-temp-verify-replace-unlink, batch manifest, validation, reconcile/resume/rollback, integrity-check를 통과해야 한다. Worker split은 A backend safety, B DB/scanner/hash, C CLI/reports/manifests, D frontend/AGY, E scale/packaging/docs로 유지하고 parent는 조정/리뷰/검증만 하며 nontrivial implementation/content를 직접 작성하지 않는다. AGY는 /data/data/com.termux/files/home/bin/agy에서 사용할 수 있으나 service-boundary 제약을 따라야 한다. 각 구현 slice 뒤에는 post-slice validation을 실행하고 GOAL.md를 근거와 함께 갱신한다. 약 50만 개 파일 real soak가 불가능하면 같은 DB/UI/manifest/rollback scaling risk를 보존하는 500k synthetic validation을 수행한다. packaging proof에서는 이 환경의 ignored local build/가 python -m build를 shadow하므로 python -m pip wheel . -w /data/data/com.termux/files/usr/tmp/photos-wheel-check --no-deps --no-build-isolation 또는 동등한 unshadowed build frontend를 사용한다. Windows-only gap(NTFS/exFAT/long path/junction/permission, GUI rendering/performance, installer/signing, RAW/EXIF tools, hardware throughput/soak)은 명시적으로 남기고, 검증되지 않은 Windows release readiness를 주장하지 않는다. 이 목표는 매 주요 검증 뒤 현재 진행과 사용자 경험을 기준으로 다시 읽고, 필요한 수정이 있으면 먼저 GOAL.md를 갱신한 뒤 같은 목표를 재수행하는 재귀 루프로 운영한다.
```

## Public Contract

Target: the current repository at `/data/data/com.termux/files/home/prj/photos`.

Primary source inputs:

- Current repository: existing GUI, reporting, scanner, manifest, vendor/PIL, and local project conventions.
- Commercial source bundle: `/sdcard/termux/import/photos/2/photos-commercial-v1.zip`.
- Commercial source bundle SHA-256: `e3c92bd336725bcd8c06caeb075372d156d1f2aca60f06c8ed69d2e18ed22a37`.
- Verified extracted commercial reference, when present: `/data/data/com.termux/files/usr/tmp/photos-verify.DKTZIG/commercial/photos-commercial-v1`.

Output surface:

- A reconstructed `main` working tree whose backend and frontend form a trusted Windows photo organizer app.
- Updated source, tests, docs, and verification scripts.
- This `GOAL.md` as a living objective and acceptance ledger.

Success threshold:

- The commercial backend safety model is integrated.
- The current repository's useful GUI/report/scanner/vendor strengths are preserved or improved.
- The current CLI preserves `report-page` and gains commercial execution/recovery commands instead of remaining analysis/report-only.
- The app is designed and verified toward trusted operation on about 500,000 files.
- Long-running scans, hashes, and batch execution expose visible progress and resumable state to the user.
- Recovery state and the next safe action are clearly visible after interruption or failure.
- Existing handoff validation and commercial execution/recovery validation both pass in the available environment.
- Remaining Windows-only or hardware-only gaps are explicit, bounded, and backed by a validation plan.

Accepted baseline before implementation was clean and passed:

- `python -m compileall -q src tests photo_organizer_app.py`
- `env PYTHONPATH=src python -m unittest discover -s tests` with 8 tests
- `python scripts/verify_handoff.py`
- `env PYTHONPATH=src python -m photos --help`

## Meaning Of Trusted Execution

"믿고 실행할 수 있다" means a normal Windows user can point the app at a large photo/video library and proceed without reasonable fear of silent data loss, unrecoverable mutation, UI lockup from loading the whole library, or unclear recovery state.

For this goal, trusted execution includes:

- Scanning about 500,000 files without unbounded memory growth.
- Hashing and analysis in bounded, resumable batches.
- Visible progress, pause/resume state, and completion feedback in GUI status text, CLI envelopes, and recovery prompts for long-running scans, hashes, and batch execution.
- Clear recovery state and next safe action in GUI status text, CLI envelopes, and recovery prompts after interruption or failure.
- Resume continues from recorded batch state and surfaces the remaining retryable work instead of replaying completed items.
- GUI long-running scans and analysis tasks expose a clear stop/cancel path and reset the status text when stopped.
- CLI long-running commands exit cleanly on interruption with a structured envelope instead of a traceback.
- CLI long-running commands keep the recorded command name visible in the structured interruption envelope and point `next_safe_action` at the matching recovery workflow, including `dry-run`, `service-smoke`, and `batch-reconcile`.
- GUI service-boundary failures surface the backend `next_safe_action` in both the status text and the warning/detail text so the user sees the next recovery step instead of only a generic error.
- Paginated or virtualized UI/report views; never require all rows in memory or on screen.
- Explicit approval gates before filesystem mutation.
- Dry-run and preflight before execution.
- Copy-temp-verify-replace-unlink semantics for moves.
- Batch manifests for every mutation batch.
- Manifest validation with optional file verification.
- Rollback, reconcile, resume, and integrity-check support.
- Clear handling of Windows long paths, case collisions, reparse points, permissions, source/archive overlap, partial failures, and interrupted execution.
- A frontend that uses the backend service boundary and does not bypass safety gates.

`PhotoOrganizerService` is the only allowed frontend mutation boundary. GUI, AGY, and CLI entry points must not directly call SQLite, scanner internals, execution internals, or direct filesystem move/delete/rename operations for real mutation. Real mutation requires plan creation, DB approval, immediate dry-run/preflight, runtime confirmation, operation lock, copy-temp-verify-replace-unlink transfer semantics, batch manifest creation, validation, reconcile/resume/rollback support, and SQLite integrity-check.

## Living Plan / Goal Realignment

This document is both the minimum requirement and the current source of truth. It is not a ceiling.

When implementation reveals a safer architecture, stronger validation, better frontend workflow, better large-library performance strategy, or clearer development direction, update this document with:

- The new observation.
- The evidence or failed proof axis.
- The proposed change.
- The affected files or interfaces.
- The updated validation predicate.

Then realign the implementation to the updated goal.

## Recursive Goal Loop

The goal is intentionally recursive and should be re-evaluated against current state on every major pass.

Each iteration must:

1. Re-read this document and the current acceptance ledger.
2. Compare current worktree evidence, validation output, current progress, completed items, and user-facing behavior against the success threshold.
3. If the verification reveals a usability, safety, or reliability gap, or if the user workflow can be made clearer or safer before the next implementation slice, update this document before changing code or scripts.
4. Re-run the goal against the revised document until the implementation and ledger converge.
5. Keep user experience changes first-class when they improve clarity, recovery, or the safety of real use.

User experience revisions should prefer:

- shorter recovery paths after failure or interruption
- clearer approval and rollback cues before destructive mutation
- bounded views that avoid forcing a full-library load
- explicit validation notes where a user would otherwise need to guess
- visible progress and resume state for long-running scans, hashes, and batch execution

Goal realignment must not:

- Bypass the backend service boundary.
- Weaken approval, dry-run, manifest, rollback, resume, or integrity gates.
- Replace bounded proof with a simpler happy path.
- Mutate protected local data or generated evidence surfaces unnecessarily.
- Convert this project into a benchmark-specific or checker-specific solution.

## Model / Reasoning Policy

Available models are `5.5`, `5.4`, and `5.4 mini`.

- Planning, architecture decisions, safety gates, filesystem mutation design, rollback/recovery design, Windows release-readiness review, and final acceptance use `5.5 xhigh`.
- The main goal implementer should use `5.5 high` by default, escalating to `5.5 xhigh` for data-loss risk, schema migration, execution/rollback semantics, concurrency, large-library performance, or frontend/backend contract changes.
- Narrow implementation workers may use `5.4 high` when the task is well-scoped and protected surfaces are explicit. Examples: adding tests, porting isolated modules, wiring CLI commands, or merging documented behavior.
- `5.4 mini` is limited to low-risk support work: file inventories, diff summaries, command-output slicing, documentation cleanup, checklist updates, and non-authoritative analysis.
- `5.4 mini` must not own filesystem mutation logic, rollback logic, database schema changes, recovery logic, or final acceptance.
- If Termux can call AGY/Antigravity, AGY may be used for frontend planning and Windows app workflow, especially where commercial-v1 delegates frontend completion. AGY work must follow this document and the backend service boundary.
- Frontend work must not bypass approval, dry-run, manifest validation, rollback, resume, integrity-check, or recovery gates.
- Backend work is owned by Codex, using subworkers where available and appropriate. Workers must receive bounded briefs, protected surfaces, deliverables, validation commands, and final report requirements.

Accepted worker split:

- Worker A: backend safety, service contracts, execution, rollback, reconcile, resume, operation lock, integrity gates.
- Worker B: database, scanner, scan repair semantics, hashing backlog, indexes, transaction behavior.
- Worker C: CLI, reports, manifests, handoff verification, report-page preservation, commercial execution command merge.
- Worker D: frontend and AGY workflow/UX, constrained to `PhotoOrganizerService` for mutation.
- Worker E: large-library scale validation, packaging, Windows docs, release-readiness gap ledger.
- Parent: coordination, reviews, integration decisions, and verification only; no nontrivial implementation/content/file deliverables unless explicitly authorized after delegation is unavailable or blocked.

## Source Strengths To Preserve

Current repository strengths:

- Larger root Tkinter GUI in `photo_organizer_app.py`.
- Workflow, scan filter, duplicate insight, preview, bulk suggestion, metadata edit plan, and strategy comparison UI behavior.
- `report-page` CLI.
- Management report detail paging and detail limits.
- Scan error summary and recent scan error reporting.
- `candidate_manifest.json` plus legacy `deletion_manifest.json` compatibility.
- Candidate manifest fields such as `manifest_type`, `approval_state`, `approved_for_delete`, and `validation_required_before_delete`.
- `os.scandir` scanner traversal that avoids symlink/reparse directories and is stronger than commercial-v1's simpler traversal.
- Conservative scan error/missing-file repair behavior that avoids marking files missing after scan errors and is stronger than commercial-v1.
- `vendor/PIL` for root GUI Pillow availability.

Commercial-v1 strengths:

- `PhotoOrganizerService` service boundary.
- Product store and contracts layer.
- Backend modules to port into the current source tree:
  - `src/photos/contracts.py`
  - `src/photos/store.py`
  - `src/photos/services.py`
  - `src/photos/execution.py`
  - `src/photos/duplicates.py`
  - `src/photos/date_audit.py`
- Duplicate/date audit materialization.
- Approval-gated archive planning and execution.
- Copy-temp-verify-replace-unlink filesystem mutation.
- Execution batch, item, transfer verification, and manifest records.
- Rollback support.
- Operation lock for filesystem mutation.
- Pre-execution and pre-rollback SQLite backups.
- Archive/source overlap blockers.
- Windows reparse point guard in execution validation.
- Batch manifest validation.
- Batch reconciliation and resume.
- SQLite integrity check.
- WAL, longer busy timeout, temp memory store, larger cache target, and additional indexes.
- Bounded hash backlog processing.
- Periodic scan commits.
- Commercial safety tests and docs.

## Current Acceptance Ledger

Proven in the available Termux environment:

- The commercial source zip SHA-256 was freshly verified as `e3c92bd336725bcd8c06caeb075372d156d1f2aca60f06c8ed69d2e18ed22a37`.
- Service-boundary GUI/CLI implementation and AST enforcement tests exist. The root GUI direct `shutil.move` gap is repaired.
- The current full unittest discovery passed 59 tests. `compileall` passed. `python scripts/verify_handoff.py` passed after the root Tkinter wording correction and includes 59 unittest tests.
- `run_media_analysis` progress is now verified as a stage-based sequence for the analysis envelope, so the user sees starting/scanned/hashed/planned/budget_checked/manifest_written/report_written/review_package_written/completed transitions instead of an unbounded item stream.
- The CLI `dry-run` command is also verified to forward structured stderr progress for the same stage sequence, so the user-facing non-destructive path exposes the same bounded analysis feedback as the shared helper.
- The CLI `plan-dry-run` command is now verified to forward structured stderr progress for the stage-based plan validation envelope, and the backend/service/GUI path now forwards the same dry-run stages into the status bar during the root GUI service flow, so the non-destructive check is visible across all user-facing surfaces.
- The root GUI progress formatter now names analysis and dry-run stages explicitly and reports stage-specific transitions instead of falling back to raw operation tokens for those surfaces.
- The root GUI progress formatter's stage-specific outputs are runtime-checked for representative analysis, sample dry-run, and plan-dry-run payloads, not just source-checked.
- A copied-fixture commercial smoke passed analyze, plan creation, action listing, dry-run, approval, and execution with 7 completed and 0 failed. The execution manifest validated with file verification and integrity status was `ok`.
- The same copied-fixture smoke passed rollback with 7 completed and 0 failed, and the rollback batch manifest validated. The original execution manifest correctly became file-invalid after rollback because its executed destination state no longer existed.
- The latest opt-in 500,000-row synthetic public database paging/report/plan/batch test passed in 81.444 seconds on the current worktree. It does not prove scanner, filesystem, GUI, Windows, or hardware soak behavior.
- `photos_triage-0.2.0-py3-none-any.whl` was built with `--no-build-isolation`; the wheel contains `photo_organizer_app.py`, `photos/services.py`, and console scripts `photos` and `photo-organizer`. It does not include `vendor/PIL`.
- The AGY executable is available at `/data/data/com.termux/files/home/bin/agy`; no AGY-produced change is claimed by this ledger.
- The root GUI already emits progress callbacks during folder structure, content, date, duplicate analysis, and batch execution; the backend/service/CLI now expose structured progress frames for scanning, hashing, analysis, execute/resume/reconcile/rollback batch flows, and CLI stderr progress, with scan/hash plus batch execution/recovery frames throttled to a bounded cadence for large libraries and analysis/dry-run retained as stage-based progress rather than per-item spam, and the root GUI progress formatter now names analysis and dry-run stages explicitly and reports stage-specific transitions instead of falling back to a raw operation token, and GUI service-boundary failures now echo backend recovery hints in both the status text and the warning/detail text, but visible Windows UI progress/resume behavior remains unverified in this environment.
- `scripts/verify_windows.ps1` has an opt-in `-CommercialSmoke` switch for copied-fixture analyze, plan, actions, dry-run, approval, execution, manifest validation, integrity, rollback, and rollback-manifest validation in a temp workspace only. It also has an opt-in `-WindowsFilesystemProbes` switch for temp-only filesystem probes: `long_path_probe` creates, reads, and deletes a nested path longer than 260 characters, and `case_collision_probe` verifies archive-planned destination paths remain case-insensitively unique for two source files whose names collide case-insensitively. `junction_reparse_probe` and `permission_lock_probe` still report skipped with explicit reasons. `-WindowsProbePlaceholders` is retained only as a deprecated alias. These probes were not run in Termux because `pwsh` is unavailable here, and they do not prove Windows release readiness.

Not proven and still required before any Windows release-readiness claim:

- Real Windows NTFS/exFAT, long-path, junction/reparse-point, permissions, locking, and case-collision behavior.
- Real Windows GUI rendering, responsiveness, memory behavior, and large-library interaction.
- Scanner, hashing, manifest, mutation, interruption/recovery, and rollback throughput on representative filesystems and hardware.
- Installer creation, signing, upgrades/uninstall, and installed-runtime validation.
- RAW/EXIF/FFmpeg tool discovery and output-quality validation on Windows.

This ledger records current bounded evidence. It does not declare the overall goal complete or the app ready for release on Windows.

## Historical Starting Weaknesses And Current Status

Do not merely choose one side's weakness.

- Historical: the starting repository lacked a real service/execution/rollback/recovery backend. Current service and recovery surfaces exist and have bounded copied-fixture proof.
- Historical: the starting CLI lacked commercial execution commands. The current CLI preserves `report-page` and includes the commercial execution/recovery command family.
- Historical: the accepted baseline had only 8 tests. Current full unittest discovery passed 36 tests.
- Historical: the starting wheel did not include the root GUI or `vendor/PIL`. The current `photos_triage-0.2.0-py3-none-any.whl` includes `photo_organizer_app.py`, `photos/services.py`, and console scripts `photos` and `photo-organizer`, but still excludes `vendor/PIL`.
- Commercial-v1 lacks current `report-page`.
- Commercial-v1 has a simpler scanner traversal than current repo.
- Commercial-v1 lacks current candidate manifest richness.
- Commercial-v1 lacks current report-page/detail limits/recent scan errors and current scan error/missing-file repair behavior.
- Commercial-v1 root GUI is smaller and lacks several current GUI workflows.
- Commercial-v1 zip does not include `vendor/PIL`.
- Neither side proves 500k-file Windows soak behavior. The current 500k synthetic public database test is bounded evidence only.
- Neither side is a signed Windows installer.
- Neither side completes full GUI QA, RAW conversion quality validation, EXIF-write validation, or real Windows hardware validation.
- Windows-only gaps remain: real Windows NTFS/exFAT/long path/junction/permission behavior, GUI rendering/performance, installer/signing, RAW/EXIF tools, and hardware throughput/soak.

## Protected Surfaces

Do not modify unless a later explicit task scopes them:

- `.git/`
- `.photos-data/`
- Existing untracked/generated evidence not required for the integration
- Historical commits, refs, reflogs, or object stores

The later authorized source cleanup removed `_zip_check/` and `legacy2/` from
the working tree. Their exact Git source, fixtures, plans, and release notes remain
in published commit `189caf91ff4cd244dd367110e14517b18f144cf6`; recovery details
and unmerged snapshot hardening are in `docs/windows_handoff.md`.

Preserve unless there is a documented replacement plan:

- `vendor/PIL/`
- Root GUI behavior in `photo_organizer_app.py`
- Existing tests and fixtures
- Existing Windows scripts unless superseded by verified commercial-safe behavior

## Integration Strategy

Do not overwrite the current repository with the commercial zip.

Use commercial-v1 as the backend safety foundation, then merge current repo advantages into that foundation.

### Phase 1: Baseline And Ledger

- Record `git status --short`.
- Verify current repository behavior:
  - `python -m compileall -q src tests photo_organizer_app.py`
  - `env PYTHONPATH=src python -m unittest discover -s tests`
  - `python scripts/verify_handoff.py`
  - `env PYTHONPATH=src python -m photos --help`
- Verify or re-extract commercial-v1 from `/sdcard/termux/import/photos/2/photos-commercial-v1.zip`.
- Record exact commercial source path and sha256 of the zip:
  - path: `/sdcard/termux/import/photos/2/photos-commercial-v1.zip`
  - SHA-256: `e3c92bd336725bcd8c06caeb075372d156d1f2aca60f06c8ed69d2e18ed22a37`
- Update this document if the source bundle differs from the previously inspected bundle.

### Phase 2: Add Commercial Backend Skeleton

Add commercial backend files that do not exist in the current repo:

- `src/photos/contracts.py`
- `src/photos/execution.py`
- `src/photos/services.py`
- `src/photos/store.py`
- `src/photos/duplicates.py`
- `src/photos/date_audit.py`
- `tests/test_service_mvp.py`
- `tests/test_service_formal_execution.py`
- `tests/test_indexes.py`
- `tests/test_commercial_safety.py`
- `COMMERCIAL_HARDENING_SUMMARY.md`
- `COMMERCIAL_CHANGELOG.md`
- `docs/06_COMMERCIAL_HARDENING_NOTES.md`

### Phase 3: Merge Existing Files Conservatively

Merge, do not blindly replace:

- `pyproject.toml`: adopt `0.2.0`, commercial description, pytest config; preserve current package conventions.
- `src/photos/database.py`: adopt WAL/busy timeout/cache/indexes; preserve scan error and missing-file behavior.
- `src/photos/hashing.py`: adopt bounded backlog hashing.
- `src/photos/scanner.py`: combine current `os.scandir`/reparse-safe traversal with commercial periodic commits.
- `src/photos/manifest.py`: preserve current rich `candidate_manifest.json` and legacy `deletion_manifest.json` compatibility; ensure commercial execution manifests do not weaken candidate review semantics.
- `src/photos/reports.py`: preserve `report-page`, paging/detail limits, and recent scan error reporting; ensure service compatibility.
- `src/photos/pairing.py`: preserve current functions and add `find_duplicate_candidate_buckets`.
- `src/photos/dry_run.py`: preserve candidate manifest and report paging support; keep commercial service compatibility.
- `src/photos/cli.py`: preserve `report-page`; add commercial plan/create/approve/execute/batch/manifest/reconcile/resume/rollback/integrity commands.
- `scripts/verify_handoff.py`: preserve current dry-run validation; add service boundary validation.
- Windows scripts: merge only behavior with clear validation value.

### Phase 4: GUI And Frontend

- Preserve root `photo_organizer_app.py` first.
- Do not replace it with the smaller commercial-v1 root GUI.
- Compare commercial GUI changes and selectively port only useful improvements:
  - progressive rendering
  - DB cache deletion
  - execute worker safety
  - any service-boundary-compatible workflow
- Keep `vendor/PIL` unless replaced by a stronger packaging plan.
- Use AGY/Antigravity at `/data/data/com.termux/files/home/bin/agy` for frontend planning or implementation where helpful.
- Frontend must call backend service APIs for mutation workflows.
- Frontend must never call SQLite, scanner internals, execution internals, or move, delete, rename, or modify files directly outside backend-approved `PhotoOrganizerService` flows.

### Phase 5: Large-Library Readiness

Implement and verify design for about 500,000 files:

- Scanner bounded memory.
- Hash backlog bounded memory.
- Periodic commits.
- Resume/reconcile support after interruption.
- Report and review pagination.
- UI virtualization or paged data access.
- No full-library row rendering in a single UI operation.
- Export flows for large review queues.
- Explicit performance notes and future soak-test procedure.

If an actual 500k-file run is not feasible in Termux, create a faithful synthetic validation plan or generator that preserves the same database and UI scaling risks without mutating real media.
The synthetic proof must exercise post-slice database growth, report pagination/export, manifest size, review queue behavior, recovery metadata, and frontend data-access assumptions rather than only creating empty placeholder files.

### Phase 6: Packaging And Windows Trust

- Keep source install and wheel install paths working.
- Document whether root GUI is part of wheel, script execution, or PyInstaller packaging.
- For Termux packaging proof, export committed source and build only under `TMPDIR`, following `docs/large_library_windows_gaps.md`. Install declared build prerequisites in disposable tooling; keep compiler/bytecode caches under XDG cache.
- A normal isolated build requires build-dependency/index availability. Historically, in the restricted environment, `python -m pip wheel . -w /data/data/com.termux/files/usr/tmp/photos-wheel-check --no-deps` failed during build-isolation dependency resolution, while the same command with `--no-build-isolation` passed.
- Keep Windows setup and verification scripts aligned with the final app surface.
- Document remaining Windows-only validation:
  - real hardware
  - long paths
  - NTFS/exFAT behavior
  - permissions
  - reparse points/junctions
  - Tkinter rendering
  - installer/signing
  - RAW/EXIF external tool behavior

## Required Validation

Run the smallest faithful current checks after each major integration slice and again after post-slice repairs:

```bash
python -m compileall -q src tests photo_organizer_app.py
env PYTHONPATH=src python -m unittest discover -s tests
python scripts/verify_handoff.py
env PYTHONPATH=src python -m photos --help
```

Run commercial backend smoke on copied sample media:

```bash
env PYTHONPATH=src python -m photos analyze <media_copy> --db <tmp>/photos.sqlite --output <tmp>/out
env PYTHONPATH=src python -m photos plan-create --db <tmp>/photos.sqlite --archive-root <tmp>/archive
env PYTHONPATH=src python -m photos plan-actions 1 --db <tmp>/photos.sqlite --limit 20
env PYTHONPATH=src python -m photos plan-dry-run 1 --db <tmp>/photos.sqlite
env PYTHONPATH=src python -m photos plan-approve 1 --db <tmp>/photos.sqlite --note cli
env PYTHONPATH=src python -m photos plan-execute 1 --db <tmp>/photos.sqlite --yes
env PYTHONPATH=src python -m photos batch-manifest-validate 1 --db <tmp>/photos.sqlite --verify-files
env PYTHONPATH=src python -m photos integrity-check --db <tmp>/photos.sqlite
env PYTHONPATH=src python -m photos batch-rollback 1 --db <tmp>/photos.sqlite --yes
env PYTHONPATH=src python -m photos batch-manifest-validate 2 --db <tmp>/photos.sqlite --verify-files
```

Verify current repo features still exist:

```bash
env PYTHONPATH=src python -m photos report-page --help
env PYTHONPATH=src python -m photos dry-run tests/fixtures/sample_media --db <tmp>/dry.sqlite --output <tmp>/dry --free-bytes 214748364800
```

Expected dry-run artifacts:

- `candidate_manifest.json`
- legacy `deletion_manifest.json`
- `management_report.json`
- `review_package/decisions_template.csv`
- `review_package/queues/exact_duplicates.csv`

Packaging checks:

Use the committed-source export and wheel recipe in
`docs/large_library_windows_gaps.md`. Its source, build intermediates, and wheel
output stay under `TMPDIR`; build prerequisites belong in disposable tooling.
Do not create local build projects or install binaries under the repository.

If `pytest` is available:

```bash
python -m pytest
PYTHONPATH=src python -m pytest -q tests
```

If `pytest`, `tkinter`, `exiftool`, or RAW tools are unavailable in Termux, classify that as an environment limitation and keep faithful backend checks running.

## Acceptance Criteria

The goal is complete only when all applicable criteria hold:

- Current repository strengths listed in this document are preserved or deliberately superseded by a better documented replacement.
- Commercial backend safety APIs and CLI are integrated.
- Filesystem mutation is service-boundary-only.
- GUI, AGY, and CLI do not directly call SQLite, scanner internals, execution internals, or real filesystem mutation APIs outside `PhotoOrganizerService`.
- Approval, dry-run, runtime confirmation, manifest, validation, rollback, reconcile, resume, and integrity-check gates exist and are tested.
- `report-page` remains available.
- Candidate and legacy manifests are both produced by dry-run.
- Scanner is reparse-safe and uses bounded transaction commits.
- Hashing is bounded-memory and resumable.
- Reports/review queues support large-library pagination/export.
- Long-running scans, hashes, and batch execution expose visible progress and resumable state in GUI status text, CLI envelopes, and recovery prompts.
- Interruption/failure recovery cues, including the next safe action, are visible in GUI status text, CLI envelopes, and recovery prompts.
- Batch resume continues from recorded batch state and surfaces remaining retryable work instead of replaying completed items.
- GUI long-running scans and analysis tasks expose a clear stop/cancel path and reset the status text when stopped.
- CLI long-running commands exit cleanly on interruption with a structured envelope instead of a traceback.
- CLI long-running commands keep the recorded command name visible in the structured interruption envelope and point `next_safe_action` at the matching recovery workflow, including `dry-run`, `service-smoke`, and `batch-reconcile`.
- Root GUI is not regressed by a blind overwrite.
- Large-library strategy for about 500,000 files is implemented with real soak when feasible, or with faithful 500k synthetic validation that preserves DB/UI/manifest/recovery scaling risks.
- Wheel/source execution still works.
- `python scripts/verify_handoff.py` passes in the available environment.
- Commercial execution/manifest/integrity/rollback smoke passes on copied sample media.
- Final report separates proven facts from Windows-only gaps.

## Risk Register

- Data loss risk: any direct move/delete outside backend service gates is unacceptable.
- Scanner regression risk: replacing current `os.scandir` traversal with simple `rglob` may reintroduce reparse traversal and missing-file false marking.
- Report regression risk: replacing current `reports.py` may remove pagination needed for 500k files.
- Manifest regression risk: replacing current `manifest.py` may weaken candidate-review semantics.
- GUI regression risk: replacing root `photo_organizer_app.py` may remove existing workflow and review features.
- Packaging risk: `vendor/PIL` is not included in commercial-v1; removing it may weaken GUI reproducibility.
- Verification risk: Termux lacks some Windows GUI/media tooling; do not claim Windows release readiness from Termux-only checks.
- Build tooling risk: generated local `build/` can shadow a build frontend. Packaging proof must use a source export under `TMPDIR` with the declared build backend available.
- Scope risk: integration can sprawl. Keep each slice bounded and prove it before moving on.

## Working Notes

Append dated notes here when the plan changes.

- 2026-06-07: Initial goal document created from comparison of current repo, formal-v1, and commercial-v1. The strategy is to use commercial-v1 as backend safety foundation while preserving current repo GUI/report/scanner/vendor strengths.
- 2026-06-07: Historical baseline before implementation was clean: compileall passed, unittest discovery passed with 8 tests, `scripts/verify_handoff.py` passed, and `python -m photos --help` passed. An early restricted-environment packaging proof built `photos_triage-0.1.0-py3-none-any.whl` with `--no-build-isolation`; the later current-wheel proof built `photos_triage-0.2.0`.
- 2026-06-07: Accepted plan sharpened around current repo preservation, no blind commercial zip replacement, `PhotoOrganizerService` as the only mutation boundary, CLI commercial execution command merge while preserving `report-page`, 500k synthetic validation when real soak is infeasible, and explicit Windows-only gap tracking.
- 2026-06-07: Historical first integration slice evidence: compileall passed; `env PYTHONPATH=src python -m unittest discover -s tests` passed 16 tests before the large-library test was added; `python scripts/verify_handoff.py` passed with current dry-run artifacts and `service_smoke`; and the copied-fixture CLI smoke passed analyze, plan-create, plan-actions, plan-dry-run, plan-approve, plan-execute `--yes`, batch-manifest-validate `--verify-files`, integrity-check, batch-rollback `--yes`, and rollback-manifest validation. Packaging passed only with `--no-build-isolation` in this restricted environment. At that slice, the root GUI direct `shutil.move` boundary and 500k synthetic run remained open; both were addressed by later bounded work, while Windows-only validation remains open.
- 2026-06-07: Historical Worker E post-slice proof: the bounded synthetic test passed with 12,000 media rows, 12,000 plan actions, 12,000 batch items, and no physical media files; unittest discovery then passed 18 tests; focused compileall and owned-file diff checks passed; and `pip wheel --no-deps --no-build-isolation` built an early `photos_triage-0.1.0-py3-none-any.whl`. The 500k option had not yet run in that slice; it passed in later acceptance slices, and the current wheel proof is version `0.2.0`.
- 2026-06-07: Current bounded acceptance update: commercial zip SHA-256 was freshly verified; service-boundary GUI/CLI code and AST tests exist; the root direct `shutil.move` gap is repaired; full unittest discovery passed 36 tests; compileall passed; `python scripts/verify_handoff.py` passed after the root Tkinter wording correction and includes 36 unittest tests; copied-fixture execution completed 7 actions with 0 failures, produced a valid execution manifest, and integrity status was `ok`; copied-fixture rollback completed 7 actions with 0 failures and produced a valid rollback manifest; the original execution manifest correctly became file-invalid after rollback; the latest opt-in 500k synthetic public database paging/report/plan/batch test passed in 81.444 seconds on the current worktree; `photos_triage-0.2.0-py3-none-any.whl` was built and contains `photo_organizer_app.py`, `photos/services.py`, and console scripts `photos` and `photo-organizer`; the AGY executable exists, but no AGY-produced implementation is claimed. Windows-only release-readiness gaps remain, and overall completion is not claimed.
- 2026-06-07: Worker M minimal Windows validation slice added `verify_windows.ps1 -CommercialSmoke` for temp copied-fixture commercial execution/rollback validation. Worker N replaced the placeholder-only filesystem path with opt-in `verify_windows.ps1 -WindowsFilesystemProbes` coverage for `long_path_probe` and `case_collision_probe`; `junction_reparse_probe` and `permission_lock_probe` remain explicit skipped results. `-WindowsProbePlaceholders` remains only as a deprecated alias. This improves handoff executability but was not run in Termux because `pwsh` is unavailable here and does not claim Windows release readiness.
- 2026-06-07: Recursive goal wording tightened again so each pass explicitly compares current progress, completed items, and user-facing behavior against the success threshold, and revises the goal first when UX can be made clearer or safer before the next implementation slice.
- 2026-06-07: Recursive goal loop clarified: the goal must be re-read against current progress, UX, and validation evidence on each major pass; if that reveals a better validation or user-experience path, update the goal first, then rerun the implementation against the revised objective.
- 2026-06-07: The tightened recursive wording was validated with `python scripts/verify_handoff.py` and `git diff --check`; the proof still shows 36 unittest tests passing and no new code regressions from the documentation update.
- 2026-06-07: Latest audit confirmed the recursive wording already satisfies the current user-experience requirement; no additional goal text changes were needed beyond recording the proof and continuing to treat the Windows-only verifier gap as explicitly unproven here.
- 2026-06-07: Added visible progress, pause/resume state, and completion feedback for long-running scans, hashes, and batch execution to the trusted-execution contract so the UX requirement is now explicit in the goal, not only implied in the recursive guidance.
- 2026-06-07: Added an explicit acceptance criterion for visible progress/resumable state in user-facing surfaces, because the current code already exposes progress callbacks and `resume_batch`, but the goal needed a direct pass/fail line for that UX requirement.
- 2026-06-07: Added an explicit acceptance criterion for recovery state and next safe action in user-facing surfaces, because the current service envelope already exposes `next_safe_action` and interruption recovery metadata but the goal needed that UX cue stated directly.
- 2026-06-07: Tightened the UX acceptance criteria again so the goal names the surfaces that must show state: GUI status text, CLI envelopes, and recovery prompts.
- 2026-06-07: Added explicit resume continuity so the goal now requires resuming from recorded batch state and surfacing remaining retryable work instead of replaying completed items.
- 2026-06-07: Added an explicit GUI stop/cancel requirement for long-running scans and analysis tasks so interruption control is a first-class UX criterion, matching the existing stop_event-driven GUI behavior.
- 2026-06-07: Added a clean CLI interrupt path for long-running commands so Ctrl-C returns a structured failure envelope and exit code 130 instead of a traceback.
- 2026-06-07: Documented the CLI interrupt/recovery workflow in the Windows handoff docs and large-library gap ledger so operators know Ctrl-C now yields a structured recovery envelope and `batch-resume` continues recorded work.
- 2026-06-07: Confirmed the goal wording already covers the remaining resume/recovery UX surface; no further scope expansion was needed beyond documenting the CLI interrupt workflow.
- 2026-06-07: Added a batch-resume CLI interrupt test so the recorded command name survives Ctrl-C in the structured envelope and the resume workflow remains clear to operators.
- 2026-06-07: Refined the CLI interrupt envelope so interrupted `batch-resume` points `next_safe_action` back to `resume_batch`, then verified the new command-specific test and updated the handoff docs.
- 2026-06-07: Expanded CLI interruption recovery so `hash`, `batch-resume`, and `plan-execute` surface command-specific `next_safe_action` values, then verified the updated tests and docs.
- 2026-06-07: Extended the command-specific interrupt cue to `analyze` as well, so the structured recovery envelope now covers the non-mutating scan path that most users hit first.
- 2026-06-07: Extended command-specific interruption recovery to `service-smoke` and `batch-reconcile` as well, so the structured envelope covers the remaining long-running CLI recovery paths.
- 2026-06-07: GUI service-boundary failures were tightened so the warning/detail text and status text can carry the backend `next_safe_action` instead of hiding the next recovery step behind a generic error.
- 2026-06-07: The GUI recovery cue was made explicit in the goal and implementation so the root app now echoes backend recovery hints in both the status bar and the warning/detail text.
- 2026-06-07: Current proof refreshed: full unittest discovery now passes 47 tests, including the new recovery-text helper coverage, and the GUI recovery hint is represented in code, docs, and the acceptance ledger.
- 2026-06-07: Structured progress callbacks were added for hashing and batch execution, then wired into the CLI stderr progress frames and root GUI service execution status so long-running batch work now shows item counts instead of only a final completion message.
- 2026-06-07: Current proof refreshed again: full unittest discovery now passes 50 tests, including progress-reporting coverage for hashing, execution, CLI stderr progress, and root GUI service execution wiring.
- 2026-06-07: Structured progress callbacks were extended to scanning and analysis, then wired into the CLI stderr progress frames and service smoke path so long-running analysis now reports stage transitions as well as item counts.
- 2026-06-07: Current proof refreshed again: full unittest discovery now passes 53 tests, including progress-reporting coverage for scanning, analysis, hashing, execution, CLI stderr progress, and root GUI service execution wiring.
- 2026-06-07: Structured progress callbacks were extended to batch reconciliation and rollback, so batch recovery flows now emit the same structured progress frames as execute/resume.
- 2026-06-07: Current proof refreshed again: full unittest discovery now passes 59 tests, including progress-reporting coverage for scanning, analysis, hashing, dry-run, execute/resume/reconcile/rollback batch flows, CLI stderr progress, and root GUI service execution wiring.
- 2026-06-07: Scan, hash, and batch execution/recovery progress frames were throttled to a bounded cadence so large libraries can still show useful progress without per-item stderr spam; the progress proof still passes at 59 tests, the CLI dry-run and plan-dry-run paths now expose stage-based stderr feedback, and the root GUI progress formatter names analysis/dry-run stages explicitly and reports stage-specific transitions with runtime coverage.
