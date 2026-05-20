# Photo Organizer v2 MVP Completion Goal

## Mission

Build one usable Windows photo organizer MVP for a large fragmented photo/video drive.

The product target is a PySide6 Windows GUI backed by a deterministic SQLite service layer and CLI. The app must safely scan, analyze, plan, dry-run, and execute organization of files from a user-selected source root, defaulting to `D:\`, into a user-selected archive root, defaulting to `D:\PICTURES`.

This document is the single source of truth for the next implementation pass. The previous "MVP-1 through MVP-6" wording is superseded. There is one MVP. Work is divided into phases and gates only.

## Completion Rule

The MVP is complete only when every required phase gate below is satisfied with current evidence:

- code implemented
- tests added or updated
- required CLI/GUI behavior verified
- packaged Windows release smoke verified
- `GOAL_PROGRESS.md` updated with command output
- source/docs/tests committed and pushed
- no known blocking gap remains hidden or renamed as complete

Do not mark the MVP complete merely because unit tests pass. A test is evidence only for the behavior it actually exercises.

## Failure Lessons To Prevent Repetition

The previous pass failed in three ways:

- It treated phase completion as product completion.
- It accepted scaffold GUI behavior as if it were full GUI workflow behavior.
- It tested the Python module path but not the packaged executable path, allowing the release entrypoint error:
  `ImportError: attempted relative import with no known parent package`.

The new pass must make those failure modes impossible:

- Every phase has an acceptance gate and a release/UX impact note.
- GUI tests must prove service-backed behavior, not only smoke scaffolds.
- Release checks must build and run the packaged executable.
- Duplicate/date logic must be verified against the user's real decision model, not only toy fixtures.

## Progress Checklist Format

Use this exact checklist format in user progress reports and `GOAL_PROGRESS.md`.

```text
MVP Completion
- [PASS] Phase 0: Release entrypoint and packaging gate
- [RUNNING] Phase 1: Inventory performance and schema indexes
- [TODO] Phase 2: Duplicate screening pipeline
- [TODO] Phase 3: Date trust and metadata review pipeline
- [TODO] Phase 4: Deterministic plan and execution hardening
- [TODO] Phase 5: GUI workflow completion
- [TODO] Phase 6: Final release audit

