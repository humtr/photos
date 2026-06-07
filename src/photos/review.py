from __future__ import annotations

import csv
import json
import re
import sqlite3
from collections.abc import Iterable, Iterator
from pathlib import Path, PureWindowsPath
from typing import Any
from urllib.parse import quote

from .database import record_review_decision
from .pairing import (
    iter_raw_jpg_pairs,
    iter_raw_without_jpg,
    raw_jpg_pair_count,
    raw_without_jpg_count,
)

NON_PERSON_LABELS = {"non_person", "no_person", "not_person", "without_person", "scene", "object"}
DELETE_DECISIONS = {"delete", "delete_candidate", "delete_raw", "delete_after_validation"}

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


def _write_csv(path: Path, rows: Iterable[dict[str, Any]]) -> None:
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


def _non_person_sql() -> tuple[str, tuple[str, ...]]:
    labels = tuple(sorted(NON_PERSON_LABELS))
    placeholders = ",".join("?" for _ in labels)
    return (
        f"""
        SELECT media_files.*,
               classification_results.label,
               classification_results.model AS source,
               CASE
                   WHEN lower(classification_results.label) IN ({placeholders}) THEN 1
                   ELSE 0
               END AS classifier_match
        FROM media_files
        LEFT JOIN classification_results
          ON classification_results.path = media_files.path
        WHERE media_files.exists_on_disk = 1
          AND (
              media_files.media_type = 'screenshot'
              OR lower(classification_results.label) IN ({placeholders})
          )
        ORDER BY CASE WHEN media_files.media_type = 'screenshot' THEN 0 ELSE 1 END,
                 media_files.path
        """,
        labels + labels,
    )


def iter_non_person_candidates(
    con: sqlite3.Connection,
    *,
    limit: int | None = None,
    offset: int = 0,
) -> Iterator[dict[str, Any]]:
    sql, params = _non_person_sql()
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params += (limit, offset)
    elif offset:
        sql += " LIMIT -1 OFFSET ?"
        params += (offset,)
    for row in con.execute(sql, params):
        reason = "screenshot_name_heuristic"
        if row["classifier_match"]:
            reason = f"classifier:{row['source'] or 'unknown'}:{row['label']}"
        yield _media_row(
            row,
            reason=reason,
            recommendation="review_keep_or_delete",
        )


def non_person_candidate_count(con: sqlite3.Connection) -> int:
    labels = tuple(sorted(NON_PERSON_LABELS))
    placeholders = ",".join("?" for _ in labels)
    return con.execute(
        f"""
        SELECT COUNT(*) AS count
        FROM media_files
        LEFT JOIN classification_results
          ON classification_results.path = media_files.path
        WHERE media_files.exists_on_disk = 1
          AND (
              media_files.media_type = 'screenshot'
              OR lower(classification_results.label) IN ({placeholders})
          )
        """,
        labels,
    ).fetchone()["count"]


def non_person_candidates_page(
    con: sqlite3.Connection, *, page: int, page_size: int
) -> tuple[list[dict[str, Any]], int]:
    return (
        list(iter_non_person_candidates(con, limit=page_size, offset=page * page_size)),
        non_person_candidate_count(con),
    )


def non_person_candidates(con: sqlite3.Connection) -> list[dict[str, Any]]:
    return list(iter_non_person_candidates(con))


def _duplicate_group_count(con: sqlite3.Connection) -> int:
    return con.execute(
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
        "exact_duplicate_groups": _duplicate_group_count(con),
        "raw_jpg_pairs": raw_jpg_pair_count(con),
        "raw_without_jpg": raw_without_jpg_count(con),
        "non_person_candidates": non_person_candidate_count(con),
        "videos": video_count,
    }


def _iter_exact_duplicates(con: sqlite3.Connection) -> Iterator[dict[str, Any]]:
    hashes = con.execute(
        """
        SELECT sha256
        FROM media_files
        WHERE sha256 IS NOT NULL
          AND exists_on_disk = 1
        GROUP BY sha256
        HAVING COUNT(*) > 1
        ORDER BY sha256
        """
    )
    for hash_row in hashes:
        group_key = f"duplicate:{hash_row['sha256']}"
        members = con.execute(
            """
            SELECT *
            FROM media_files
            WHERE sha256 = ?
              AND exists_on_disk = 1
            ORDER BY path
            """,
            (hash_row["sha256"],),
        )
        for member_index, row in enumerate(members, start=1):
            yield {
                "queue": "exact_duplicates",
                "item_key": group_key,
                "reason": "same_sha256",
                "recommendation": "keep" if member_index == 1 else "delete_candidate",
                **_media_row(row),
            }


