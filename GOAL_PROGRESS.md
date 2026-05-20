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
