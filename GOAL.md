# Photo Organizer v2 Implementation Goal

## Mission

Build Photo Organizer v2 as a clean new implementation. Do not extend the current Tkinter prototype as the product architecture. The program must organize a large Windows photo/video drive, initially `D:\`, into a controlled archive root, initially `D:\PICTURES`, with deterministic local code responsible for all file custody and execution.

The app must work without LLM assistance. LLM use is optional and limited to folder semantics, folder hierarchy interpretation, organizing philosophy, folder-pair duplicate insight, and metadata/date review suggestions. LLM output is never an executable command. Every file move, rename, cleanup action, metadata action, dry-run decision, and execution decision must be validated locally by the app and explicitly approved by the user.

The first implementation target is a CLI-first core with SQLite as the internal source of truth. A PySide6 GUI will then be built on the same service layer. CLI-first is an implementation sequence, not a reduction of the product goal: the final product is a Windows GUI application for safe, large-scale photo organization.

## Build Philosophy

- This is a clean build. Existing files may be read for product context, but the new implementation must be structured around the v2 architecture in this document.
- `photo_organizer_app.py` must not be imported by v2 code. Useful concepts must be reimplemented through the v2 service layer.
- Folder structure is the primary unit of human meaning. File custody is the primary unit of data safety.
- The app must be able to complete scan, analysis, plan, dry-run, and same-volume verified move without LLM.
- LLM improves folder interpretation and strategy reporting, but the app must never require LLM for deterministic safety.
- User approval is a first-class state, not a dialog-only side effect.
- Long operations must be resumable and observable through SQLite state and report artifacts.
- GUI actions must call the same services as CLI commands. GUI must not implement separate business rules.

## Success Criteria

The goal is complete only when all of the following are true:

- A v2 package structure exists under `src/photos` and does not depend on the current Tkinter prototype.
- CLI commands can scan a large source tree, store folder/media inventory in SQLite, resume safely, and report progress.
- The system extracts EXIF date and GPS data where available and creates folder-level place summaries.
- Duplicate and collision intelligence works without full-drive SHA-256 hashing.
- The system can produce LLM-ready folder packets and import LLM review suggestions as non-executable proposals.
- Deterministic planning creates move/rename/keep/hold actions under the configured archive root.
- Dry-run blocks execution if any root escape, overwrite, collision, source change, path issue, missing approval, or unsafe transfer condition exists.
- Same-volume verified move works in test fixtures and writes DB status plus batch manifests.
- Cross-volume copy/verify/source cleanup exists as a safe fallback path, but same-volume move is the default for `D:\ -> D:\PICTURES`.
- A PySide6 GUI can drive scan, analysis, folder review, plan, dry-run, and approved execution through the same service layer.
- Tests cover safety-critical behavior, and all acceptance commands listed in this document pass.
- `GOAL_PROGRESS.md` records each MVP result, verification output, known risks, and remaining work.

## Non-Negotiable Safety Rules

- Never move, delete, rename, or modify real files under `D:\` during development unless the user explicitly approves that exact operation in the current session.
- Development and tests must use repo-local `.test-tmp` fixtures by default.
- Dry-run error count must be `0` before any execute command is allowed.
- Execution must be disabled unless the CLI receives an explicit execution flag such as `--execute-approved`.
- GUI execute controls must remain disabled unless the latest dry-run is passing and relevant approvals exist.
- Destination paths must stay inside the configured archive root.
- Destination overwrite is forbidden. Do not implement overwrite mode in v2 MVP.
- Root escape, reparse point loops, junction traversal risk, inaccessible files, path length errors, source file changes, and destination collisions must produce held/failed statuses, not best-effort execution.
- LLM suggestions must be stored as proposals requiring user approval. They must not directly mutate plans or execution actions.
- Full-drive SHA-256 hashing must not be a default or required step.
- Hash-free duplicate candidates must never be labeled as exact duplicates. Use `probable_duplicate`, `transferred_derivative`, `same_name_collision`, `folder_pair_burst`, or `requires_review`.
- Same-name collision files must not be deleted. They must be preserved separately, usually through deterministic rename.
- Metadata writes are disabled by default. Metadata suggestions may be used as planning overrides before any file metadata is changed.
- Batch manifests must be written before a batch can be marked committed.
- If manifest writing fails, the batch remains failed/held.
- If post-move verification fails, the batch remains failed/held and no further destructive action may proceed.

## Clean Build Boundary

- Treat the current Tkinter prototype as a product sketch and behavior reference only.
- Existing `src/photos` modules may be replaced or heavily rewritten.
- Preserve useful tests or concepts only when they match this document.
- `_zip_check/`, `__pycache__/`, `.test-tmp/`, `build/`, and `dist/` are not v2 source and must not be committed as implementation work.
- Vendor files under `vendor/` should not be modified unless packaging requirements make it necessary.
- If current implementation behavior conflicts with this document, this document wins.

## Default Paths and Runtime Assumptions

- Default source root: `D:\`
- Default archive root: `D:\PICTURES`
- Default SQLite DB: `.photos-data/photos.sqlite`
- Default review/export directory: `.photos-data/review`
- Default LLM packet directory: `.photos-data/folder-packets`
- Default manifest directory: `.photos-data/manifests`
- Default test workspace: `.test-tmp`
- CLI and GUI must allow source and archive roots to be changed after program start.
- Same-volume move is expected for the default `D:\ -> D:\PICTURES` case.
- Cross-volume transfer must be detected and routed to bounded copy/verify/source cleanup.
- GPS packet mode default: `summary`
- GPS packet modes: `none`, `summary`, `raw`
- Reverse geocoding default: cache-first. If no provider is configured, keep GPS coordinate summaries and continue.

## User-Facing Product Requirements

The final product must be a Windows GUI application, even though implementation starts with CLI.

GUI requirements:

- Source root and archive root can be selected after app launch.
- Folder structure is presented before large file lists.
- Folder review uses a three-panel model:
  - all folders
  - included/target folders
  - excluded/held folders
- Folder rows support tri-state selection: selected, unselected, partially selected.
- Parent selection propagates to children; mixed children show partial state.
- Expanding/collapsing tree nodes must not toggle selection.
- Tables must be paginated or lazy-loaded from SQLite.
- Candidate duplicate groups, folder-pair burst groups, metadata audit groups, and LLM proposals must have approval UI.
- Representative photo and metadata preview must load only for selected rows.
- Dry-run status and execute availability must be visible.
- Execute remains disabled when dry-run has errors or required approvals are missing.
- GUI must expose progress, cancellation, failure reason, and resume status for long operations.
- Folder tree views must be driven by folder aggregates and must not preload every media row.
- File, duplicate, audit, and proposal tables must use SQLite-backed pagination. Default page size is `10000` rows unless the UI requires a smaller page for responsiveness.
- GUI performance tests must prove that a synthetic database with at least `400000` media rows can open folder review and page through table data without loading all rows into memory.

Windows application and release requirements:

- MVP-6 must include a documented GUI launch path for development and for packaged Windows use.
- The packaged app may be a portable executable or installer, but it must launch without requiring the user to run Python commands.
- Packaged GUI must allow source/archive root selection after startup.
- Packaged GUI must keep database, reports, logs, and manifests in user-selected or app-data locations, not accidentally inside source code or build folders.
- Normal GUI use must not require a visible console window. Logs and error details must remain accessible through files and UI status panels.

CLI-first does not mean GUI-last in product quality. CLI services must be built so the GUI can be a reliable shell over the same state and commands.

## Folder-First Operating Model

The app must not start by trying to display every photo row. The primary workflow is folder-first:

1. Scan folder tree and basic inventory.
2. Aggregate counts, bytes, extensions, date ranges, and GPS availability by folder/subtree.
3. Extract representative samples for folder meaning.
4. Build folder-pair duplicate/derivative/collision insights.
5. Export optional LLM packets for folder semantics and organizing strategy.
6. Import LLM proposals as pending suggestions.
7. Build deterministic organize plans from approved settings and proposals.
8. Dry-run and execute through the local engine.

The app must distinguish safety/attention patterns from semantic judgments. Safety patterns can be detected locally. Semantic folder roles for organizing philosophy should be left to LLM/user review.

## Exclusion and Attention Patterns

The scanner and UI must recognize known system/cache/sync patterns as attention signals. These are not final semantic labels and must be user-overridable.

Attention patterns include:

- `.thumbnails`
- `$RECYCLE.BIN`
- `System Volume Information`
- `OneDriveTemp`
- `.tmp` and temp-like folders
- cloud/cache/sync folders such as OneDrive, Google Photos, Samsung Gallery, download caches, thumbnail caches
- hidden/system folders
- reparse points, junctions, symlinks, mounted-volume boundaries

Required behavior:

- Attention folders are visible in folder review unless explicitly hidden by the user.
- They default to held/excluded from execution plans unless the user approves inclusion.
- LLM packets may include that a folder was flagged by safety pattern, but must not include app-generated semantic roles such as "backup" or "original".
- Execution plans must never include system/cache folders unless explicitly approved.

## Target Architecture

Implement v2 as a service-oriented package.

- `photos.store`: SQLite connection, schema, migrations, page queries, status transitions
- `photos.scan`: folder/media inventory, EXIF date/GPS extraction, extension/size/date aggregation
- `photos.place`: GPS cache, reverse geocoding adapter, folder-level dominant place summaries
- `photos.duplicates`: filename/size/date/folder-pair/sequence duplicate intelligence
- `photos.metadata_audit`: filename date, folder date, EXIF date, filesystem date inconsistency analysis
- `photos.folder_packets`: LLM-ready packet export and chunking
- `photos.llm_review`: LLM review JSON import, schema validation, approval staging
- `photos.planning`: deterministic plan generation for move/rename/keep/hold/metadata override actions
- `photos.execution`: dry-run, same-volume verified move, cross-volume bounded copy/verify/source cleanup, manifests
- `photos.cli`: CLI entrypoints for the v2 workflow
- `photos.app`: PySide6 GUI built on the same service layer

Do not let GUI code own business rules. GUI must call the same service layer used by CLI.

## SQLite Data Model

Implement migrations with schema versioning. Use explicit status values rather than ad hoc strings.

Inventory:

- `scan_roots`: `id`, `source_root`, `archive_root`, `created_at`, `active`, `settings_json`
- `scan_runs`: `id`, `scan_root_id`, `status`, `started_at`, `finished_at`, `folder_count`, `file_count`, `error_count`, `details_json`
- `scan_errors`: `id`, `scan_run_id`, `path`, `phase`, `error`, `created_at`
- `folder_nodes`: `id`, `scan_root_id`, `path`, `parent_path`, `depth`, `direct_file_count`, `subtree_file_count`, `direct_bytes`, `subtree_bytes`, `extension_counts_json`, `date_ranges_json`, `attention_flags_json`, `last_seen_scan_id`
- `media_files`: `id`, `scan_root_id`, `path`, `folder_path`, `name`, `stem`, `suffix`, `media_type`, `size_bytes`, `ctime_ns`, `mtime_ns`, `exif_datetime`, `gps_lat`, `gps_lon`, `existence_state`, `last_seen_scan_id`
- `folder_samples`: `id`, `folder_path`, `sample_type`, `path`, `name`, `size_bytes`, `dates_json`, `gps_place_id`

Place:

- `places`: `id`, `lat_bucket`, `lon_bucket`, `label`, `provider`, `confidence`, `raw_json`, `updated_at`
- `folder_place_summaries`: `folder_path`, `dominant_places_json`, `gps_file_count`, `non_gps_file_count`, `updated_at`

Duplicate and collision intelligence:

- `name_groups`: `id`, `normalized_name`, `member_count`, `size_variants`, `date_range_json`, `status`
- `duplicate_candidates`: `id`, `group_type`, `confidence`, `recommended_action`, `reason_json`, `created_at`
- `candidate_members`: `candidate_id`, `path`, `member_role`, `evidence_json`
- `folder_pair_relations`: `id`, `folder_a`, `folder_b`, `matched_name_count`, `same_size_count`, `same_exif_count`, `derivative_count`, `collision_count`, `dominant_place`, `date_range_json`, `confidence`, `reason_json`

Metadata/date audit:

- `date_audit_groups`: `id`, `folder_path`, `issue_type`, `confidence`, `evidence_json`, `status`
- `date_audit_items`: `group_id`, `path`, `filename_date`, `folder_date`, `exif_date`, `filesystem_date`, `proposed_canonical_date`, `status`
- `metadata_edit_suggestions`: `id`, `target_type`, `target_path`, `proposed_value`, `source`, `status`, `reason_json`

LLM review:

- `llm_packets`: `id`, `packet_type`, `path`, `root_folder`, `created_at`, `row_count`, `sha256`, `settings_json`
- `llm_reviews`: `id`, `review_type`, `path`, `status`, `imported_at`, `summary_json`
- `llm_review_items`: `id`, `review_id`, `target_type`, `target_path`, `proposal_type`, `proposal_json`, `confidence`, `status`

Planning and execution:

- `organize_plans`: `id`, `strategy`, `archive_root`, `status`, `created_at`, `summary_json`
- `plan_actions`: `id`, `plan_id`, `source_path`, `destination_path`, `action_type`, `expected_size`, `expected_mtime_ns`, `status`, `reason_json`
- `execution_batches`: `id`, `plan_id`, `transfer_method`, `estimated_bytes`, `status`, `started_at`, `finished_at`, `summary_json`
- `batch_items`: `id`, `batch_id`, `plan_action_id`, `source_path`, `destination_path`, `status`, `error_code`, `error_message`
- `transfer_verifications`: `id`, `batch_item_id`, `destination_size`, `destination_mtime_ns`, `verification_status`, `verified_at`, `details_json`
- `batch_manifests`: `id`, `batch_id`, `manifest_path`, `manifest_sha256`, `item_count`, `total_bytes`, `created_at`
- `approvals`: `id`, `approval_type`, `target_type`, `target_id`, `approved`, `note`, `approved_at`

Operational artifacts:

- `reports`: `id`, `report_type`, `path`, `sha256`, `created_at`, `summary_json`

Required status values:

- `existence_state`: `seen`, `not_seen_this_scan`, `confirmed_missing`
- `duplicate_candidates.group_type`: `probable_duplicate`, `transferred_derivative`, `same_name_collision`, `folder_pair_burst`, `requires_review`
- `plan_actions.action_type`: `move`, `rename_move`, `keep_separate`, `hold`, `metadata_override`, `metadata_write_candidate`
- `transfer_method`: `same_volume_move`, `copy_verify_cleanup`
- `batch status`: `planned`, `dry_run_passed`, `running`, `verified`, `committed`, `failed`, `held`, `cancelled`
- `item status`: `pending`, `moved`, `copied`, `verified`, `source_changed`, `collision`, `failed`, `held`
- `llm_review_items.status`: `pending_approval`, `approved`, `rejected`, `superseded`

## Duplicate and Collision Intelligence

Do not implement default full-drive SHA-256 hashing. The default duplicate engine is evidence-based and folder-aware.

Evidence inputs:

- filename equality
- file size equality or consistent size ratio
- EXIF datetime equality/proximity
- filesystem date proximity
- folder-name date equality/conflict
- folder-level dominant place equality/conflict
- sequence continuity within folder pairs
- repeated behavior across many files in the same folder pair
- transferred/compressed image pattern: same name/date but consistently smaller size
- camera filename iteration pattern: same name but different date/place/folder context

Classification:

- `probable_duplicate`: name, size, date/place, and sequence context strongly match
- `transferred_derivative`: same or related name/date but smaller compressed/transferred copy pattern
- `same_name_collision`: name matches but date/place/size/folder context indicates separate photos
- `folder_pair_burst`: folders show large repeated duplicate/derivative/collision patterns
- `requires_review`: weak or conflicting evidence

Actions:

- `probable_duplicate`: canonical candidate plus cleanup proposal, not automatic delete
- `transferred_derivative`: derivative cleanup proposal, user approval required
- `same_name_collision`: rename/keep separate; deletion forbidden
- `folder_pair_burst`: LLM and user review target; app still validates file actions
- `requires_review`: hold

Optional targeted content verification may be added for high-risk candidates, but it must not become a required full-drive hash step.

## Metadata and Date Audit

Analyze date consistency at folder-group level.

Inputs:

- filename date
- folder-name date
- EXIF datetime
- filesystem ctime/mtime
- folder dominant place
- neighboring folder date/place patterns

Detect:

- folder name date disagrees with most EXIF dates
- filesystem date is clearly backup/copy date rather than shooting date
- folder contains a dominant event/place/date cluster plus outliers
- filenames encode date ranges inconsistent with parent folder
- likely metadata override needed for planning
- possible metadata write candidate, disabled by default

LLM may propose canonical date/place interpretation for a folder group. The app must store this as `metadata_override` or `metadata_write_candidate`. Metadata writing requires separate approval and is not part of the default MVP execution.

## LLM Folder and Metadata Review Contract

LLM packets must contain objective data and app-generated candidate groups. Do not include app-assigned semantic folder roles as prompt inputs.

Include:

- folder tree structure
- file/photo/video/extension counts and bytes
- attention flags for safety/system/cache/sync patterns
- folder-name, filename, EXIF, and filesystem date ranges
- representative file samples: oldest, newest, largest, and extension representatives
- GPS dominant place summary
- folder-pair duplicate/derivative/collision summaries
- date inconsistency folder groups
- rename and metadata override candidate groups

Packet output layout:

- `folder_semantics_index.json`
- `folder_packets/<top-folder-safe-name>.json`
- split large top folders into subtree packets if needed

LLM import files:

- `strategy_report.md`
- `folder_semantic_review.json`
- `metadata_review.json`
- `duplicate_review.json`

Import rules:

- Validate schema before storing.
- Reject path entries outside known scan roots.
- Store proposals in `llm_review_items`.
- Mark proposals `pending_approval` by default.
- Do not mutate `plan_actions` until user approval is recorded.

LLM report quality requirements:

- `strategy_report.md` must not be a simple echo of input rows.
- It must explain the proposed organizing philosophy.
- It must compare date-based, place-based, source-preserving, event-based, and hybrid strategies when relevant.
- It must identify likely canonical folder groups and lower-priority derivative/backup/cache groups.
- It must explain folder-pair duplicate bursts and same-name collision risks.
- It must list items that require user review before execution.
- It must distinguish strong recommendations from low-confidence observations.

## Transfer and Execution Model

Default for `D:\ -> D:\PICTURES` is same-volume verified move.

Same-volume move flow:

1. Confirm source and destination are on the same volume.
2. Dry-run validates root containment, path length, destination collision, overwrite risk, permissions, source existence, and expected size/mtime.
3. Execution requires `--execute-approved`.
4. Revalidate source immediately before move.
5. Move the file.
6. Verify destination exists and source no longer exists.
7. Verify destination size and mtime.
8. Write batch manifest.
9. Mark batch/item committed only after manifest is written.

Cross-volume fallback:

1. Detect different volume or same-volume move unavailable.
2. Measure free space on destination root.
3. Calculate reserve.
4. Select bounded batch that fits usable space.
5. Copy.
6. Verify size/mtime.
7. Cleanup source only after verification.
8. Write manifest and DB status.

Dry-run must report:

- total actions
- runnable actions
- held actions
- errors by category
- destination collisions
- root escape attempts
- same-volume vs cross-volume transfer method
- cross-volume capacity checks where applicable

Execution must stop on any batch-level failure. Failed and successful batches must be clearly separated in DB and manifests.

## Windows Path, Volume, and Transfer Invariants

Same-volume move is safe only when the app proves it through Windows-aware path and volume checks. Do not rely only on drive-letter string comparison.

Required invariants:

- Normalize paths through Windows path rules before containment, collision, or equality checks.
- Compare paths case-insensitively for collision detection while preserving original casing for display and manifests.
- Resolve archive-root containment after normalization and before every planned action.
- Detect volume identity using Windows volume information such as volume root and volume serial number, or an equivalent reliable API.
- Store detected source/archive volume identity in dry-run reports and batch manifests.
- Treat reparse points, junctions, symlinks, and mounted-volume boundaries as attention or hold conditions unless explicitly supported and approved.
- Same-volume transfer method is allowed only when source file and destination root resolve to the same volume identity at dry-run and again immediately before execution.
- If volume identity cannot be proven, route to cross-volume fallback or hold the action.
- Destination existence check and collision check must happen immediately before move/copy.
- Overwrite must remain forbidden even when a platform API could replace the destination.
- Long path support must be tested with fixture paths near Windows limits.
- All path validation must be repeated during execute; dry-run results are necessary but not sufficient.

## Operational Artifacts

SQLite is the internal source of truth, but the app must also emit durable review and execution artifacts.

Required artifacts:

- scan summary report
- folder inventory export
- duplicate intelligence report
- date/metadata audit report
- LLM folder packets
- imported LLM review summaries
- organize plan report
- dry-run report
- batch manifest
- execution log
- rollback reference

Rules:

- Reports must be deterministic and re-creatable from SQLite state where practical.
- Batch manifest records what was attempted, what succeeded, what failed, and what verification was performed.
- Execution log records chronological events.
- Rollback reference is a manual recovery guide, not an automatic restore engine.
- Missing artifacts must block execution only when they are required for the current phase.

Manifest required fields:

- `schema_version`
- `manifest_id`
- `plan_id`
- `batch_id`
- `scan_run_id`
- `source_root`
- `archive_root`
- `transfer_method`
- `source_volume`
- `archive_volume`
- `dry_run_report`
- `approval_ids`
- `started_at`
- `finished_at`
- `command`
- `operator_context`
- `item_count`
- `total_expected_bytes`
- `items`

Each manifest item must include:

- `plan_action_id`
- `source_path`
- `destination_path`
- `action_type`
- `expected_size`
- `expected_mtime_ns`
- `precheck_size`
- `precheck_mtime_ns`
- `postcheck_size`
- `postcheck_mtime_ns`
- `source_existed_before`
- `source_exists_after`
- `destination_exists_after`
- `verification_status`
- `status`
- `error_code`
- `error_message`

Manifest writing rules:

- Write manifests atomically by writing a temporary file, flushing it, and renaming it into place.
- Compute and store manifest SHA-256 after the final manifest file exists.
- Do not mark a batch committed until manifest path and manifest hash are stored in SQLite.
- A failed, partial, or missing manifest keeps the batch in `failed` or `held` state.

Rollback reference requirements:

- Rollback reference must be generated from manifest and DB state.
- It must list successful, failed, held, and skipped items separately.
- It must provide enough source/destination/status information for manual recovery.
- It must explicitly state that automatic rollback is not implemented in v2.
- It must not suggest deleting source or destination files without a separate user-approved cleanup phase.

## Fail-Fast and Resume Rules

- External commands and internal service steps must fail fast on non-recoverable errors.
- Do not silently continue after a failed batch, failed manifest, failed verification, or unsafe dry-run.
- Long scans and analyses must be resumable through SQLite state.
- Cancellation must record a checkpoint and leave the DB in a queryable state.
- Re-running scan should update `last_seen_scan_id` and distinguish `not_seen_this_scan` from `confirmed_missing`.
- Re-running analysis should reuse existing stable facts and recompute invalidated facts only where possible.
- A failed batch retry must create a new attempt or clearly update retry state without erasing the failed evidence.

## Real Windows Validation

Distinguish test-fixture validation from real Windows drive validation.

Before real `D:\` execution:

- Run scan-only against real source.
- Verify source and archive roots are detected as same volume.
- Verify reparse point, junction, and system folder handling.
- Verify long path behavior.
- Verify locked/inaccessible file handling.
- Verify dry-run produces reports and no writes outside `.photos-data` or chosen archive/report paths.
- Obtain explicit user approval before any real move.

The goal is not complete until fixture tests pass. Real-drive validation can be recorded separately in `GOAL_PROGRESS.md` as environment-specific evidence.

## Required CLI Contract

Implement these commands. Names should not be changed without updating this document.

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

All commands must emit machine-readable JSON to stdout unless explicitly writing a report file.

Real `D:\` execution must require explicit user approval and `--execute-approved`. During development, acceptance tests must not run execution against real `D:\`.

## Machine-Readable Output and Review Schemas

Every CLI command must emit a stable JSON envelope to stdout.

Required command JSON envelope:

```json
{
  "schema_version": 1,
  "ok": true,
  "command": "scan",
  "db": ".photos-data/photos.sqlite",
  "started_at": "2026-01-01T00:00:00Z",
  "finished_at": "2026-01-01T00:00:01Z",
  "summary": {},
  "artifacts": [],
  "warnings": [],
  "errors": []
}
```

Rules:

- `ok` is `false` if the command failed or produced blocking validation errors.
- `errors` entries must include `code`, `message`, `phase`, `path` when applicable, and `recoverable`.
- `warnings` entries must include `code`, `message`, and optional `path`.
- `artifacts` entries must include `type`, `path`, and `sha256` when the file exists.
- Dry-run JSON must include `error_count`, `execute_allowed`, `blocking_reasons`, `batch_summaries`, and `capacity_checks`.
- Execute JSON must include `batch_id`, `transfer_method`, `manifest_path`, `manifest_sha256`, committed/failed/held item counts, and next safe action.
- Output schemas must be covered by tests so GUI code can consume CLI/service results without string parsing.

LLM review import files must use explicit schemas.

Common review file fields:

- `schema_version`
- `review_type`
- `created_at`
- `source_packet_sha256`
- `items`

Each review item must include:

- `target_type`
- `target_path`
- `proposal_type`
- `confidence`
- `proposal`
- `evidence`
- `requires_user_approval`

Import rules:

- Reject unknown major schema versions.
- Reject missing `target_path`, unknown `proposal_type`, and paths outside known scan roots.
- Accept additional explanatory fields only if required fields validate.
- Store raw review JSON path and hash in `llm_reviews`.
- Store each accepted proposal as `pending_approval`.

## MVP Gate Rules

- Implement MVPs in order.
- Do not start a later MVP until the previous MVP acceptance criteria pass.
- Minimal service skeletons for later MVPs are allowed only when needed to keep interfaces stable.
- Each MVP must add or update tests.
- Each MVP must update `GOAL_PROGRESS.md`.
- Each MVP must leave the repo in a state where baseline verification commands can run.
- If an MVP requirement is revised, record the change in `GOAL_PROGRESS.md`.

## MVP Implementation Order and Acceptance Criteria

### MVP-1: Scan + SQLite Inventory

Implement:

- schema bootstrap and migrations
- source/archive defaults
- folder/media inventory
- attention flags for known safety/system/cache/sync patterns
- EXIF date and GPS extraction
- extension/size/date aggregation
- scan errors
- `seen`, `not_seen_this_scan`, `confirmed_missing`
- reparse point and junction defense

Acceptance:

- `photos init` creates a DB.
- `photos scan` works against `.test-tmp/sample-drive`.
- `photos summarize` returns folder count, file count, bytes, extension counts, and attention flag counts.
- Tests cover inaccessible path handling and re-scan missing-state separation.

### MVP-2: Place + Duplicate Intelligence

Implement:

- GPS place cache
- folder dominant place summary
- filename/size/date/folder-pair/sequence duplicate candidates
- transferred derivative detection
- same-name collision detection

Acceptance:

- A fixture with camera filename iteration is classified as `same_name_collision`.
- A fixture with smaller transferred copies is classified as `transferred_derivative`.
- A fixture with folder-pair repeated matches creates `folder_pair_burst`.
- No full-drive SHA-256 is required.

### MVP-3: Metadata/Date Audit + LLM Packets

Implement:

- folder-level date inconsistency analysis
- metadata override proposal storage
- LLM folder packet export
- LLM review import validation

Acceptance:

- Packet export includes folder structure, counts, sample files, date ranges, GPS place summary, attention flags, and duplicate insights.
- Packet export excludes app semantic role labels.
- Invalid LLM review paths outside scan roots are rejected.
- Imported LLM proposals remain pending approval.
- Valid and invalid review schema fixtures are covered by tests.

### MVP-4: Deterministic Plan + Dry-Run

Implement:

- move/rename/keep/hold actions
- archive root containment
- same-volume method detection
- destination collision and case-insensitive collision checks
- source snapshot validation
- cross-volume capacity validation
- dry-run report artifact

Acceptance:

- Plan never writes outside archive root.
- Same-name collisions are planned as `rename_move` or `keep_separate`.
- Dry-run reports zero errors only for safe fixture plans.
- Any dry-run error blocks execute.
- Dry-run JSON sets `execute_allowed` to `false` whenever `error_count` is nonzero or approvals are missing.
- Same-volume detection is tested with mocked or fixture volume identity data and does not rely only on drive letters.

### MVP-5: Execution

Implement:

- same-volume verified move
- cross-volume bounded copy/verify/source cleanup fallback
- batch manifests
- execution log
- rollback reference
- DB execution state
- failed batch retry state

Acceptance:

- Same-volume fixture move succeeds with manifest and committed DB status.
- Source change before execute causes held status.
- Destination collision causes held status.
- Manifest failure prevents committed status.
- Cross-volume fallback is covered by tests using separate fixture roots or mocked volume detection.
- Manifest files contain the required manifest and item fields.
- Rollback reference separates successful, failed, held, and skipped actions.

### MVP-6: PySide6 GUI

Implement:

- open/change source and archive roots
- run CLI-equivalent service actions
- three-panel folder review
- tri-state folder selection
- lazy folder tree
- paginated file/candidate tables
- LLM proposal diff and approval UI
- plan/dry-run/execute UI
- representative photo and metadata preview
- visible progress/cancel/resume status
- large SQLite-backed pagination without all-row preload
- packaged Windows GUI launch path

Acceptance:

- GUI can drive scan, analyze, packet export/import, plan, and dry-run.
- Execute remains disabled when dry-run has errors.
- GUI can show included/excluded/partial folder state.
- GUI does not implement separate business logic from CLI services.
- GUI opens folder review against a synthetic database with at least `400000` media rows without loading every media row into memory.
- Packaged Windows GUI launches without requiring the user to run Python commands.
- Packaged GUI can select source/archive roots and run a read-only scan or summary action.

## Test and Verification Commands

Use repo-local tests and fixtures.

Required baseline checks:

```powershell
python -m py_compile src\photos\*.py
python -m unittest discover -s tests
```

Required CLI smoke sequence after MVP-1:

```powershell
python -m photos init --db .test-tmp\photos.sqlite
python -m photos scan --source .test-tmp\sample-drive --archive-root .test-tmp\archive --db .test-tmp\photos.sqlite
python -m photos summarize --db .test-tmp\photos.sqlite
```

Required CLI smoke sequence after MVP-4:

```powershell
python -m photos analyze-duplicates --db .test-tmp\photos.sqlite
python -m photos audit-dates --db .test-tmp\photos.sqlite
python -m photos plan --db .test-tmp\photos.sqlite --archive-root .test-tmp\archive --strategy hybrid
python -m photos dry-run --db .test-tmp\photos.sqlite --plan latest
```

Required CLI smoke sequence after MVP-5:

```powershell
python -m photos execute --db .test-tmp\photos.sqlite --plan latest --batch latest --execute-approved
python -m photos status --db .test-tmp\photos.sqlite
```

Do not run the execute smoke sequence against real `D:\` unless explicitly approved by the user.

Required GUI/release checks after MVP-6:

```powershell
python -m photos.app --smoke
python -m unittest discover -s tests -p "*gui*"
```

If packaging uses PyInstaller, Nuitka, or another tool, add the project-standard package command and record the produced artifact path in `GOAL_PROGRESS.md`.

## Progress and Commit Policy

- Maintain `GOAL_PROGRESS.md`.
- After each MVP, record completed work, verification commands, known risks, and next steps.
- Commit only source/docs/tests intentionally related to the MVP.
- Do not commit `_zip_check/`, `__pycache__/`, `.test-tmp/`, build artifacts, or accidental generated files.
- If a test cannot be run because of environment limits, record the reason in `GOAL_PROGRESS.md`.
- Do not mark the goal complete until MVP-1 through MVP-6 acceptance criteria are satisfied or explicitly revised by the user.

## Deleted, Superseded, and Deferred Concepts

Deleted from the default path:

- full-drive SHA-256 duplicate scan as a prerequisite
- LLM file-by-file review
- automatic permanent delete
- overwrite mode
- single-file GUI architecture

Superseded:

- Review-file round trip as the core workflow is replaced by SQLite source of truth plus optional LLM packet/review import.
- Basic duplicate scan is replaced by folder-aware duplicate intelligence.
- GUI-only behavior is replaced by CLI service layer plus GUI shell.

Deferred:

- perceptual similarity/dHash
- online reverse geocoding provider selection UI
- advanced undo automation
- advanced GUI polish
- metadata write execution

## Implementation Tickets

1. Rewrite schema/bootstrap around the v2 SQLite model and status values.
2. Build scanner with EXIF/GPS extraction, folder aggregates, attention flags, missing-state separation, and reparse point defense.
3. Implement GPS place cache and folder dominant place summaries.
4. Implement duplicate intelligence from filename, size, date, folder-pair, place, and sequence evidence.
5. Implement metadata/date audit groups and metadata override suggestions.
6. Implement LLM packet export and LLM review import with pending approval storage.
7. Implement deterministic planner for move, rename, keep, hold, and metadata override actions.
8. Implement dry-run with archive containment, same-volume detection, collision checks, source validation, and cross-volume capacity validation.
9. Implement same-volume verified move and cross-volume fallback with batch manifests, execution log, rollback reference, and DB state transitions.
10. Implement PySide6 GUI on top of the CLI service layer.
11. Add stable JSON output schemas and LLM review schema fixtures.
12. Add Windows packaging/release smoke validation for the GUI.

## Final Defaults

- Default source: `D:\`
- Default archive: `D:\PICTURES`
- Default DB: `.photos-data/photos.sqlite`
- Default GPS packet mode: `summary`
- Default transfer method: same-volume verified move when possible
- Default duplicate proof model: evidence-based candidates, not exact hash proof
- Default cleanup policy: no permanent delete, no overwrite, approval required