def _iter_raw_jpg_pair_queue(con: sqlite3.Connection) -> Iterator[dict[str, Any]]:
    for pair_index, pair in enumerate(iter_raw_jpg_pairs(con), start=1):
        raw = _row_for_path(con, pair.raw_path)
        if raw is None:
            continue
        yield {
            **_media_row(raw),
            "queue": "raw_jpg_pairs",
            "item_key": f"raw_pair:{pair_index:06d}",
            "paired_path": pair.jpg_path,
            "reason": pair.reason,
            "recommendation": "validate_jpg_then_decide_raw",
        }


def _iter_raw_without_jpg_queue(con: sqlite3.Connection) -> Iterator[dict[str, Any]]:
    for index, row in enumerate(iter_raw_without_jpg(con), start=1):
        yield {
            **_media_row(row),
            "queue": "raw_without_jpg",
            "item_key": f"raw_without_jpg:{index:06d}",
            "reason": "raw_has_no_same_folder_jpg",
            "recommendation": "convert_raw_to_jpg_then_review",
        }


def _iter_non_person_queue(con: sqlite3.Connection) -> Iterator[dict[str, Any]]:
    for index, row in enumerate(iter_non_person_candidates(con), start=1):
        yield {
            "queue": "non_person_candidates",
            "item_key": f"non_person:{index:06d}",
            **row,
        }


def _iter_video_queue(con: sqlite3.Connection) -> Iterator[dict[str, Any]]:
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
        yield {
            **_media_row(row),
            "queue": "videos",
            "item_key": f"video:{index:06d}",
            "reason": "video_file",
            "recommendation": "review_keep_or_delete",
        }


def iter_review_queue(con: sqlite3.Connection, queue_name: str) -> Iterator[dict[str, Any]]:
    factories = {
        "exact_duplicates": _iter_exact_duplicates,
        "raw_jpg_pairs": _iter_raw_jpg_pair_queue,
        "raw_without_jpg": _iter_raw_without_jpg_queue,
        "non_person_candidates": _iter_non_person_queue,
        "videos": _iter_video_queue,
    }
    try:
        yield from factories[queue_name](con)
    except KeyError:
        raise ValueError(f"unsupported review queue: {queue_name}") from None


def build_review_queues(con: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    return {
        name: list(iter_review_queue(con, name))
        for name in (
            "exact_duplicates",
            "raw_jpg_pairs",
            "raw_without_jpg",
            "non_person_candidates",
            "videos",
        )
    }


def export_review_package(
    con: sqlite3.Connection,
    output_dir: str | Path,
    *,
    max_shortcuts_per_queue: int = 250,
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    queue_names = (
        "exact_duplicates",
        "raw_jpg_pairs",
        "raw_without_jpg",
        "non_person_candidates",
        "videos",
    )
    queue_counts = {name: 0 for name in queue_names}
    decisions_path = output / "decisions_template.csv"
    decisions_path.parent.mkdir(parents=True, exist_ok=True)
    with decisions_path.open("w", newline="", encoding="utf-8") as decisions_handle:
        decisions_writer = csv.DictWriter(decisions_handle, fieldnames=REVIEW_FIELDS)
        decisions_writer.writeheader()
        for queue_name in queue_names:
            queue_path = output / "queues" / f"{queue_name}.csv"
            queue_path.parent.mkdir(parents=True, exist_ok=True)
            with queue_path.open("w", newline="", encoding="utf-8") as queue_handle:
                queue_writer = csv.DictWriter(queue_handle, fieldnames=REVIEW_FIELDS)
                queue_writer.writeheader()
                for index, row in enumerate(iter_review_queue(con, queue_name), start=1):
                    csv_row = {_field: _csv_value(row.get(_field, "")) for _field in REVIEW_FIELDS}
                    queue_writer.writerow(csv_row)
                    decisions_writer.writerow(csv_row)
                    queue_counts[queue_name] += 1
                    if index <= max(0, max_shortcuts_per_queue):
                        stem = _safe_name(f"{index:05d}_{Path(row['path']).stem}")
                        _write_url(
                            output / "shortcuts" / queue_name / f"{stem}.url",
                            row["path"],
                        )

    summary = {
        "output_dir": str(output),
        "queue_counts": queue_counts,
        "max_shortcuts_per_queue": max_shortcuts_per_queue,
        "destructive_action_performed": False,
        "decision_values": ["keep", "delete", "defer", "convert", "delete_after_validation"],
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return summary


def import_review_decisions(con: sqlite3.Connection, csv_path: str | Path) -> int:
    imported = 0
    with Path(csv_path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            decision = (row.get("decision") or "").strip()
            if not decision:
                continue
            group_key = row.get("item_key") or row.get("queue") or "review"
            path = row.get("path") or ""
            if not path:
                continue
            record_review_decision(con, group_key, path, decision, row.get("note") or "")
            imported += 1
    con.commit()
    return imported


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
        "candidate_count": len(rows),
        "candidates": [dict(row) for row in rows],
        "destructive_action_performed": False,
        "requires_explicit_approval_before_delete": True,
    }
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest
