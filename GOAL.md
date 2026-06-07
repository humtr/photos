# Photos Trusted Windows App Goal

## Goal Prompt

Use this prompt to start the goal:

```text
/goal GOAL.md를 기준 문서로 삼아 photos 레포를 Windows에서 실제로 믿고 실행할 수 있는 사진 정리 앱으로 재구성한다. 2번 /sdcard/termux/import/photos/2/photos-commercial-v1.zip의 commercial backend 장점과 현재 레포의 GUI, 보고서, scanner, vendor/PIL 장점을 모두 통합하고, 양쪽의 단점은 개선한다. 이 문서의 요구사항은 반드시 충족해야 하는 최소 기준이며, 그것으로 한정하지 않는다. 구현 중 더 나은 안전성, 구조, 검증, 성능, 개발 방향이 발견되면 근거와 영향을 GOAL.md에 갱신해 목표를 재정렬한 뒤 반영한다. 단순 덮어쓰기는 금지하며, 최종 결과는 약 50만 개 파일 규모의 스캔, 분류, 계획, 검증, 정렬 작업에서 데이터 손실, 복구 불가 상태, UI/성능 병목, 검증 공백 없이 운영될 수 있어야 한다.
```

## Public Contract

Target: the current repository at `/data/data/com.termux/files/home/prj/photos`.

Primary source inputs:

- Current repository: existing GUI, reporting, scanner, manifest, vendor/PIL, and local project conventions.
- Commercial source bundle: `/sdcard/termux/import/photos/2/photos-commercial-v1.zip`.
- Verified extracted commercial reference, when present: `/data/data/com.termux/files/usr/tmp/photos-verify.DKTZIG/commercial/photos-commercial-v1`.

Output surface:

- A reconstructed `main` working tree whose backend and frontend form a trusted Windows photo organizer app.
- Updated source, tests, docs, and verification scripts.
- This `GOAL.md` as a living objective and acceptance ledger.

Success threshold:

- The commercial backend safety model is integrated.
- The current repository's useful GUI/report/scanner/vendor strengths are preserved or improved.
- The app is designed and verified toward trusted operation on about 500,000 files.
- Existing handoff validation and commercial execution/recovery validation both pass in the available environment.
- Remaining Windows-only or hardware-only gaps are explicit, bounded, and backed by a validation plan.

## Meaning Of Trusted Execution

"믿고 실행할 수 있다" means a normal Windows user can point the app at a large photo/video library and proceed without reasonable fear of silent data loss, unrecoverable mutation, UI lockup from loading the whole library, or unclear recovery state.

For this goal, trusted execution includes:

- Scanning about 500,000 files without unbounded memory growth.
- Hashing and analysis in bounded, resumable batches.
- Paginated or virtualized UI/report views; never require all rows in memory or on screen.
- Explicit approval gates before filesystem mutation.
- Dry-run and preflight before execution.
- Copy-temp-verify-replace-unlink semantics for moves.
- Batch manifests for every mutation batch.
- Manifest validation with optional file verification.
- Rollback, reconcile, resume, and integrity-check support.
- Clear handling of Windows long paths, case collisions, reparse points, permissions, source/archive overlap, partial failures, and interrupted execution.
- A frontend that uses the backend service boundary and does not bypass safety gates.

## Living Plan / Goal Realignment

This document is both the minimum requirement and the current source of truth. It is not a ceiling.

When implementation reveals a safer architecture, stronger validation, better frontend workflow, better large-library performance strategy, or clearer development direction, update this document with:

- The new observation.
- The evidence or failed proof axis.
- The proposed change.
- The affected files or interfaces.
- The updated validation predicate.

Then realign the implementation to the updated goal.

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

## Source Strengths To Preserve

Current repository strengths:

- Larger root Tkinter GUI in `photo_organizer_app.py`.
- Workflow, scan filter, duplicate insight, preview, bulk suggestion, metadata edit plan, and strategy comparison UI behavior.
- `report-page` CLI.
- Management report detail paging and detail limits.
- Scan error summary and recent scan error reporting.
- `candidate_manifest.json` plus legacy `deletion_manifest.json` compatibility.
- Candidate manifest fields such as `manifest_type`, `approval_state`, `approved_for_delete`, and `validation_required_before_delete`.
- `os.scandir` scanner traversal that avoids symlink/reparse directories.
- Conservative behavior that avoids marking files missing after scan errors.
- `vendor/PIL` for root GUI Pillow availability.

