from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .hashing import duplicate_groups, hash_backlog
from .pairing import raw_jpg_pairs, raw_without_jpg
from .review import NON_PERSON_LABELS, non_person_candidates, review_queue_counts


def _media_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "path": row["path"],
        "rel_path": row["rel_path"],
        "media_type": row["media_type"],
        "size_bytes": row["size_bytes"],
        "sha256": row["sha256"],
    }


def _scan_error_counts(con: sqlite3.Connection, *, scan_run_id: int | None = None) -> list[dict]:
    if scan_run_id is None:
        rows = con.execute(
            """
            SELECT phase, COUNT(*) AS count
            FROM scan_errors
            GROUP BY phase
            ORDER BY phase
            """
        )
    else:
        rows = con.execute(
            """
            SELECT phase, COUNT(*) AS count
            FROM scan_errors
            WHERE scan_run_id = ?
            GROUP BY phase
            ORDER BY phase
            """,
            (scan_run_id,),
        )
    return [{"phase": row["phase"], "count": row["count"]} for row in rows]


def _recent_scan_errors(
    con: sqlite3.Connection, *, scan_run_id: int | None = None, limit: int = 20
) -> list[dict]:
    if scan_run_id is None:
        rows = con.execute(
            """
            SELECT path, phase, error, created_at, scan_run_id
            FROM scan_errors
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
    else:
        rows = con.execute(
            """
            SELECT path, phase, error, created_at, scan_run_id
            FROM scan_errors
            WHERE scan_run_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (scan_run_id, limit),
        )
    return [
        {
            "path": row["path"],
            "phase": row["phase"],
            "error": row["error"],
            "created_at": row["created_at"],
            "scan_run_id": row["scan_run_id"],
        }
        for row in rows
    ]


