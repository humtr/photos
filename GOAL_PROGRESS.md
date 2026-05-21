# GOAL Progress

## MVP Completion

- ✅ Phase 0: Release entrypoint and packaging gate
- ✅ Phase 1: Inventory performance and schema indexes
- ✅ Phase 2: Duplicate screening pipeline
- ✅ Phase 3: Date trust and metadata review pipeline
- ⏳ Phase 4: Deterministic plan and execution hardening
- ⬜ Phase 5: GUI workflow completion
- ⬜ Phase 6: Final release audit

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
- pending
