# GOAL Progress

## MVP Completion

- ✅ Phase 0: Release entrypoint and packaging gate
- ✅ Phase 1: Inventory performance and schema indexes
- ✅ Phase 2: Duplicate screening pipeline
- ✅ Phase 3: Date trust and metadata review pipeline
- ✅ Phase 4: Deterministic plan and execution hardening
- ✅ Phase 5: GUI workflow completion
- ⏳ Phase 6: Final release audit

## Current Phase Detail

- ⬜ code implemented
- ⬜ tests updated
- ⬜ local command verified
- ⬜ packaged exe verified
- ✅ GOAL_PROGRESS updated
- ⬜ commit pushed
- ⬜ remaining risk closed

## Phase 0: Release Entrypoint And Packaging Gate

State: ✅ PASS

Intent:
- Prove the packaged Windows GUI entrypoint launches without Python commands and without relative-import failure.

Changed files:
- `src/photos/app.py`
- `tests/test_release_smoke.py`

Evidence:
- Fixed packaged script execution by importing `photos.gui` through an absolute package import.
- Added release regression coverage for both module execution and script-style entry execution.
- Verified package build and packaged executable smoke in the current workspace.

Commands run:
- `python -m unittest tests.test_release_smoke` -> `Ran 4 tests ... OK`
- `python -m unittest discover -s tests` -> `Ran 29 tests ... OK`
- `python -m PyInstaller -y --name PhotoOrganizerV2 --noconsole --clean --distpath dist --workpath build --paths src src/photos/app.py` -> build complete in `dist`
- `dist\PhotoOrganizerV2\PhotoOrganizerV2.exe --smoke --db .test-tmp\release-exe-smoke.sqlite` -> `ok=true`, `command=gui-smoke`

Known risks:
- Generated build outputs remain untracked and must not be committed.

Next action:
- Start Phase 1: add SQLite indexes and query-plan evidence for 500k-scale workflows.

Commit evidence:
- `c01cdf8` `fix: package gui entrypoint as importable module`

## Phase 1: Inventory Performance And SQLite Indexes

State: ✅ PASS

Intent:
- Add real query-pattern indexes and query-plan tests so folder/media/duplicate/date workflows do not depend on broad table scans at large scale.

Changed files:
- `src/photos/store.py`
- `tests/test_phase1_indexes.py`
- `GOAL_PROGRESS.md`

Evidence:
- Added query-pattern indexes for media state/path, extension+size duplicate buckets, filename buckets, folder/name lookup, folder tree child lookup, duplicate candidate status/type lookup, and date/metadata audit lookup.
- Added `EXPLAIN QUERY PLAN` tests that assert the intended indexes are used for:
  - media state/path paging
  - suffix+size duplicate bucket lookup
  - filename bucket lookup
  - folder child lookup
  - metadata/date audit lookup
- Added a 400000-row synthetic media table test and verified bounded 10000-row page fetch.

Commands run:
- `python -m unittest tests.test_phase1_indexes` -> `Ran 5 tests ... OK`
- `python -m unittest tests.test_schema_contract` -> `Ran 4 tests ... OK`
- `python -m unittest tests.test_mvp6_gui` -> `Ran 5 tests ... OK`
- `python -m unittest discover -s tests` -> `Ran 34 tests ... OK`
- `Get-ChildItem -Path src\photos -Filter *.py -File | Sort-Object FullName | ForEach-Object { python -m py_compile $_.FullName }` -> no errors
- `python -m PyInstaller -y --name PhotoOrganizerV2 --noconsole --clean --distpath dist --workpath build --paths src src/photos/app.py` -> build complete in `dist`
- `dist\PhotoOrganizerV2\PhotoOrganizerV2.exe --smoke --db .test-tmp\phase1-exe-smoke.sqlite` -> `ok=true`, `command=gui-smoke`

Known risks:
- Phase 1 proves indexing and bounded page access. It does not yet rebuild duplicate candidate generation; that is Phase 2.

Next action:
- Start Phase 2: duplicate screening pipeline.

Commit evidence:
- `956ca60` `feat: add phase1 sqlite indexes and query plan tests`

## Phase 2: Duplicate Screening Pipeline

State: ✅ PASS

Intent:
- Replace shallow duplicate classification with bucketed screening and candidate generation that respects the evidence/trigger split in `GOAL.md`.

