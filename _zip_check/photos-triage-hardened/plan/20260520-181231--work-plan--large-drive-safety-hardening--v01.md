Plan Type: work-plan
Workstream: Large-drive safety hardening for photos-triage
Version: v01
Status: Completed - second hardening pass ready for user review
Created: 2026-05-20T18:12:31+09:00 Asia/Seoul
Last Updated: 2026-05-20 Asia/Seoul
Supersedes or Related Plan: Related to user-approved repository hardening request and follow-up request to modify and return the archive.
Current Completion State: Implementation, verification, review, and packaging completed; user review remains.
Completed So Far: Scanner, hashing, planning, reporting, manifest semantics, import validation, SQL-side pairing, docs, Windows runner, and tests hardened.
Remaining Work: User review and any separately approved Windows-side validation.
Current Blockers: None.
Next Step: Deliver the archive and verification summary to the user.

# Scoreboard

Current Score: 56/100
Score Source: provisional
Last Updated: 2026-05-20 Asia/Seoul
Score Rationale: The safety core is stronger and locally verified, but the real Windows 4 TB target remains unverified.
What Improved: Current-vs-historical scan health, candidate-vs-approved manifest separation, atomic decision imports, SQL-side RAW/JPG pairing, bounded report detail output, and regression coverage.
What Remains Unsatisfactory: Real Windows drive behavior, long paths, file locking, GUI performance, external RAW conversion quality, and throughput are not validated in this runtime.
Actions To Raise Or Maintain Score: Run the Windows handoff checks and a bounded real-drive first pass with `-SkipHash`, then small hash batches.

# Approved Objective

Improve the existing photos-triage repository so it is safer and more dependable for large Windows photo/video drives while preserving its current non-destructive operating model.

The repository must continue to avoid direct deletion or file movement. Any delete-related output must remain a review or approval artifact only.

# Completed Second-Pass Changes

- Added a `scan_runs` table and connected scan errors to scan runs via `scan_run_id`.
- Added `scan_health.current_run` with scan-run status, scanned count, error count, missing-marking skip flag, and current-run error details.
- Preserved historical scan-error counts for auditability.
- Separated candidate review manifests from approved delete manifests.
- Wrote dry-run candidate manifests to `candidate_manifest.json`; kept `manifest_path` as a compatibility alias and added `candidate_manifest_path` explicitly.
- Made decision manifests explicit review-decision artifacts that do not execute deletion and still require separate execution approval.
- Replaced Python-wide JPG indexing in RAW/JPG pairing with SQL-side `EXISTS` and correlated lookup.
- Batched classification and decision imports with one commit after validation.
- Rejected invalid review decision values atomically before writing review decisions.
- Added report detail limits through `max_detail_items` while preserving summary counts.
- Added CLI/report and Windows runner support for report detail limits.
- Updated README, Windows handoff documentation, and verification script to use safer manifest terminology.
- Added regression tests for current-vs-historical scan runs, invalid decision atomicity, and classification batch commit behavior.

# Verification

- `PYTHONPATH=src python -m unittest discover -s tests` passed 16 tests.
- `python -m compileall -q src tests scripts` returned 0.
- `PYTHONPATH=src python -m photos --help` returned 0.
- `PYTHONPATH=src python scripts/verify_handoff.py` returned status `ok`; the verifier reran 16 tests and sample dry-run.
- `python -m ruff check .` could not run because `ruff` is not installed in this environment.

# Boundary

This package is ready for user review and Windows handoff testing. It does not prove real-drive throughput, Windows file-lock behavior, external RAW conversion quality, or GUI performance.
