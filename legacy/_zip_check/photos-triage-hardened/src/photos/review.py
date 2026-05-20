from __future__ import annotations

import csv
import json
import re
import sqlite3
from pathlib import Path, PureWindowsPath
from typing import Any
from urllib.parse import quote

from .database import record_review_decision, utc_now
from .hashing import duplicate_groups
from .pairing import raw_jpg_pairs, raw_without_jpg

NON_PERSON_LABELS = {"non_person", "no_person", "not_person", "without_person", "scene", "object"}
DELETE_DECISIONS = {"delete", "delete_candidate", "delete_raw", "delete_after_validation"}
ALLOWED_REVIEW_DECISIONS = {
    "keep",
    "keep_raw",
    "delete",
    "delete_candidate",
    "delete_raw",
    "delete_after_validation",
    "defer",
    "convert",
    "convert_raw_to_jpg",
    "validate_existing_jpg",
    "ignore",
}

REVIEW_FIELDS = [
    "queue",
    "item_key",
    "path",
    "paired_path",
    "media_type",
    "size_bytes",
    "sha256",
    "reason",
    "recommendation",
    "decision",
    "note",
]


def _media_row(row: sqlite3.Row, **extra: Any) -> dict[str, Any]:
    data = {
        "path": row["path"],
        "paired_path": "",
        "media_type": row["media_type"],
        "size_bytes": row["size_bytes"],
        "sha256": row["sha256"] or "",
    }
    data.update(extra)
    return data


def _row_for_path(con: sqlite3.Connection, path: str) -> sqlite3.Row | None:
    return con.execute(
        "SELECT * FROM media_files WHERE path = ? AND exists_on_disk = 1", (path,)
    ).fetchone()


def _windows_or_posix_file_uri(path: str) -> str:
    if re.match(r"^[\\/]{2}", path):
        windows_path = PureWindowsPath(path)
        return "file:" + quote(windows_path.as_posix(), safe="/:")
    if re.match(r"^[A-Za-z]:[\\/]", path):
        windows_path = PureWindowsPath(path)
        return "file:///" + quote(windows_path.as_posix(), safe="/:")
    return Path(path).expanduser().resolve().as_uri()


def _safe_name(value: str, *, fallback: str = "item") -> str:
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", value).strip(" ._")
    return safe[:120] or fallback


