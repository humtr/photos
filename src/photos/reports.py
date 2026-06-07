from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .hashing import hash_backlog
from .pairing import raw_jpg_pairs_page, raw_without_jpg_page
from .review import NON_PERSON_LABELS, non_person_candidates_page, review_queue_counts

DEFAULT_DETAIL_PAGE_SIZE = 10_000


def _media_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "path": row["path"],
        "rel_path": row["rel_path"],
        "media_type": row["media_type"],
        "size_bytes": row["size_bytes"],
        "sha256": row["sha256"],
    }


def _scan_error_counts(con: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
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


def _recent_scan_errors(con: sqlite3.Connection, *, limit: int = 20) -> list[dict[str, Any]]:
    return [
        {
            "path": row["path"],
            "phase": row["phase"],
            "error": row["error"],
            "created_at": row["created_at"],
        }
        for row in con.execute(
            """
            SELECT path, phase, error, created_at
            FROM scan_errors
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
    ]


def _duplicate_groups_page(
    con: sqlite3.Connection,
    *,
    page: int,
    page_size: int,
) -> tuple[list[dict[str, Any]], int]:
    total = con.execute(
        """
        SELECT COUNT(*) AS count
        FROM (
            SELECT sha256
            FROM media_files
            WHERE sha256 IS NOT NULL
              AND exists_on_disk = 1
            GROUP BY sha256
            HAVING COUNT(*) > 1
        )
        """
    ).fetchone()["count"]
    items: list[dict[str, Any]] = []
    hashes = con.execute(
        """
        SELECT sha256
        FROM media_files
        WHERE sha256 IS NOT NULL
          AND exists_on_disk = 1
        GROUP BY sha256
        HAVING COUNT(*) > 1
        ORDER BY sha256
        LIMIT ? OFFSET ?
        """,
        (page_size, page * page_size),
    )
    for hash_row in hashes:
        group = list(
            con.execute(
                """
                SELECT *
                FROM media_files
                WHERE sha256 = ?
                  AND exists_on_disk = 1
                ORDER BY path
                """,
                (hash_row["sha256"],),
            )
        )
        keep = group[0]
        total_bytes = sum(row["size_bytes"] for row in group)
        reclaimable_bytes = total_bytes - keep["size_bytes"]
        items.append(
            {
                "sha256": keep["sha256"],
                "keep_path": keep["path"],
                "member_count": len(group),
                "total_bytes": total_bytes,
                "reclaimable_bytes": reclaimable_bytes,
                "members": [_media_row(row) for row in group],
            }
        )
    return items, total


def build_management_report(
    con: sqlite3.Connection,
    *,
    top_folders: int = 20,
    max_detail_items: int = DEFAULT_DETAIL_PAGE_SIZE,
    detail_page_size: int = DEFAULT_DETAIL_PAGE_SIZE,
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

    page0_duplicates, duplicate_total = _duplicate_groups_page(con, page=0, page_size=max_detail_items)
    duplicates = page0_duplicates

    raw_pair_page, raw_pairs_total = raw_jpg_pairs_page(
        con, page=0, page_size=max_detail_items
    )
    raw_pairs = [
        {
            "raw_path": pair.raw_path,
            "jpg_path": pair.jpg_path,
            "confidence": pair.confidence,
            "reason": pair.reason,
        }
        for pair in raw_pair_page
    ]
    raw_without_page, raw_without_total = raw_without_jpg_page(
        con, page=0, page_size=max_detail_items
    )
    raw_without_pairs = [_media_row(row) for row in raw_without_page]
    non_person, non_person_total = non_person_candidates_page(
        con, page=0, page_size=max_detail_items
    )
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
    scan_error_counts = _scan_error_counts(con)
    recent_scan_errors = _recent_scan_errors(con)

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
            "recent_scan_errors": recent_scan_errors,
        },
        "detail_limits": {
            "max_detail_items": max_detail_items,
            "detail_page_size": detail_page_size,
            "duplicate_groups_total": duplicate_total,
            "duplicate_groups_included": len(duplicates),
            "raw_pairs_total": raw_pairs_total,
            "raw_pairs_included": len(raw_pairs),
            "raw_without_jpg_total": raw_without_total,
            "raw_without_jpg_included": len(raw_without_pairs),
            "non_person_candidates_total": non_person_total,
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
    max_detail_items: int = DEFAULT_DETAIL_PAGE_SIZE,
    detail_page_size: int = DEFAULT_DETAIL_PAGE_SIZE,
) -> dict[str, Any]:
    report = build_management_report(
        con,
        top_folders=top_folders,
        max_detail_items=max_detail_items,
        detail_page_size=detail_page_size,
    )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def write_management_report_page(
    con: sqlite3.Connection,
    output_path: str | Path,
    *,
    section: str,
    page: int,
    page_size: int = DEFAULT_DETAIL_PAGE_SIZE,
) -> dict[str, Any]:
    if page < 0:
        raise ValueError("page must be zero or greater")
    if page_size <= 0:
        raise ValueError("page_size must be greater than zero")

    if section == "duplicates":
        items, total = _duplicate_groups_page(con, page=page, page_size=page_size)
    elif section == "raw_pairs":
        pairs, total = raw_jpg_pairs_page(con, page=page, page_size=page_size)
        items = [
            {"raw_path": p.raw_path, "jpg_path": p.jpg_path, "confidence": p.confidence, "reason": p.reason}
            for p in pairs
        ]
    elif section == "raw_without_jpg":
        rows, total = raw_without_jpg_page(con, page=page, page_size=page_size)
        items = [_media_row(row) for row in rows]
    elif section == "non_person_candidates":
        items, total = non_person_candidates_page(con, page=page, page_size=page_size)
    else:
        raise ValueError(f"unsupported section: {section}")

    payload = {
        "section": section,
        "page": page,
        "page_size": page_size,
        "total_items": total,
        "total_pages": (total + page_size - 1) // page_size,
        "items": items,
    }
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return payload