def _latest_scan_run(con: sqlite3.Connection) -> dict[str, Any] | None:
    row = con.execute(
        """
        SELECT *
        FROM scan_runs
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        return None
    scan_run_id = row["id"]
    return {
        "id": scan_run_id,
        "root": row["root"],
        "status": row["status"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "scanned_count": row["scanned_count"],
        "errors_count": row["errors_count"],
        "missing_marking_skipped": bool(row["missing_marking_skipped"]),
        "scan_errors": _scan_error_counts(con, scan_run_id=scan_run_id),
        "recent_scan_errors": _recent_scan_errors(con, scan_run_id=scan_run_id),
    }


def build_management_report(
    con: sqlite3.Connection, *, top_folders: int = 20, max_detail_items: int = 1000
) -> dict[str, Any]:
    total = con.execute(
        """
        SELECT COUNT(*) AS count, COALESCE(SUM(size_bytes), 0) AS bytes
        FROM media_files
        WHERE exists_on_disk = 1
        """
    ).fetchone()
    missing_total = con.execute(
        "SELECT COUNT(*) AS count FROM media_files WHERE exists_on_disk = 0"
    ).fetchone()
    by_type = [
        {
            "media_type": row["media_type"],
            "count": row["count"],
            "bytes": row["bytes"],
        }
        for row in con.execute(
            """
            SELECT media_type, COUNT(*) AS count, COALESCE(SUM(size_bytes), 0) AS bytes
            FROM media_files
            WHERE exists_on_disk = 1
            GROUP BY media_type
            ORDER BY count DESC, media_type
            """
        )
    ]
    folders = [
        {
            "folder": row["parent_key"] or ".",
            "count": row["count"],
            "bytes": row["bytes"],
        }
        for row in con.execute(
            """
            SELECT parent_key, COUNT(*) AS count, COALESCE(SUM(size_bytes), 0) AS bytes
            FROM media_files
            WHERE exists_on_disk = 1
            GROUP BY parent_key
            ORDER BY count DESC, bytes DESC, parent_key
            LIMIT ?
            """,
            (top_folders,),
        )
    ]

    duplicates = []
    duplicate_group_count = 0
    for group in duplicate_groups(con):
        duplicate_group_count += 1
        if len(duplicates) >= max_detail_items:
            continue
        keep = group[0]
        total_bytes = sum(row["size_bytes"] for row in group)
        reclaimable_bytes = total_bytes - keep["size_bytes"]
        duplicates.append(
            {
                "sha256": keep["sha256"],
                "keep_path": keep["path"],
                "member_count": len(group),
                "total_bytes": total_bytes,
                "reclaimable_bytes": reclaimable_bytes,
                "members": [_media_row(row) for row in group],
            }
        )

    raw_pair_rows = raw_jpg_pairs(con)
    raw_pairs = [
        {
            "raw_path": pair.raw_path,
            "jpg_path": pair.jpg_path,
            "confidence": pair.confidence,
            "reason": pair.reason,
        }
        for pair in raw_pair_rows[:max_detail_items]
    ]
    raw_without_rows = raw_without_jpg(con)
    raw_without_pairs = [_media_row(row) for row in raw_without_rows[:max_detail_items]]
    non_person_rows = non_person_candidates(con)
    non_person = non_person_rows[:max_detail_items]
    classification_counts = [
        {
            "label": row["label"],
            "count": row["count"],
        }
        for row in con.execute(
            """
            SELECT label, COUNT(*) AS count
            FROM classification_results
            GROUP BY label
            ORDER BY count DESC, label
            """
        )
    ]
    deletion_candidates = list(
        con.execute(
            """
            SELECT candidates_json
            FROM deletion_manifests
            ORDER BY id DESC
            LIMIT 1
            """
        )
    )
    candidate_count = 0
    if deletion_candidates:
        candidate_count = len(json.loads(deletion_candidates[0]["candidates_json"]))

    operation_counts = [
        {
            "kind": row["kind"],
            "action": row["action"],
            "status": row["status"],
            "count": row["count"],
        }
        for row in con.execute(
            """
            SELECT kind, action, status, COUNT(*) AS count
            FROM planning_records
            GROUP BY kind, action, status
            ORDER BY kind, action, status
            """
        )
    ]
    planned_conflicts = [
        {
            "planned_path": row["planned_path"],
            "count": row["count"],
        }
        for row in con.execute(
            """
            SELECT planned_path, COUNT(*) AS count
            FROM planning_records
            WHERE status = 'planned'
            GROUP BY planned_path
            HAVING COUNT(*) > 1
            ORDER BY count DESC, planned_path
            """
        )
    ]
    planned_case_conflicts = [
        {
            "planned_path_lower": row["planned_path_lower"],
            "count": row["count"],
        }
        for row in con.execute(
            """
            SELECT lower(planned_path) AS planned_path_lower, COUNT(*) AS count
            FROM planning_records
            WHERE status = 'planned'
            GROUP BY lower(planned_path)
            HAVING COUNT(*) > 1
            ORDER BY count DESC, planned_path_lower
            """
        )
    ]
    historical_scan_errors = _scan_error_counts(con)
    recent_scan_errors = _recent_scan_errors(con)
    current_run = _latest_scan_run(con)

    return {
        "inventory": {
            "total_files": total["count"],
            "total_bytes": total["bytes"],
            "missing_files": missing_total["count"],
            "by_type": by_type,
            "top_folders": folders,
        },
        "review_queues": {**review_queue_counts(con), "deletion_candidates": candidate_count},
        "duplicates": duplicates,
        "raw_pairs": raw_pairs,
        "raw_without_jpg": raw_without_pairs,
        "non_person_candidates": non_person,
        "classification": {
            "counts": classification_counts,
            "non_person_labels": sorted(NON_PERSON_LABELS),
        },
        "planned_operations": {
            "counts": operation_counts,
            "planned_path_conflicts": planned_conflicts,
            "planned_path_case_conflicts": planned_case_conflicts,
        },
        "scan_health": {
            "hash_backlog": hash_backlog(con),
            "current_run": current_run,
            "scan_errors": historical_scan_errors,
            "historical_scan_errors": historical_scan_errors,
            "recent_scan_errors": recent_scan_errors,
        },
        "detail_limits": {
            "max_detail_items": max_detail_items,
            "duplicate_groups_total": duplicate_group_count,
            "duplicate_groups_included": len(duplicates),
            "raw_pairs_total": len(raw_pair_rows),
            "raw_pairs_included": len(raw_pairs),
            "raw_without_jpg_total": len(raw_without_rows),
            "raw_without_jpg_included": len(raw_without_pairs),
            "non_person_candidates_total": len(non_person_rows),
            "non_person_candidates_included": len(non_person),
        },
        "safety": {
            "destructive_action_performed": False,
            "requires_explicit_approval_before_file_changes": True,
        },
    }


def write_management_report(
    con: sqlite3.Connection,
    output_path: str | Path,
    *,
    top_folders: int = 20,
    max_detail_items: int = 1000,
) -> dict[str, Any]:
    report = build_management_report(
        con, top_folders=top_folders, max_detail_items=max_detail_items
    )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report
