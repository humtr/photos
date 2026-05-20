from __future__ import annotations

import re
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath

from .database import add_planning_record
from .pairing import raw_jpg_pairs, raw_without_jpg

DEFAULT_RESERVED_BYTES = 100 * 1024**3
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


def _dedupe_planned_paths(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for path in paths:
        candidate = PurePosixPath(path)
        final = candidate
        index = 2
        while str(final).lower() in seen:
            final = candidate.with_name(f"{candidate.stem}_{index}{candidate.suffix}")
            index += 1
        seen.add(str(final).lower())
        result.append(str(final))
    return result


def build_archive_plans(
    con: sqlite3.Connection, archive_root: str = "archive", event_threshold: int = 10
) -> list[dict[str, str]]:
    con.execute("UPDATE planning_records SET status = 'superseded' WHERE kind = 'archive'")
    rows = list(con.execute("SELECT * FROM media_files WHERE exists_on_disk = 1 ORDER BY path"))
    counts = Counter(_date_key(row) for row in rows)
    planned_paths = [
        _planned_archive_path(
            row,
            counts,
            archive_root=archive_root,
            event_threshold=event_threshold,
        )
        for row in rows
    ]
    planned_paths = _dedupe_planned_paths(planned_paths)

    plans: list[dict[str, str]] = []
    for row, planned_path in zip(rows, planned_paths, strict=True):
        details = {"rel_path": row["rel_path"], "media_type": row["media_type"]}
        add_planning_record(
            con,
            kind="archive",
            action="move_after_approval",
            source_path=row["path"],
            planned_path=planned_path,
            status="planned",
            details=details,
            commit=False,
        )
        plans.append({"source_path": row["path"], "planned_path": planned_path})
    con.commit()
    return plans


def build_raw_to_jpg_plans(
    con: sqlite3.Connection, jpg_root: str = "archive_jpg"
) -> list[dict[str, str]]:
    con.execute("UPDATE planning_records SET status = 'superseded' WHERE kind = 'raw_to_jpg'")
    rows = list(con.execute("SELECT * FROM media_files WHERE exists_on_disk = 1 ORDER BY path"))
    counts = Counter(_date_key(row) for row in rows)
    plans: list[dict[str, str]] = []

    paired_raw_paths = set()
    for pair in raw_jpg_pairs(con):
        paired_raw_paths.add(pair.raw_path)
        add_planning_record(
            con,
            kind="raw_to_jpg",
            action="validate_existing_jpg",
            source_path=pair.raw_path,
            planned_path=pair.jpg_path,
            status="planned",
            details={"confidence": pair.confidence, "reason": pair.reason},
            commit=False,
        )
        plans.append(
            {
                "source_path": pair.raw_path,
                "planned_path": pair.jpg_path,
                "action": "validate_existing_jpg",
            }
        )

    raw_without_pairs = raw_without_jpg(con)
    raw_planned_paths = _dedupe_planned_paths(
        [
            _planned_archive_path(
                raw,
                counts,
                archive_root=jpg_root,
                event_threshold=10,
                suffix_override=".jpg",
            )
            for raw in raw_without_pairs
        ]
    )
    for raw, planned_path in zip(raw_without_pairs, raw_planned_paths, strict=True):
        add_planning_record(
            con,
            kind="raw_to_jpg",
            action="convert_raw_to_jpg_on_windows",
            source_path=raw["path"],
            planned_path=planned_path,
            status="planned",
            details={"requires_windows_media_tool_validation": True},
            commit=False,
        )
        plans.append(
            {
                "source_path": raw["path"],
                "planned_path": planned_path,
                "action": "convert_raw_to_jpg_on_windows",
            }
        )

    con.commit()
    return plans


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