Changed files:
- `src/photos/duplicates.py`
- `src/photos/store.py`
- `tests/test_mvp2_duplicates.py`
- `tests/test_phase2_duplicate_screening.py`
- `tests/test_schema_contract.py`
- `GOAL_PROGRESS.md`

Evidence:
- Rebuilt duplicate analysis around indexed buckets:
  - `name_bucket`
  - `suffix_size_bucket`
  - `folder_pair_hotspot`
  - `camera_filename_iteration`
  - `transfer_derivative_hotspot`
- Added candidate types:
  - `probable_duplicate`
  - `renamed_duplicate_candidate`
  - `transferred_derivative`
  - `same_name_collision`
  - `folder_pair_burst`
  - `noisy_size_bucket`
- Populates `name_groups`, `candidate_members`, and `folder_pair_relations`.
- Stores evidence as valid JSON rather than `str(dict)`.
- Prevents noisy suffix+size buckets from exploding into global pairwise candidates.

Commands run:
- `python -m unittest tests.test_mvp2_duplicates tests.test_phase2_duplicate_screening` -> `Ran 5 tests ... OK`
- `python -m unittest tests.test_schema_contract tests.test_phase1_indexes` -> `Ran 9 tests ... OK`
- `python -m unittest discover -s tests` -> `Ran 38 tests ... OK`
- `Get-ChildItem -Path src\photos -Filter *.py -File | Sort-Object FullName | ForEach-Object { python -m py_compile $_.FullName }` -> no errors
- `python -m PyInstaller -y --name PhotoOrganizerV2 --noconsole --clean --distpath dist --workpath build --paths src src/photos/app.py` -> build complete in `dist`
- `dist\PhotoOrganizerV2\PhotoOrganizerV2.exe --smoke --db .test-tmp\phase2-exe-smoke.sqlite` -> `ok=true`, `command=gui-smoke`

Known risks:
- Phase 2 creates candidate groups and screening evidence only. It does not authorize deletion or exact duplicate claims.
- Date trust is still basic and belongs to Phase 3.

Next action:
- Start Phase 3: date trust and metadata review pipeline.

Commit evidence:
- `7d746a3` `feat: implement phase2 duplicate screening buckets`

## Phase 3: Date Trust And Metadata Review Pipeline

State: ✅ PASS

Intent:
- Detect photo clusters whose EXIF date is not trustworthy and route them to user review without writing metadata.

Changed files:
- `src/photos/metadata_audit.py`
- `src/photos/planning.py`
- `tests/test_phase3_date_trust.py`
- `GOAL_PROGRESS.md`

Evidence:
- `metadata_audit` now populates `date_audit_groups`, `date_audit_items`, and `metadata_edit_suggestions` for date trust review.
- Date evidence compares folder dates, filename dates, EXIF dates, filesystem mtime, filesystem ctime, neighboring filename sequence ranges, folder place summaries, and raw GPS context.
- Date conflict groups include:
  - `date_conflict_cluster`
  - `exif_untrusted_cluster`
  - `folder_date_conflict`
  - `filesystem_backup_date_suspected`
  - `missing_exif_cluster`
- Canonical dates are stored only as suggestions. No metadata write path was enabled.
- Approved metadata suggestions affect planning destination only and do not edit original metadata.

Commands run:
- `python -m unittest tests.test_phase3_date_trust` -> `Ran 5 tests ... OK`
- `python -m unittest discover -s tests` -> `Ran 43 tests ... OK`
- `Get-ChildItem -Path src\photos -Filter *.py -File | Sort-Object FullName | ForEach-Object { python -m py_compile $_.FullName }` -> no errors
- `python -m PyInstaller -y --name PhotoOrganizerV2 --noconsole --clean --distpath dist --workpath build --paths src src/photos/app.py` -> build complete in `dist`
- `dist\PhotoOrganizerV2\PhotoOrganizerV2.exe --smoke --db .test-tmp\phase3-exe-smoke.sqlite` -> `ok=true`, `command=gui-smoke`

Known risks:
- Phase 3 suggests canonical dates and planning overrides only. Actual metadata writing remains disabled and belongs to a separately approved workflow.
- Date trust uses deterministic local evidence. LLM interpretation remains advisory and is not required for this phase gate.