def _csv_value(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({_field: _csv_value(row.get(_field, "")) for _field in REVIEW_FIELDS})


def _write_url(path: Path, target_path: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = f"[InternetShortcut]\nURL={_windows_or_posix_file_uri(target_path)}\n"
    path.write_text(content, encoding="utf-8")


def non_person_candidates(con: sqlite3.Connection) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for row in con.execute(
        """
        SELECT *, 'screenshot_name_heuristic' AS source, '' AS label, NULL AS confidence
        FROM media_files
        WHERE media_type = 'screenshot'
          AND exists_on_disk = 1
        ORDER BY path
        """
    ):
        rows[row["path"]] = _media_row(
            row,
            reason=row["source"],
            recommendation="review_keep_or_delete",
        )

    for row in con.execute(
        """
        SELECT media_files.*, classification_results.label, classification_results.confidence,
               classification_results.model AS source
        FROM classification_results
        JOIN media_files ON media_files.path = classification_results.path
        WHERE media_files.exists_on_disk = 1
        ORDER BY media_files.path
        """
    ):
        if row["label"].lower() not in NON_PERSON_LABELS:
            continue
        rows[row["path"]] = _media_row(
            row,
            reason=f"classifier:{row['source'] or 'unknown'}:{row['label']}",
            recommendation="review_keep_or_delete",
        )
    return list(rows.values())


def review_queue_counts(con: sqlite3.Connection) -> dict[str, int]:
    video_count = con.execute(
        """
        SELECT COUNT(*) AS count
        FROM media_files
        WHERE media_type = 'video'
          AND exists_on_disk = 1
        """
    ).fetchone()["count"]
    return {
        "exact_duplicate_groups": len(duplicate_groups(con)),
        "raw_jpg_pairs": len(raw_jpg_pairs(con)),
        "raw_without_jpg": len(raw_without_jpg(con)),
        "non_person_candidates": len(non_person_candidates(con)),
        "videos": video_count,
    }


def build_review_queues(con: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    queues: dict[str, list[dict[str, Any]]] = {
        "exact_duplicates": [],
        "raw_jpg_pairs": [],
        "raw_without_jpg": [],
        "non_person_candidates": [],
        "videos": [],
    }

    for group in duplicate_groups(con):
        group_key = f"duplicate:{group[0]['sha256']}"
        for member_index, row in enumerate(group, start=1):
            queues["exact_duplicates"].append(
                {
                    "queue": "exact_duplicates",
                    "item_key": group_key,
                    "reason": "same_sha256",
                    "recommendation": "keep" if member_index == 1 else "delete_candidate",
                    **_media_row(row),
                }
            )

    for pair_index, pair in enumerate(raw_jpg_pairs(con), start=1):
        raw = _row_for_path(con, pair.raw_path)
        if raw is None:
            continue
        queues["raw_jpg_pairs"].append(
            {
                **_media_row(raw),
                "queue": "raw_jpg_pairs",
                "item_key": f"raw_pair:{pair_index:06d}",
                "paired_path": pair.jpg_path,
                "reason": pair.reason,
                "recommendation": "validate_jpg_then_decide_raw",
            }
        )

    for index, row in enumerate(raw_without_jpg(con), start=1):
        queues["raw_without_jpg"].append(
            {
                **_media_row(row),
                "queue": "raw_without_jpg",
                "item_key": f"raw_without_jpg:{index:06d}",
                "reason": "raw_has_no_same_folder_jpg",
                "recommendation": "convert_raw_to_jpg_then_review",
            }
        )

    for index, row in enumerate(non_person_candidates(con), start=1):
        queues["non_person_candidates"].append(
            {
                "queue": "non_person_candidates",
                "item_key": f"non_person:{index:06d}",
                **row,
            }
        )

    for index, row in enumerate(
        con.execute(
            """
            SELECT *
            FROM media_files
            WHERE media_type = 'video'
              AND exists_on_disk = 1
            ORDER BY path
            """
        ),
        start=1,
    ):
        queues["videos"].append(
            {
                **_media_row(row),
                "queue": "videos",
                "item_key": f"video:{index:06d}",
                "reason": "video_file",
                "recommendation": "review_keep_or_delete",
            }
        )

    return queues


def export_review_package(
    con: sqlite3.Connection,
    output_dir: str | Path,
    *,
    max_shortcuts_per_queue: int = 250,
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    queues = build_review_queues(con)
    all_rows: list[dict[str, Any]] = []

    for queue_name, rows in queues.items():
        _write_csv(output / "queues" / f"{queue_name}.csv", rows)
        all_rows.extend(rows)
        shortcut_limit = max(0, max_shortcuts_per_queue)
        for index, row in enumerate(rows[:shortcut_limit], start=1):
            stem = _safe_name(f"{index:05d}_{Path(row['path']).stem}")
            _write_url(output / "shortcuts" / queue_name / f"{stem}.url", row["path"])

    _write_csv(output / "decisions_template.csv", all_rows)
    summary = {
        "output_dir": str(output),
        "queue_counts": {name: len(rows) for name, rows in queues.items()},
        "max_shortcuts_per_queue": max_shortcuts_per_queue,
        "destructive_action_performed": False,
        "decision_values": sorted(ALLOWED_REVIEW_DECISIONS),
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return summary


def import_review_decisions(con: sqlite3.Connection, csv_path: str | Path) -> int:
    pending: list[tuple[str, str, str, str]] = []
    invalid: list[str] = []
    with Path(csv_path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "path" not in reader.fieldnames or "decision" not in reader.fieldnames:
            raise ValueError("decision CSV must include path and decision columns")
        for row_number, row in enumerate(reader, start=2):
            decision = (row.get("decision") or "").strip().lower()
            if not decision:
                continue
            if decision not in ALLOWED_REVIEW_DECISIONS:
                invalid.append(f"row {row_number}: {decision}")
                continue
            group_key = row.get("item_key") or row.get("queue") or "review"
            path = row.get("path") or ""
            if not path:
                continue
            pending.append((group_key, path, decision, row.get("note") or ""))

    if invalid:
        allowed = ", ".join(sorted(ALLOWED_REVIEW_DECISIONS))
        raise ValueError(f"invalid review decision values ({'; '.join(invalid)}); allowed: {allowed}")

    for group_key, path, decision, note in pending:
        record_review_decision(con, group_key, path, decision, note, commit=False)
    con.commit()
    return len(pending)


def write_decision_manifest(con: sqlite3.Connection, output_path: str | Path) -> dict[str, Any]:
    rows = list(
        con.execute(
            """
            SELECT review_decisions.group_key, review_decisions.path,
                   review_decisions.decision, review_decisions.note,
                   review_decisions.updated_at
            FROM review_decisions
            JOIN media_files ON media_files.path = review_decisions.path
            WHERE lower(review_decisions.decision) IN ({})
              AND media_files.exists_on_disk = 1
            ORDER BY review_decisions.group_key, review_decisions.path
            """.format(",".join("?" for _ in DELETE_DECISIONS)),
            tuple(sorted(DELETE_DECISIONS)),
        )
    )
    manifest = {
        "manifest_type": "approved_delete_manifest",
        "created_at": utc_now(),
        "candidate_count": len(rows),
        "candidates": [dict(row) for row in rows],
        "delete_decisions": sorted(DELETE_DECISIONS),
        "destructive_action_performed": False,
        "approved_by_review_decision": True,
        "requires_explicit_approval_before_delete": True,
        "requires_separate_execution_approval": True,
    }
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest
