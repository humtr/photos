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

