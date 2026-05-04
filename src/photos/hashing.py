from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def compute_missing_hashes(con: sqlite3.Connection) -> int:
    rows = list(con.execute("SELECT id, path FROM media_files WHERE sha256 IS NULL ORDER BY path"))
    updated = 0
    for row in rows:
        path = Path(row["path"])
        if not path.exists():
            continue
        con.execute(
            "UPDATE media_files SET sha256 = ? WHERE id = ?",
            (sha256_file(path), row["id"]),
        )
        updated += 1
    con.commit()
    return updated


def duplicate_groups(con: sqlite3.Connection) -> list[list[sqlite3.Row]]:
    groups: list[list[sqlite3.Row]] = []
    hashes = con.execute(
        """
        SELECT sha256
        FROM media_files
        WHERE sha256 IS NOT NULL
        GROUP BY sha256
        HAVING COUNT(*) > 1
        ORDER BY sha256
        """
    )
    for row in hashes:
        members = list(
            con.execute(
                "SELECT * FROM media_files WHERE sha256 = ? ORDER BY path",
                (row["sha256"],),
            )
        )
        groups.append(members)
    return groups
