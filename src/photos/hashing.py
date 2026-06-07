from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from .database import mark_media_missing, record_scan_error

PROGRESS_FRAME_INTERVAL = 1000


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def hash_backlog(con: sqlite3.Connection) -> dict[str, int]:
    row = con.execute(
        """
        SELECT COUNT(*) AS count, COALESCE(SUM(size_bytes), 0) AS bytes
        FROM media_files
        WHERE sha256 IS NULL
          AND exists_on_disk = 1
        """
    ).fetchone()
    return {"count": row["count"], "bytes": row["bytes"]}


def _emit_progress(progress_callback: Callable[[dict[str, Any]], None] | None, payload: dict[str, Any]) -> None:
    if progress_callback is None:
        return
    try:
        progress_callback(payload)
    except Exception:
        pass


def _should_emit_progress(processed: int) -> bool:
    if processed <= 0:
        return False
    if processed == 1:
        return True
    return processed % PROGRESS_FRAME_INTERVAL == 0


def compute_missing_hashes(
    con: sqlite3.Connection,
    *,
    max_files: int | None = None,
    commit_interval: int = 100,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> int:
    backlog = hash_backlog(con)
    batch_size = max(1, min(1000, int(commit_interval or 100)))
    attempted = 0
    updated = 0
    last_path = ""
    target_total = backlog["count"] if max_files is None else min(backlog["count"], max_files)

    _emit_progress(
        progress_callback,
        {
            "operation": "hash_missing",
            "phase": "starting",
            "total": target_total,
            "backlog_count": backlog["count"],
            "backlog_bytes": backlog["bytes"],
            "attempted": attempted,
            "updated": updated,
        },
    )

    while max_files is None or attempted < max_files:
        remaining = batch_size if max_files is None else min(batch_size, max_files - attempted)
        if remaining <= 0:
            break
        rows = con.execute(
            """
            SELECT id, root, path
            FROM media_files
            WHERE sha256 IS NULL
              AND exists_on_disk = 1
              AND path > ?
            ORDER BY path
            LIMIT ?
            """,
            (last_path, remaining),
        ).fetchall()
        if not rows:
            break

        for row in rows:
            attempted += 1
            last_path = row["path"]
            path = Path(row["path"])
            if not path.exists():
                mark_media_missing(
                    con,
                    row["path"],
                    phase="hash",
                    error="file disappeared before hashing",
                )
                con.commit()
                if _should_emit_progress(attempted):
                    _emit_progress(
                        progress_callback,
                        {
                            "operation": "hash_missing",
                            "phase": "hashing",
                            "total": target_total,
                            "backlog_count": backlog["count"],
                            "attempted": attempted,
                            "updated": updated,
                            "current_path": row["path"],
                            "status": "missing",
                        },
                    )
                continue
            try:
                digest = sha256_file(path)
                current = path.stat()
            except OSError as exc:
                record_scan_error(
                    con,
                    root=row["root"],
                    path=row["path"],
                    phase="hash",
                    error=repr(exc),
                )
                con.commit()
                if _should_emit_progress(attempted):
                    _emit_progress(
                        progress_callback,
                        {
                            "operation": "hash_missing",
                            "phase": "hashing",
                            "total": target_total,
                            "backlog_count": backlog["count"],
                            "attempted": attempted,
                            "updated": updated,
                            "current_path": row["path"],
                            "status": "failed",
                            "error_code": exc.__class__.__name__,
                        },
                    )
                continue
            stored = con.execute(
                "SELECT size_bytes, mtime_ns FROM media_files WHERE id = ?",
                (row["id"],),
            ).fetchone()
            file_changed = stored and (
                stored["size_bytes"] != current.st_size or stored["mtime_ns"] != current.st_mtime_ns
            )
            if file_changed:
                con.execute(
                    """
                    UPDATE media_files
                    SET size_bytes = ?, mtime_ns = ?, sha256 = NULL
                    WHERE id = ?
                    """,
                    (current.st_size, current.st_mtime_ns, row["id"]),
                )
                con.commit()
                if _should_emit_progress(attempted):
                    _emit_progress(
                        progress_callback,
                        {
                            "operation": "hash_missing",
                            "phase": "hashing",
                            "total": target_total,
                            "backlog_count": backlog["count"],
                            "attempted": attempted,
                            "updated": updated,
                            "current_path": row["path"],
                            "status": "file_changed",
                        },
                    )
                continue
            con.execute("UPDATE media_files SET sha256 = ? WHERE id = ?", (digest, row["id"]))
            updated += 1
            if _should_emit_progress(attempted):
                _emit_progress(
                    progress_callback,
                    {
                        "operation": "hash_missing",
                        "phase": "hashing",
                        "total": target_total,
                        "backlog_count": backlog["count"],
                        "attempted": attempted,
                        "updated": updated,
                        "current_path": row["path"],
                        "status": "hashed",
                    },
                )
            if commit_interval > 0 and updated % commit_interval == 0:
                con.commit()
        if commit_interval > 0:
            con.commit()
    con.commit()
    _emit_progress(
        progress_callback,
        {
            "operation": "hash_missing",
            "phase": "completed",
            "total": target_total,
            "backlog_count": backlog["count"],
            "attempted": attempted,
            "updated": updated,
        },
    )
    return updated


def iter_duplicate_hash_groups(
    con: sqlite3.Connection,
    *,
    limit: int | None = None,
    offset: int = 0,
) -> Iterator[sqlite3.Row]:
    sql = """
        SELECT sha256
             , COUNT(*) AS member_count
        FROM media_files
        WHERE sha256 IS NOT NULL
          AND exists_on_disk = 1
        GROUP BY sha256
        HAVING COUNT(*) > 1
        ORDER BY sha256
    """
    params: tuple[int, ...] = ()
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params = (max(0, int(limit)), max(0, int(offset)))
    elif offset:
        sql += " LIMIT -1 OFFSET ?"
        params = (max(0, int(offset)),)
    yield from con.execute(sql, params)


def duplicate_group_count(con: sqlite3.Connection) -> int:
    return int(
        con.execute(
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
    )


def iter_duplicate_group_members(
    con: sqlite3.Connection,
    sha256: str,
    *,
    limit: int | None = None,
    offset: int = 0,
) -> Iterator[sqlite3.Row]:
    sql = """
        SELECT *
        FROM media_files
        WHERE sha256 = ?
          AND exists_on_disk = 1
        ORDER BY path
    """
    params: tuple[object, ...] = (sha256,)
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params = (*params, max(0, int(limit)), max(0, int(offset)))
    elif offset:
        sql += " LIMIT -1 OFFSET ?"
        params = (*params, max(0, int(offset)))
    yield from con.execute(sql, params)


def iter_duplicate_groups(
    con: sqlite3.Connection,
    *,
    limit: int | None = None,
    offset: int = 0,
) -> Iterator[list[sqlite3.Row]]:
    """Yield one duplicate group at a time.

    Each yielded group remains complete for compatibility. Consumers that need
    strict per-group bounds should use ``iter_duplicate_hash_groups`` followed
    by ``iter_duplicate_group_members`` with a member limit.
    """

    for row in iter_duplicate_hash_groups(con, limit=limit, offset=offset):
        yield list(iter_duplicate_group_members(con, str(row["sha256"])))


def duplicate_groups_page(
    con: sqlite3.Connection, *, page: int, page_size: int
) -> tuple[list[list[sqlite3.Row]], int]:
    page = max(0, int(page))
    page_size = max(1, min(1000, int(page_size)))
    return (
        list(iter_duplicate_groups(con, limit=page_size, offset=page * page_size)),
        duplicate_group_count(con),
    )


def duplicate_groups(con: sqlite3.Connection) -> list[list[sqlite3.Row]]:
    """Compatibility API that intentionally materializes every duplicate group."""

    return list(iter_duplicate_groups(con))
