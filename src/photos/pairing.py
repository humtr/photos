from __future__ import annotations

import sqlite3
from collections import defaultdict

from .models import RawJpgPair


def raw_jpg_pairs(con: sqlite3.Connection) -> list[RawJpgPair]:
    jpg_rows = con.execute(
        "SELECT * FROM media_files WHERE media_type = 'jpeg' ORDER BY path"
    )
    jpg_by_key: dict[tuple[str, str], list[sqlite3.Row]] = defaultdict(list)
    for row in jpg_rows:
        jpg_by_key[(row["parent_key"], row["stem_key"])].append(row)

    pairs: list[RawJpgPair] = []
    raw_rows = con.execute("SELECT * FROM media_files WHERE media_type = 'raw' ORDER BY path")
    for raw in raw_rows:
        matches = jpg_by_key.get((raw["parent_key"], raw["stem_key"]), [])
        if not matches:
            continue
        pairs.append(
            RawJpgPair(
                raw_path=raw["path"],
                jpg_path=matches[0]["path"],
                confidence="high",
                reason="same folder and basename",
            )
        )
    return pairs


def raw_paths_with_pairs(con: sqlite3.Connection) -> set[str]:
    return {pair.raw_path for pair in raw_jpg_pairs(con)}


def raw_without_jpg(con: sqlite3.Connection) -> list[sqlite3.Row]:
    paired = raw_paths_with_pairs(con)
    rows = list(con.execute("SELECT * FROM media_files WHERE media_type = 'raw' ORDER BY path"))
    return [row for row in rows if row["path"] not in paired]
