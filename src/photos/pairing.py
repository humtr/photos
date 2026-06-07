from __future__ import annotations

import sqlite3
from collections.abc import Iterator

from .models import RawJpgPair


def iter_raw_jpg_pairs(
    con: sqlite3.Connection,
    *,
    limit: int | None = None,
    offset: int = 0,
) -> Iterator[RawJpgPair]:
    sql = """
        SELECT raw.path AS raw_path, MIN(jpg.path) AS jpg_path
        FROM media_files AS raw
        JOIN media_files AS jpg
          ON jpg.parent_key = raw.parent_key
         AND jpg.stem_key = raw.stem_key
         AND jpg.media_type = 'jpeg'
         AND jpg.exists_on_disk = 1
        WHERE raw.media_type = 'raw'
          AND raw.exists_on_disk = 1
        GROUP BY raw.id, raw.path
        ORDER BY raw.path
    """
    params: tuple[int, ...] = ()
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params = (limit, offset)
    elif offset:
        sql += " LIMIT -1 OFFSET ?"
        params = (offset,)
    for row in con.execute(sql, params):
        yield RawJpgPair(
            raw_path=row["raw_path"],
            jpg_path=row["jpg_path"],
            confidence="high",
            reason="same folder and basename",
        )


def raw_jpg_pair_count(con: sqlite3.Connection) -> int:
    return con.execute(
        """
        SELECT COUNT(*) AS count
        FROM media_files AS raw
        WHERE raw.media_type = 'raw'
          AND raw.exists_on_disk = 1
          AND EXISTS (
              SELECT 1
              FROM media_files AS jpg
              WHERE jpg.parent_key = raw.parent_key
                AND jpg.stem_key = raw.stem_key
                AND jpg.media_type = 'jpeg'
                AND jpg.exists_on_disk = 1
          )
        """
    ).fetchone()["count"]


def raw_jpg_pairs_page(
    con: sqlite3.Connection, *, page: int, page_size: int
) -> tuple[list[RawJpgPair], int]:
    return (
        list(iter_raw_jpg_pairs(con, limit=page_size, offset=page * page_size)),
        raw_jpg_pair_count(con),
    )


def raw_jpg_pairs(con: sqlite3.Connection) -> list[RawJpgPair]:
    return list(iter_raw_jpg_pairs(con))


def raw_paths_with_pairs(con: sqlite3.Connection) -> set[str]:
    return {pair.raw_path for pair in iter_raw_jpg_pairs(con)}


def iter_raw_without_jpg(
    con: sqlite3.Connection,
    *,
    limit: int | None = None,
    offset: int = 0,
) -> Iterator[sqlite3.Row]:
    sql = """
        SELECT raw.*
        FROM media_files AS raw
        WHERE raw.media_type = 'raw'
          AND raw.exists_on_disk = 1
          AND NOT EXISTS (
              SELECT 1
              FROM media_files AS jpg
              WHERE jpg.parent_key = raw.parent_key
                AND jpg.stem_key = raw.stem_key
                AND jpg.media_type = 'jpeg'
                AND jpg.exists_on_disk = 1
          )
        ORDER BY raw.path
    """
    params: tuple[int, ...] = ()
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params = (limit, offset)
    elif offset:
        sql += " LIMIT -1 OFFSET ?"
        params = (offset,)
    yield from con.execute(sql, params)


def raw_without_jpg_count(con: sqlite3.Connection) -> int:
    return con.execute(
        """
        SELECT COUNT(*) AS count
        FROM media_files AS raw
        WHERE raw.media_type = 'raw'
          AND raw.exists_on_disk = 1
          AND NOT EXISTS (
              SELECT 1
              FROM media_files AS jpg
              WHERE jpg.parent_key = raw.parent_key
                AND jpg.stem_key = raw.stem_key
                AND jpg.media_type = 'jpeg'
                AND jpg.exists_on_disk = 1
          )
        """
    ).fetchone()["count"]


def raw_without_jpg(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(iter_raw_without_jpg(con))


def raw_without_jpg_page(
    con: sqlite3.Connection, *, page: int, page_size: int
) -> tuple[list[sqlite3.Row], int]:
    return (
        list(iter_raw_without_jpg(con, limit=page_size, offset=page * page_size)),
        raw_without_jpg_count(con),
    )


def find_duplicate_candidate_buckets(con: sqlite3.Connection) -> list[dict[str, object]]:
    buckets = con.execute(
        """
        SELECT suffix, size_bytes
        FROM media_files
        WHERE exists_on_disk = 1
        GROUP BY suffix, size_bytes
        HAVING COUNT(*) > 1
        ORDER BY suffix, size_bytes
        """
    ).fetchall()

    results: list[dict[str, object]] = []
    for bucket in buckets:
        members = con.execute(
            """
            SELECT *
            FROM media_files
            WHERE exists_on_disk = 1
              AND suffix = ?
              AND size_bytes = ?
            ORDER BY path
            """,
            (bucket["suffix"], bucket["size_bytes"]),
        ).fetchall()
        results.append(
            {
                "suffix": bucket["suffix"],
                "size": bucket["size_bytes"],
                "members": list(members),
            }
        )
    return results
