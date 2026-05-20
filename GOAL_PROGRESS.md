# GOAL Progress

## MVP-1: Scan + SQLite Inventory

Status: completed

Implemented:
- SQLite bootstrap and schema initialization (`scan_roots`, `scan_runs`, `scan_errors`, `folder_nodes`, `media_files`)
- CLI commands: `init`, `scan`, `summarize`
- Scan inventory with media extension filtering and folder aggregation
- Attention flag detection for known cache/system/sync patterns
- Missing-state transitions (`seen`, `not_seen_this_scan`, `confirmed_missing`)
- JSON envelope output for CLI responses

Verification evidence:
- `python -m unittest tests.test_mvp1_scan` -> `OK`
- `python -m photos init --db .test-tmp\mvp1.sqlite` -> `ok=true`
- `python -m photos scan --source .test-tmp\test_mvp1\sample-drive --archive-root .test-tmp\test_mvp1\archive --db .test-tmp\test_mvp1\photos.sqlite` -> `ok=true`
- `python -m photos summarize --db .test-tmp\test_mvp1\photos.sqlite` -> `ok=true` with folder/file/bytes/extension/attention counts

Known risks:
- EXIF extraction remains best-effort and depends on optional Pillow availability.
- Reparse-point and long-path stress coverage should be expanded in later hardening tests.

Next step:
- Start MVP-2 and keep MVP-gated progression (verify + commit per stage).

## MVP-2: Place + Duplicate Intelligence

Status: completed

Implemented:
- CLI commands: `enrich-places`, `analyze-duplicates`
- GPS summary cache path (`place_cache`) and folder-level dominant place summary (`folder_places`)
- Duplicate candidate classification without full-drive hashing:
  - `same_name_collision`
  - `transferred_derivative`
  - `folder_pair_burst`
  - `probable_duplicate`

Verification evidence:
- `python -m unittest tests.test_mvp2_duplicates` -> `OK`
- `python -m photos enrich-places --db .test-tmp\test_mvp2\photos.sqlite --gps-mode summary` -> `ok=true`

Known risks:
- Place label currently cache-summary style (`GPS(lat,lon)`) and not external reverse geocoder output.
- Duplicate logic is evidence-based and intentionally conservative; no exact hash merge guarantee in MVP-2.

Next step:
- Start MVP-3 and keep MVP-gated progression (verify + commit per stage).

## MVP-3: Metadata/Date Audit + LLM Packets

Status: completed

Implemented:
- CLI commands: `audit-dates`, `export-folder-packets`, `import-folder-review`
- Folder-level metadata/date inconsistency analysis persisted to `metadata_audits`
- LLM-ready folder packet export with index artifact (`index.json`)
- LLM review import schema validation and proposal persistence as `pending_approval`
- Invalid/out-of-root review item rejection wired to CLI error response

Verification evidence:
- `python -m unittest tests.test_mvp3_packets` -> `OK`
- Valid review import stores `llm_review_items.status='pending_approval'`
- Invalid review import returns non-zero with populated `errors`

Known risks:
- Packet format is deterministic and local, but strategy richness still depends on external LLM quality in later workflow.
- Metadata audit heuristics are conservative and based on folder/date patterns only in MVP-3.

Next step:
- Start MVP-4 and keep MVP-gated progression (verify + commit per stage).

## MVP-4: Deterministic Plan + Dry-Run

Status: completed

Implemented:
- CLI commands: `plan`, `dry-run`
- Deterministic plan builder for `move`/`rename_move`/`keep`/`hold`
- Dry-run safety gates:
  - execute approval required
  - archive root containment
  - case-insensitive destination collision detection
  - source snapshot validation (`size`, `mtime_ns`)
  - transfer method derivation (`same_volume_move` / `copy_verify_cleanup`)
  - capacity check payload for cross-volume path

Verification evidence:
- `python -m unittest tests.test_mvp4_dry_run` -> `OK`
- `python -m photos plan --db .test-tmp\test_mvp1\photos.sqlite --archive-root .test-tmp\test_mvp1\archive --strategy hybrid` -> `ok=true`
- `python -m photos dry-run --db .test-tmp\test_mvp1\photos.sqlite --plan latest` -> blocked with `execute_allowed=false` and `missing_execute_approval`
- `python -m photos dry-run --db .test-tmp\test_mvp1\photos.sqlite --plan latest --approve-execute` -> `ok=true`, `execute_allowed=true`

Known risks:
- Dry-run report artifact file persistence is minimal at this stage and will be expanded with MVP-5 execution artifacts.
- Same-volume/cross-volume behavior is validated functionally with fixtures and mocked identity path in tests.

Next step:
- Start MVP-5 and keep MVP-gated progression (verify + commit per stage).