Next action:
- Start Phase 4: deterministic plan and execution hardening.

Commit evidence:
- `cef54ce` `feat: implement phase3 date trust review`

## Phase 4: Deterministic Plan And Execution Hardening

State: ✅ PASS

Intent:
- Harden dry-run and execution so every committed file action is preflighted, revalidated, and auditable before status is committed.

Changed files:
- `src/photos/planning.py`
- `src/photos/execution.py`
- `tests/test_phase4_execution_hardening.py`
- `GOAL_PROGRESS.md`

Evidence:
- `metadata_override` actions execute as `file_transfer`.
- `metadata_write_candidate` remains non-executable.
- Dry-run validates archive containment, root escape, destination collision, case-insensitive collision, path length, source existence, expected size+mtime, volume identity, reparse risk, and required approval.
- Execute revalidates the plan before each action.
- Same-volume file actions use verified move.
- Cross-volume file actions copy, verify, and retain the source.
- Manifest write failure prevents committed status.

Commands run:
- `python -m unittest tests.test_phase4_execution_hardening tests.test_mvp4_dry_run tests.test_mvp5_execution` -> `Ran 15 tests ... OK`
- `python -m unittest discover -s tests` -> `Ran 49 tests ... OK`
- `Get-ChildItem -Path src\photos -Filter *.py -File | Sort-Object FullName | ForEach-Object { python -m py_compile $_.FullName }` -> no errors
- `git diff --check` -> exit 0 with CRLF warnings only
- `python -m PyInstaller -y --name PhotoOrganizerV2 --noconsole --clean --distpath dist --workpath build --paths src src/photos/app.py` -> build complete in `dist`
- `dist\PhotoOrganizerV2\PhotoOrganizerV2.exe --smoke --db .test-tmp\phase4-exe-smoke.sqlite` -> `ok=true`, `command=gui-smoke`

Known risks:
- Phase 4 validates safety invariants in repo-local fixtures. Real `D:\` execution remains blocked by approval and dry-run gates.

Next action:
- Continue Phase 5: GUI workflow completion.

Commit evidence:
- `a6a5514` `feat: harden phase4 execution safety`

## Phase 5: GUI Workflow Completion

State: ✅ PASS

Intent:
- Make the GUI a usable shell over real services rather than a scaffold.

Changed files:
- `src/photos/services.py`
- `src/photos/gui.py`
- `tests/test_mvp6_gui.py`
- `tests/test_phase5_gui_workflow.py`
- `GOAL_PROGRESS.md`

Evidence:
- GUI actions exist for init, scan, summarize, enrich places, analyze duplicates, audit dates, export/import review, plan, approve execute, dry-run, and execute.
- `PhotoOrganizerService` delegates to v2 service modules for scan, summarize, place enrichment, duplicate analysis, date audit, folder packet export, review import, planning, dry-run, approvals, and execution.
- Execute remains disabled unless the latest dry-run passes and execute approval exists.
- Visible status/progress/failure/resume labels are updated by GUI handlers.
- Folder tri-state selection remains service-backed, and media pages are fetched through bounded page queries.
- PySide6-dependent widget tests are optional; a non-Qt handler test proves required GUI handlers call service actions without requiring a display runtime.

Commands run:
- `python -m unittest tests.test_phase5_gui_workflow tests.test_mvp6_gui` -> `Ran 9 tests ... OK (skipped=1)`
- `python -m unittest discover -s tests` -> `Ran 53 tests ... OK (skipped=1)`
- `Get-ChildItem -Path src\photos -Filter *.py -File | Sort-Object FullName | ForEach-Object { python -m py_compile $_.FullName }` -> no errors
- `git diff --check` -> exit 0 with CRLF warnings only
- `python -m PyInstaller -y --name PhotoOrganizerV2 --noconsole --clean --distpath dist --workpath build --paths src src/photos/app.py` -> build complete in `dist`
- `dist\PhotoOrganizerV2\PhotoOrganizerV2.exe --smoke --db .test-tmp\phase5-exe-smoke.sqlite` -> `ok=true`, `command=gui-smoke`

Known risks:
- One optional PySide6 widget test is skipped when PySide6 is unavailable in the test environment. Non-Qt handler tests cover service-call wiring.

Next action:
- Start Phase 6: final release audit.

Commit evidence:
- pending
