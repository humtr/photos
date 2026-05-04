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


def build_management_report(con: sqlite3.Connection, *, top_folders: int = 20) -> dict[str, Any]:
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
    for group in duplicate_groups(con):
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

    raw_pairs = [
        {
            "raw_path": pair.raw_path,
            "jpg_path": pair.jpg_path,
            "confidence": pair.confidence,
            "reason": pair.reason,
        }
        for pair in raw_jpg_pairs(con)
    ]
    raw_without_pairs = [_media_row(row) for row in raw_without_jpg(con)]
    non_person = non_person_candidates(con)
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
    scan_error_counts = [
        {"phase": row["phase"], "count": row["count"]}
        for row in con.execute(
            """
            SELECT phase, COUNT(*) AS count
            FROM scan_errors
            GROUP BY phase
            ORDER BY phase
            """
        )
    ]

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
            "scan_errors": scan_error_counts,
        },
        "safety": {
            "destructive_action_performed": False,
            "requires_explicit_approval_before_file_changes": True,
        },
    }


def write_management_report(
    con: sqlite3.Connection, output_path: str | Path, *, top_folders: int = 20
) -> dict[str, Any]:
    report = build_management_report(con, top_folders=top_folders)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report
