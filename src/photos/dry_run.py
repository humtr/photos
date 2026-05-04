from __future__ import annotations

import shutil
from pathlib import Path

from .database import connect, finish_run, recover_interrupted_runs, start_run
from .hashing import compute_missing_hashes, duplicate_groups
from .manifest import create_deletion_manifest
from .pairing import raw_jpg_pairs
from .planning import (
    DEFAULT_RESERVED_BYTES,
    build_archive_plans,
    build_raw_to_jpg_plans,
    estimate_required_extra_bytes,
    storage_budget_status,
)
from .scanner import scan_media


def run_sample_dry_run(
    root: str | Path,
    *,
    db_path: str | Path,
    output_dir: str | Path,
    free_bytes: int | None = None,
    reserve_bytes: int = DEFAULT_RESERVED_BYTES,
) -> dict:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    con = connect(db_path)
    recover_interrupted_runs(con)
    run_id = start_run(con, "sample_dry_run", {"root": str(root)})

    try:
        scanned = scan_media(con, root)
        hashed = compute_missing_hashes(con)
        pairs = raw_jpg_pairs(con)
        archive_plans = build_archive_plans(con)
        raw_plans = build_raw_to_jpg_plans(con)
        required_extra = estimate_required_extra_bytes(con)
        actual_free = free_bytes if free_bytes is not None else shutil.disk_usage(output).free
        budget = storage_budget_status(
            free_bytes=actual_free,
            required_extra_bytes=required_extra,
            reserve_bytes=reserve_bytes,
        )
        manifest = create_deletion_manifest(con, output / "deletion_manifest.json")

        summary = {
            "scanned": scanned,
            "hashed": hashed,
            "duplicate_groups": len(duplicate_groups(con)),
            "raw_jpg_pairs": len(pairs),
            "archive_plans": len(archive_plans),
            "raw_to_jpg_plans": len(raw_plans),
            "deletion_candidates": manifest["candidate_count"],
            "required_extra_bytes": required_extra,
            "free_bytes": actual_free,
            "reserve_bytes": reserve_bytes,
            "can_run_batch": budget.can_run,
            "manifest_path": str(output / "deletion_manifest.json"),
        }
        finish_run(con, run_id, "completed", summary)
        return summary
    except Exception as exc:
        finish_run(con, run_id, "failed", {"error": repr(exc)})
        raise
