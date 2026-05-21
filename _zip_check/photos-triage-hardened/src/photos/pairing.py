from __future__ import annotations

import sqlite3

from .models import RawJpgPair


def raw_jpg_pairs(con: sqlite3.Connection) -> list[RawJpgPair]:
    """Return RAW/JPG pairs using SQL-side lookup instead of a full Python index."""

    pairs: list[RawJpgPair] = []
    for row in con.execute(
        """
        SELECT
            raw.path AS raw_path,
            (
                SELECT jpg.path
                FROM media_files AS jpg
                WHERE jpg.media_type = 'jpeg'
                  AND jpg.exists_on_disk = 1
                  AND jpg.parent_key = raw.parent_key
                  AND jpg.stem_key = raw.stem_key
                ORDER BY jpg.path
                LIMIT 1
            ) AS jpg_path
        FROM media_files AS raw
        WHERE raw.media_type = 'raw'
          AND raw.exists_on_disk = 1
          AND EXISTS (
                SELECT 1
                FROM media_files AS jpg
                WHERE jpg.media_type = 'jpeg'
                  AND jpg.exists_on_disk = 1
                  AND jpg.parent_key = raw.parent_key
                  AND jpg.stem_key = raw.stem_key
          )
        ORDER BY raw.path
        """
    ):
        pairs.append(
            RawJpgPair(
                raw_path=row["raw_path"],
                jpg_path=row["jpg_path"],
                confidence="high",
                reason="same folder and basename",
            )
        )
    return pairs


def raw_paths_with_pairs(con: sqlite3.Connection) -> set[str]:
    return {pair.raw_path for pair in raw_jpg_pairs(con)}


def raw_without_jpg(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        con.execute(
            """
            SELECT raw.*
            FROM media_files AS raw
            WHERE raw.media_type = 'raw'
              AND raw.exists_on_disk = 1
              AND NOT EXISTS (
                    SELECT 1
                    FROM media_files AS jpg
                    WHERE jpg.media_type = 'jpeg'
                      AND jpg.exists_on_disk = 1
                      AND jpg.parent_key = raw.parent_key
                      AND jpg.stem_key = raw.stem_key
              )
            ORDER BY raw.path
            """
        )
    )
