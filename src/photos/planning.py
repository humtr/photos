from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath

from .database import utc_now
from .pairing import iter_raw_jpg_pairs, iter_raw_without_jpg

DEFAULT_RESERVED_BYTES = 100 * 1024**3
PLANNING_BATCH_SIZE = 500
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


@dataclass(frozen=True)
class SpaceBudget:
    free_bytes: int
    reserve_bytes: int
    required_extra_bytes: int

    @property
    def available_for_batch(self) -> int:
        return max(0, self.free_bytes - self.reserve_bytes)

    @property
    def can_run(self) -> bool:
        return self.required_extra_bytes <= self.available_for_batch


def safe_segment(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", value).strip(" .")
    if not cleaned:
        return "unnamed"
    stem = cleaned.rsplit(".", 1)[0] if "." in cleaned else cleaned
    if stem.upper() in WINDOWS_RESERVED_NAMES:
        cleaned = f"_{cleaned}"
    if len(cleaned) > 180:
        if "." in cleaned:
            stem, suffix = cleaned.rsplit(".", 1)
            cleaned = f"{stem[:170]}.{suffix[:16]}"
        else:
            cleaned = cleaned[:180]
    return cleaned


def row_date(row: sqlite3.Row) -> datetime:
    return datetime.fromtimestamp(row["mtime_ns"] / 1_000_000_000)


def _date_key(row: sqlite3.Row) -> str:
    return row_date(row).strftime("%Y-%m-%d")


def _planned_archive_path(
    row: sqlite3.Row,
    date_counts: Counter[str],
    *,
    archive_root: str,
    event_threshold: int,
    suffix_override: str | None = None,
) -> str:
    dt = row_date(row)
    yyyy = dt.strftime("%Y")
    yyyy_mm = dt.strftime("%Y-%m")
    date = dt.strftime("%Y-%m-%d")
    folder = f"{date}_event" if date_counts[date] >= event_threshold else "_loose"
    name = safe_segment(row["name"])
    if suffix_override:
        stem = safe_segment(name.rsplit(".", 1)[0] if "." in name else name)
        name = f"{stem}{suffix_override}"
    return str(PurePosixPath(archive_root) / yyyy / yyyy_mm / folder / name)


def _iter_keyset_rows(
    con: sqlite3.Connection,
    sql: str,
    params: tuple[object, ...] = (),
    *,
    batch_size: int = PLANNING_BATCH_SIZE,
) -> Iterator[sqlite3.Row]:
    last_path = ""
    while True:
        rows = con.execute(sql, (*params, last_path, batch_size)).fetchall()
        if not rows:
            return
        yield from rows
        last_path = str(rows[-1]["path"])


def _prepare_date_counts(con: sqlite3.Connection) -> None:
    con.execute("DROP TABLE IF EXISTS temp.photos_planning_date_counts")
    con.execute(
        """
        CREATE TEMP TABLE photos_planning_date_counts(
            date_key TEXT PRIMARY KEY,
            item_count INTEGER NOT NULL
        ) WITHOUT ROWID
        """
    )
    for index, row in enumerate(
        _iter_keyset_rows(
            con,
            """
            SELECT path, mtime_ns
            FROM media_files
            WHERE exists_on_disk = 1 AND path > ?
            ORDER BY path
            LIMIT ?
            """,
        ),
        start=1,
    ):
        con.execute(
            """
            INSERT INTO photos_planning_date_counts(date_key, item_count)
            VALUES(?, 1)
            ON CONFLICT(date_key) DO UPDATE SET item_count = item_count + 1
            """,
            (_date_key(row),),
        )
        if index % PLANNING_BATCH_SIZE == 0:
            con.commit()
    con.commit()


def _date_count(con: sqlite3.Connection, row: sqlite3.Row) -> Counter[str]:
    date_key = _date_key(row)
    count_row = con.execute(
        "SELECT item_count FROM photos_planning_date_counts WHERE date_key = ?",
        (date_key,),
    ).fetchone()
    return Counter({date_key: int(count_row["item_count"]) if count_row else 0})


def _prepare_path_dedupe(con: sqlite3.Connection) -> None:
    con.execute("DROP TABLE IF EXISTS temp.photos_planning_paths")
    con.execute(
        """
        CREATE TEMP TABLE photos_planning_paths(
            path_ci TEXT PRIMARY KEY
        ) WITHOUT ROWID
        """
    )


def _dedupe_planned_path(con: sqlite3.Connection, path: str) -> str:
    candidate = PurePosixPath(path)
    final = candidate
    index = 2
    while True:
        try:
            con.execute(
                "INSERT INTO photos_planning_paths(path_ci) VALUES(?)",
                (str(final).lower(),),
            )
            return str(final)
        except sqlite3.IntegrityError:
            final = candidate.with_name(f"{candidate.stem}_{index}{candidate.suffix}")
            index += 1


def _add_planning_record(
    con: sqlite3.Connection,
    *,
    kind: str,
    action: str,
    source_path: str,
    planned_path: str,
    details_json: str,
) -> None:
    con.execute(
        """
        INSERT INTO planning_records(
            kind, action, source_path, planned_path, status, details_json, created_at
        )
        VALUES(?, ?, ?, ?, 'planned', ?, ?)
        ON CONFLICT(kind, action, source_path, planned_path) DO UPDATE SET
            status = excluded.status,
            details_json = excluded.details_json
        """,
        (kind, action, source_path, planned_path, details_json, utc_now()),
    )


def iter_archive_plans(
    con: sqlite3.Connection,
    archive_root: str = "archive",
    event_threshold: int = 10,
) -> Iterator[dict[str, str]]:
    """Persist and yield archive plans without materializing the library."""

    con.execute("UPDATE planning_records SET status = 'superseded' WHERE kind = 'archive'")
    con.commit()
    _prepare_date_counts(con)
    _prepare_path_dedupe(con)
    try:
        for index, row in enumerate(
            _iter_keyset_rows(
                con,
                """
                SELECT *
                FROM media_files
                WHERE exists_on_disk = 1 AND path > ?
                ORDER BY path
                LIMIT ?
                """,
            ),
            start=1,
        ):
            planned_path = _dedupe_planned_path(
                con,
                _planned_archive_path(
                    row,
                    _date_count(con, row),
                    archive_root=archive_root,
                    event_threshold=event_threshold,
                ),
            )
            _add_planning_record(
                con,
                kind="archive",
                action="move_after_approval",
                source_path=row["path"],
                planned_path=planned_path,
                details_json=json.dumps(
                    {"rel_path": row["rel_path"], "media_type": row["media_type"]},
                    sort_keys=True,
                ),
            )
            if index % PLANNING_BATCH_SIZE == 0:
                con.commit()
            yield {"source_path": row["path"], "planned_path": planned_path}
    finally:
        con.commit()
        con.execute("DROP TABLE IF EXISTS temp.photos_planning_paths")
        con.execute("DROP TABLE IF EXISTS temp.photos_planning_date_counts")


def build_archive_plans(
    con: sqlite3.Connection, archive_root: str = "archive", event_threshold: int = 10
) -> list[dict[str, str]]:
    """Compatibility API for legacy dry-runs that explicitly require a list."""

    return list(iter_archive_plans(con, archive_root=archive_root, event_threshold=event_threshold))


def build_raw_to_jpg_plans(
    con: sqlite3.Connection, jpg_root: str = "archive_jpg"
) -> list[dict[str, str]]:
    """Compatibility API for legacy dry-runs that explicitly require a list."""

    return list(iter_raw_to_jpg_plans(con, jpg_root=jpg_root))


def iter_raw_to_jpg_plans(
    con: sqlite3.Connection, jpg_root: str = "archive_jpg"
) -> Iterator[dict[str, str]]:
    con.execute("UPDATE planning_records SET status = 'superseded' WHERE kind = 'raw_to_jpg'")
    con.commit()
    _prepare_date_counts(con)
    _prepare_path_dedupe(con)
    index = 0
    try:
        for pair in iter_raw_jpg_pairs(con):
            index += 1
            _add_planning_record(
                con,
                kind="raw_to_jpg",
                action="validate_existing_jpg",
                source_path=pair.raw_path,
                planned_path=pair.jpg_path,
                details_json=json.dumps(
                    {"confidence": pair.confidence, "reason": pair.reason}, sort_keys=True
                ),
            )
            if index % PLANNING_BATCH_SIZE == 0:
                con.commit()
            yield {
                "source_path": pair.raw_path,
                "planned_path": pair.jpg_path,
                "action": "validate_existing_jpg",
            }

        for raw in iter_raw_without_jpg(con):
            index += 1
            planned_path = _dedupe_planned_path(
                con,
                _planned_archive_path(
                    raw,
                    _date_count(con, raw),
                    archive_root=jpg_root,
                    event_threshold=10,
                    suffix_override=".jpg",
                ),
            )
            _add_planning_record(
                con,
                kind="raw_to_jpg",
                action="convert_raw_to_jpg_on_windows",
                source_path=raw["path"],
                planned_path=planned_path,
                details_json=json.dumps(
                    {"requires_windows_media_tool_validation": True}, sort_keys=True
                ),
            )
            if index % PLANNING_BATCH_SIZE == 0:
                con.commit()
            yield {
                "source_path": raw["path"],
                "planned_path": planned_path,
                "action": "convert_raw_to_jpg_on_windows",
            }
    finally:
        con.commit()
        con.execute("DROP TABLE IF EXISTS temp.photos_planning_paths")
        con.execute("DROP TABLE IF EXISTS temp.photos_planning_date_counts")


def estimate_required_extra_bytes(con: sqlite3.Connection) -> int:
    total = 0
    rows = con.execute(
        """
        SELECT media_files.size_bytes
        FROM planning_records
        JOIN media_files ON media_files.path = planning_records.source_path
        WHERE planning_records.kind = 'raw_to_jpg'
          AND planning_records.action = 'convert_raw_to_jpg_on_windows'
          AND planning_records.status = 'planned'
          AND media_files.exists_on_disk = 1
        """
    )
    for row in rows:
        total += max(1 * 1024**2, int(row["size_bytes"] * 0.25))
    return total


def storage_budget_status(
    *, free_bytes: int, required_extra_bytes: int, reserve_bytes: int = DEFAULT_RESERVED_BYTES
) -> SpaceBudget:
    return SpaceBudget(
        free_bytes=free_bytes,
        reserve_bytes=reserve_bytes,
        required_extra_bytes=required_extra_bytes,
    )
