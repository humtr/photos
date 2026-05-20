from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .database import utc_now
from .hashing import duplicate_groups


def _candidate_rows(con: sqlite3.Connection) -> list[dict]:
    candidates: list[dict] = []

    for group in duplicate_groups(con):
        keep = group[0]
        for duplicate in group[1:]:
            candidates.append(
                {
                    "path": duplicate["path"],
                    "reason": "exact_duplicate",
                    "keep_path": keep["path"],
                    "sha256": duplicate["sha256"],
                    "requires_approval": True,
                    "approval_state": "candidate_only",
                }
            )

    raw_plans = con.execute(
        """
        SELECT source_path, planned_path, action
        FROM planning_records
        JOIN media_files ON media_files.path = planning_records.source_path
        WHERE kind = 'raw_to_jpg'
          AND status = 'planned'
          AND media_files.exists_on_disk = 1
        ORDER BY source_path
        """
    )
    for row in raw_plans:
        candidates.append(
            {
                "path": row["source_path"],
                "reason": "raw_reduction_candidate",
                "planned_jpg": row["planned_path"],
                "raw_action": row["action"],
                "requires_approval": True,
                "approval_state": "candidate_only",
                "validation_required_before_delete": True,
            }
        )
    return candidates


def create_candidate_manifest(con: sqlite3.Connection, output_path: str | Path) -> dict:
    candidates = _candidate_rows(con)
    manifest = {
        "manifest_type": "candidate_review_manifest",
        "created_at": utc_now(),
        "destructive_action_performed": False,
        "requires_explicit_approval_before_delete": True,
        "approved_for_delete": False,
        "candidate_count": len(candidates),
        "candidates": candidates,
    }

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    con.execute(
        """
        INSERT INTO deletion_manifests(manifest_path, candidates_json, created_at)
        VALUES(?, ?, ?)
        """,
        (str(output), json.dumps(candidates, sort_keys=True), utc_now()),
    )
    con.commit()
    return manifest


def create_deletion_manifest(con: sqlite3.Connection, output_path: str | Path) -> dict:
    # Backward compatible alias.
    return create_candidate_manifest(con, output_path)
