from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from .database import mark_media_missing, record_scan_error


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


def compute_missing_hashes(
    con: sqlite3.Connection, *, max_files: int | None = None, commit_interval: int = 100
) -> int:
    limit = "" if max_files is None else "LIMIT ?"
    params: tuple[int, ...] = () if max_files is None else (max_files,)
    rows = list(
        con.execute(
            f"""
            SELECT id, root, path
            FROM media_files
            WHERE sha256 IS NULL
              AND exists_on_disk = 1
            ORDER BY path
            {limit}
            """,
            params,
        )
    )
    updated = 0
    for row in rows:
        path = Path(row["path"])
        if not path.exists():
            mark_media_missing(
                con,
                row["path"],
                phase="hash",
                error="file disappeared before hashing",
            )
            con.commit()
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
            continue
        con.execute("UPDATE media_files SET sha256 = ? WHERE id = ?", (digest, row["id"]))
        updated += 1
        if commit_interval > 0 and updated % commit_interval == 0:
            con.commit()
    con.commit()
    return updated


def duplicate_groups(con: sqlite3.Connection) -> list[list[sqlite3.Row]]:
    groups: list[list[sqlite3.Row]] = []
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
    for row in hashes:
        members = list(
            con.execute(
                """
                SELECT *
                FROM media_files
                WHERE sha256 = ?
                  AND exists_on_disk = 1
                ORDER BY path
                """,
                (row["sha256"],),
            )
        )
        groups.append(members)
    return groups
