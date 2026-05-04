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
from .reports import write_management_report
from .review import export_review_package
from .scanner import scan_media


def run_media_analysis(
    root: str | Path,
    *,
    db_path: str | Path,
    output_dir: str | Path,
    free_bytes: int | None = None,
    reserve_bytes: int = DEFAULT_RESERVED_BYTES,
    hash_files: bool = True,
    top_folders: int = 20,
    max_review_shortcuts: int = 250,
    run_name: str = "analysis",
) -> dict:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    con = connect(db_path)
    run_id: int | None = None

    try:
        recover_interrupted_runs(con)
        run_id = start_run(con, run_name, {"root": str(root), "hash_files": hash_files})
        scanned = scan_media(con, root)
        hashed = compute_missing_hashes(con) if hash_files else 0
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
        report = write_management_report(
            con,
            output / "management_report.json",
            top_folders=top_folders,
        )
        review_package = export_review_package(
            con,
            output / "review_package",
            max_shortcuts_per_queue=max_review_shortcuts,
        )

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
            "management_report_path": str(output / "management_report.json"),
            "review_package_path": str(output / "review_package"),
            "review_queues": report["review_queues"],
            "review_package": review_package,
        }
        finish_run(con, run_id, "completed", summary)
        return summary
    except Exception as exc:
        if run_id is not None:
            finish_run(con, run_id, "failed", {"error": repr(exc)})
        raise
    finally:
        con.close()


def run_sample_dry_run(
    root: str | Path,
    *,
    db_path: str | Path,
    output_dir: str | Path,
    free_bytes: int | None = None,
    reserve_bytes: int = DEFAULT_RESERVED_BYTES,
) -> dict:
    return run_media_analysis(
        root,
        db_path=db_path,
        output_dir=output_dir,
        free_bytes=free_bytes,
        reserve_bytes=reserve_bytes,
        run_name="sample_dry_run",
    )