Commercial-v1 strengths:

- `PhotoOrganizerService` service boundary.
- Product store and contracts layer.
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

## Known Weaknesses To Improve

Do not merely choose one side's weakness.

- Current repository lacks real service/execution/rollback/recovery backend.
- Current repository validation is narrower: only 8 current tests.
- Current repository wheel does not include root GUI or vendor/PIL.
- Commercial-v1 lacks current `report-page`.
- Commercial-v1 has a simpler scanner traversal than current repo.
- Commercial-v1 lacks current candidate manifest richness.
- Commercial-v1 root GUI is smaller and lacks several current GUI workflows.
- Commercial-v1 zip does not include `vendor/PIL`.
- Neither side proves 500k-file Windows soak behavior yet.
- Neither side is a signed Windows installer.
- Neither side completes full GUI QA, RAW conversion quality validation, EXIF-write validation, or real Windows hardware validation.

## Protected Surfaces

Do not modify unless a later explicit task scopes them:

- `.git/`
- `.photos-data/`
- `_zip_check/`
- Existing untracked/generated evidence not required for the integration
- Historical commits, refs, reflogs, or object stores

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
- Record exact commercial source path and sha256 of the zip.
- Update this document if the source bundle differs from the previously inspected bundle.

### Phase 2: Add Commercial Backend Skeleton

Add commercial backend files that do not exist in the current repo:

- `src/photos/contracts.py`
- `src/photos/date_audit.py`
- `src/photos/duplicates.py`
- `src/photos/execution.py`
- `src/photos/services.py`
- `src/photos/store.py`
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
- `src/photos/manifest.py`: preserve current candidate manifest richness and legacy compatibility.
- `src/photos/reports.py`: preserve report paging/detail limits/scan error reporting; ensure service compatibility.
- `src/photos/pairing.py`: preserve current functions and add `find_duplicate_candidate_buckets`.
- `src/photos/dry_run.py`: preserve candidate manifest and report paging support; keep commercial service compatibility.
- `src/photos/cli.py`: preserve `report-page`; add commercial plan/execute/batch/manifest/reconcile/resume/integrity commands.
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
- Use AGY/Antigravity for frontend planning or implementation where helpful.
- Frontend must call backend service APIs for mutation workflows.
- Frontend must never move, delete, rename, or modify files directly outside backend-approved flows.

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

### Phase 6: Packaging And Windows Trust

- Keep source install and wheel install paths working.
- Document whether root GUI is part of wheel, script execution, or PyInstaller packaging.
- Keep Windows setup and verification scripts aligned with the final app surface.
- Document remaining Windows-only validation:
  - real hardware
  - long paths
  - NTFS/exFAT behavior
  - permissions
  - reparse points/junctions
  - PySide6/Tkinter rendering
  - installer/signing
  - RAW/EXIF external tool behavior

## Required Validation

Run the smallest faithful current checks after each major integration slice:

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

```bash
python -m pip wheel --no-deps --no-build-isolation --wheel-dir <tmp>/wheels .
```

If `pytest` is available:

```bash
python -m pytest
PYTHONPATH=src python -m pytest -q tests
```

If `pytest`, `tkinter`, `PySide6`, `exiftool`, or RAW tools are unavailable in Termux, classify that as an environment limitation and keep faithful backend checks running.

## Acceptance Criteria

The goal is complete only when all applicable criteria hold:

- Current repository strengths listed in this document are preserved or deliberately superseded by a better documented replacement.
- Commercial backend safety APIs and CLI are integrated.
- Filesystem mutation is service-boundary-only.
- Approval, dry-run, runtime confirmation, manifest, validation, rollback, reconcile, resume, and integrity-check gates exist and are tested.
- `report-page` remains available.
- Candidate and legacy manifests are both produced by dry-run.
- Scanner is reparse-safe and uses bounded transaction commits.
- Hashing is bounded-memory and resumable.
- Reports/review queues support large-library pagination/export.
- Root GUI is not regressed by a blind overwrite.
- Large-library strategy for about 500,000 files is implemented or documented with faithful synthetic validation.
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
- Scope risk: integration can sprawl. Keep each slice bounded and prove it before moving on.

## Working Notes

Append dated notes here when the plan changes.

- 2026-06-07: Initial goal document created from comparison of current repo, formal-v1, and commercial-v1. The strategy is to use commercial-v1 as backend safety foundation while preserving current repo GUI/report/scanner/vendor strengths.