Current Phase Detail
- [PASS] code implemented
- [PASS] tests updated
- [PASS] local command verified
- [PASS] packaged exe verified
- [PASS] GOAL_PROGRESS updated
- [PASS] commit pushed
- [TODO] remaining risk closed
```

Allowed states:

- `TODO`: not started
- `RUNNING`: actively being implemented
- `PASS`: verified with current evidence
- `BLOCKED`: cannot proceed; blocker must be named
- `RECHECK`: previously passed but invalidated by later findings

Avoid "MVP-1", "MVP-2", etc. Use `Phase` or `Gate`.

## Non-Negotiable Safety Rules

- Never move, delete, rename, overwrite, or modify real files under `D:\` unless the user explicitly approves that exact operation in the current session.
- Development and tests must use repo-local `.test-tmp` fixtures by default.
- Metadata writes are disabled by default.
- Permanent delete is not part of this MVP.
- Overwrite mode is forbidden.
- Dry-run must pass with `error_count == 0` before execute is enabled.
- CLI execution requires `--execute-approved`.
- GUI execution requires a passing latest dry-run plus explicit approval state.
- LLM output is advisory only. It must never directly mutate files, plans, metadata, or execution state.
- Hash-free duplicate candidates must never be called exact duplicates.
- Same-name collisions must be preserved separately unless the user explicitly approves a deterministic rename.
- Batch manifests and rollback references are required before a batch can be marked committed.

## Default Paths

- Source root: `D:\`
- Archive root: `D:\PICTURES`
- SQLite DB: `.photos-data/photos.sqlite`
- Review/export root: `.photos-data/review`
- Folder packet root: `.photos-data/folder-packets`
- Manifest root: `.photos-data/manifests`
- Test workspace: `.test-tmp`

The GUI and CLI must allow source/archive roots to be changed after startup.

## Architecture Boundary

Use the clean v2 service layer under `src/photos`.

Legacy files under `legacy/`, including `legacy/photo_organizer_app.py`, are reference-only. They must not be imported by v2 code. Useful behavior may be reimplemented in v2 services when it matches this document.

Required package surfaces:

- `photos.store`: SQLite schema, migrations, indexes, page queries, status transitions
- `photos.scan`: folder/media inventory, EXIF/GPS extraction, attention flags, missing-state separation
- `photos.place`: GPS/place cache and folder place summaries
- `photos.duplicates`: fast screening, candidate generation, evidence scoring
- `photos.metadata_audit`: date trust, metadata conflict clusters, metadata suggestions
- `photos.folder_packets`: LLM-ready folder packets
- `photos.llm_review`: schema-validated proposal import
- `photos.planning`: deterministic move/rename/keep/hold/metadata override planning
- `photos.execution`: dry-run, verified same-volume move, cross-volume copy/verify fallback, manifests
- `photos.cli`: stable JSON CLI contract
- `photos.gui` and `photos.app`: PySide6 GUI shell over the same service layer

The GUI must not contain independent business rules for scan, plan, dry-run, execute, duplicate classification, or metadata/date decisions.

## Required CLI Contract

Every command emits a stable JSON envelope to stdout.

Required commands:

- `photos init --db .photos-data/photos.sqlite`
- `photos scan --source D:\ --archive-root D:\PICTURES --db .photos-data/photos.sqlite`
- `photos summarize --db .photos-data/photos.sqlite`
- `photos enrich-places --db .photos-data/photos.sqlite --gps-mode summary`
- `photos analyze-duplicates --db .photos-data/photos.sqlite`
- `photos audit-dates --db .photos-data/photos.sqlite`
- `photos export-folder-packets --db .photos-data/photos.sqlite --output .photos-data/folder-packets --gps-mode summary`
- `photos import-folder-review --db .photos-data/photos.sqlite --input <review-json-or-dir>`
- `photos plan --db .photos-data/photos.sqlite --archive-root D:\PICTURES --strategy hybrid`
- `photos dry-run --db .photos-data/photos.sqlite --plan latest`
- `photos execute --db .photos-data/photos.sqlite --plan latest --batch latest --execute-approved`
- `photos status --db .photos-data/photos.sqlite`

Envelope fields:

- `schema_version`
- `ok`
- `command`
- `db`
- `started_at`
- `finished_at`
- `summary`
- `artifacts`
- `warnings`
- `errors`

Error entries include `code`, `message`, `phase`, optional `path`, and `recoverable`.

## Phase 0: Release Entrypoint And Packaging Gate

Goal: the packaged Windows app launches without Python commands and without relative-import failures.

Required work:

- Package entrypoint must be importable when run by PyInstaller as a script.
- Release tests must cover both `python -m photos.app --smoke` and script-style entry execution.
- Packaging script must build with PyInstaller.
- Packaged executable must pass smoke mode:
  `dist\PhotoOrganizerV2\PhotoOrganizerV2.exe --smoke --db .test-tmp\release-exe-smoke.sqlite`

Gate evidence:

- `python -m unittest tests.test_release_smoke`
- `python -m unittest discover -s tests`
- `python -m PyInstaller -y --name PhotoOrganizerV2 --noconsole --clean --distpath dist --workpath build --paths src src/photos/app.py`
- `dist\PhotoOrganizerV2\PhotoOrganizerV2.exe --smoke --db .test-tmp\release-exe-smoke.sqlite`
- commit and push

## Phase 1: Inventory Performance And SQLite Indexes

Goal: the DB supports 50만 file scale without table-scan-heavy common queries.

Required work:

- Add indexes for real query patterns, including:
  - `media_files(scan_root_id, existence_state, path)`
  - `media_files(scan_root_id, suffix, size_bytes)`
  - `media_files(scan_root_id, name)`
  - `media_files(scan_root_id, folder_path, name)`
  - `folder_nodes(scan_root_id, parent_path, path)`
  - duplicate/audit tables by `scan_root_id`, status, and group type
- Add tests using `EXPLAIN QUERY PLAN` for the most important page/filter queries.
- Preserve write performance by avoiding unnecessary low-cardinality standalone indexes.
- Ensure folder-first scans use `os.scandir` or equivalent efficient traversal.
- Keep reparse point, hidden/system/cache folder attention flags.

Gate evidence:

- index existence tests
- query-plan tests for folder page, media page, duplicate bucket, date audit lookup
- synthetic DB paging test with at least 400000 media rows or a documented bounded equivalent that proves no all-row preload

## Phase 2: Duplicate Screening Pipeline

Goal: implement fast candidate generation before expensive comparisons.

The user's rules are valid but must be separated into evidence and screening triggers.

File-level evidence:

1. filename equality
2. extension + size equality
3. EXIF shooting date when trusted
4. folder name/date/place context
5. filesystem date only as weak backup/copy evidence

Screening triggers:

6. one duplicate-like file inside a folder pair suggests the rest of the folder pair needs review
7. camera filename iteration can create same-name collisions and must trigger collision review
8. transferred/compressed photo patterns trigger derivative review
9. sequential shooting/folder-pair bursts trigger hotspot review

Required work:

- Build indexed buckets:
  - `name_bucket`
  - `suffix_size_bucket`
  - `folder_pair_hotspot`
  - `camera_sequence_collision`
  - `transfer_derivative_hotspot`
- Do not compare every file pair globally.
- Add `same_ext_size_bucket` or equivalent candidate group for renamed duplicate candidates.
- Add noisy bucket handling for tiny/common files and thumbnails.
- Store explanations in valid JSON, not `str(dict)`.
- Populate GOAL tables consistently:
  - `name_groups`
  - `duplicate_candidates`
  - `candidate_members`
  - `folder_pair_relations`
- Candidate types:
  - `probable_duplicate`
  - `renamed_duplicate_candidate`
  - `transferred_derivative`
  - `same_name_collision`
  - `folder_pair_burst`
  - `requires_review`
  - `noisy_size_bucket`
- Never label hash-free results as exact duplicates.

Gate evidence:

- fixtures for same filename + same size
- fixtures for same extension + same size + different filename
- fixtures for same filename + different size/date/place collision
- fixtures for transferred/compressed folder patterns
- fixtures for folder-pair burst hotspot
- performance test proving candidate generation is bucketed, not global pairwise

## Phase 3: Date Trust And Metadata Review Pipeline

Goal: detect photo clusters whose EXIF date is not trustworthy and route them to user review.

Required work:

- Compare:
  - EXIF date
  - filename date
  - folder name date
  - filesystem mtime/ctime
  - neighboring sequence dates
  - folder place/GPS context
- Create date trust groups:
  - `date_conflict_cluster`
  - `exif_untrusted_cluster`
  - `folder_date_conflict`
  - `filesystem_backup_date_suspected`
  - `missing_exif_cluster`
- Populate:
  - `date_audit_groups`
  - `date_audit_items`
  - `metadata_edit_suggestions`
- Generate proposed canonical date only as a suggestion.
- Metadata writes remain disabled by default.
- User may approve:
  - planning-only `metadata_override`
  - later separate `metadata_write_candidate`
- LLM may propose date/place interpretation, but app validation and user approval are mandatory.

Gate evidence:

- fixture where EXIF date conflicts with folder date
- fixture where filesystem date is a backup/copy date
- fixture where filename date is stronger than missing EXIF
- fixture where user-approved metadata override changes planning destination but does not edit original metadata

## Phase 4: Deterministic Plan And Execution Hardening

Goal: plans and file custody are safe before GUI polish.

Required work:

- Plan actions:
  - `move`
  - `rename_move`
  - `keep_separate`
  - `hold`
  - `metadata_override`
  - `metadata_write_candidate`
- Same-name collisions default to `keep_separate` or deterministic rename, never delete.
- Dry-run validates:
  - archive containment
  - root escape
  - destination collision
  - case-insensitive collision
  - path length
  - source existence
  - expected size/mtime
  - volume identity
  - reparse point/junction risk
  - required approvals
- Execute revalidates every safety condition immediately before move/copy.
- Same-volume default is verified move.
- Cross-volume fallback is bounded copy/verify/source-cleanup, with cleanup disabled unless separately approved.
- Manifest and rollback reference are mandatory.

Gate evidence:

- dry-run blocks every unsafe fixture
- manifest has all required fields
- manifest write failure prevents committed status
- source-change-before-execute holds the item
- destination collision before execute holds and stops the batch
- same-volume and cross-volume behaviors covered by tests

## Phase 5: GUI Workflow Completion

Goal: the GUI is a usable shell over real services, not a scaffold.

Required work:

- GUI can run:
  - init
  - scan
  - summarize
  - enrich places
  - analyze duplicates
  - audit dates
  - export/import LLM review
  - plan
  - dry-run
  - execute
- GUI folder review:
  - three panels: all, included, excluded/held
  - tri-state selection
  - expanding/collapsing never toggles selection
  - included/excluded updates without resetting tree expansion
- GUI tables:
  - folder aggregates
  - media pages
  - duplicate candidate groups
  - folder-pair bursts
  - date conflict clusters
  - LLM proposals
  - approval states
- Representative preview loads only selected rows.
- Execute button is disabled unless latest dry-run passes and approvals exist.
- Progress, cancellation, failure reason, and resume status are visible.
- Open Design theme integration remains optional and non-blocking.

Gate evidence:

- GUI service tests proving buttons call real services
- GUI smoke with populated DB
- synthetic 400000-row DB opens folder review and pages media without all-row preload
- packaged exe smoke

## Phase 6: Final Release Audit

Goal: prove the MVP as a single product result.

Required checks:

```powershell
python -m py_compile src\photos\*.py
python -m unittest discover -s tests
python -m photos.app --smoke --db .test-tmp\gui-smoke.sqlite
python -m PyInstaller -y --name PhotoOrganizerV2 --noconsole --clean --distpath dist --workpath build --paths src src/photos/app.py
dist\PhotoOrganizerV2\PhotoOrganizerV2.exe --smoke --db .test-tmp\release-exe-smoke.sqlite
```

On Windows PowerShell, if the wildcard compile command is not expanded as intended, use:

```powershell
Get-ChildItem -Path src\photos -Filter *.py -File | Sort-Object FullName | ForEach-Object { python -m py_compile $_.FullName }
```

Final audit must also verify:

- no v2 import from `legacy/photo_organizer_app.py`
- no generated artifacts committed:
  - `.test-tmp/`
  - `.photos-data/`
  - `build/`
  - `dist/`
  - `__pycache__/`
  - `PhotoOrganizerV2.spec` unless intentionally maintained
- release exe launches
- current `GOAL_PROGRESS.md` contains every phase gate result
- final commit and push are complete

## GOAL_PROGRESS.md Requirements

Each phase entry must include:

- state: `TODO`, `RUNNING`, `PASS`, `BLOCKED`, or `RECHECK`
- intent
- changed files
- exact commands run
- exact result summary
- known risks
- next action
- commit hash after push

Do not write "complete" without a command or artifact proving the claim.

## Immediate Next Work

Start from Phase 1 unless Phase 0 has not been committed and pushed.

Implementation order:

1. Fix and verify release entrypoint.
2. Add SQLite indexes and query-plan tests.
3. Rebuild duplicate screening as bucketed candidate generation.
4. Rebuild date trust and metadata review around conflict clusters.
5. Wire planner to duplicate/date approvals and metadata overrides.
6. Replace GUI scaffold actions with real service calls.
7. Run packaged release audit.
8. Commit and push each phase gate.

