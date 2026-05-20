from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import datetime, timezone

from .schemas import utc_now_iso
from .utils import parse_iso_date


def analyze_duplicates(conn: sqlite3.Connection, scan_root_id: int) -> dict:
    conn.execute("DELETE FROM duplicate_candidates WHERE scan_root_id=?", (scan_root_id,))
    rows = conn.execute(
        """
        SELECT path,folder_path,name,stem,size_bytes,mtime_ns,exif_datetime
        FROM media_files
        WHERE scan_root_id=? AND existence_state='seen'
        """,
        (scan_root_id,),
    ).fetchall()
    by_name: dict[str, list] = defaultdict(list)
    by_stem: dict[str, list] = defaultdict(list)
    for row in rows:
        by_name[str(row["name"]).lower()].append(row)
        by_stem[str(row["stem"]).lower()].append(row)

    inserted = 0
    inserted += _detect_same_name_collision(conn, scan_root_id, by_name)
    inserted += _detect_probable_duplicate(conn, scan_root_id, by_name)
    inserted += _detect_transferred_derivative(conn, scan_root_id, by_stem)
    inserted += _detect_folder_pair_burst(conn, scan_root_id, by_name)
    conn.commit()
    return {"candidate_count": inserted}


def _insert(conn: sqlite3.Connection, scan_root_id: int, key: str, kind: str, left: str, right: str, evidence: dict) -> None:
    conn.execute(
        """
        INSERT INTO duplicate_candidates(scan_root_id,candidate_key,candidate_type,left_path,right_path,evidence_json,status,created_at)
        VALUES(?,?,?,?,?,?,?,?)
        """,
        (scan_root_id, key, kind, left, right, str(evidence), "pending_review", utc_now_iso()),
    )


def _detect_same_name_collision(conn: sqlite3.Connection, scan_root_id: int, by_name: dict[str, list]) -> int:
    c = 0
    for name, group in by_name.items():
        sizes = {int(r["size_bytes"]) for r in group}
        if len(group) > 1 and len(sizes) > 1:
            for i in range(len(group) - 1):
                for j in range(i + 1, len(group)):
                    a, b = group[i], group[j]
                    if int(a["size_bytes"]) == int(b["size_bytes"]):
                        continue
                    _insert(
                        conn,
                        scan_root_id,
                        f"snc:{name}:{i}:{j}",
                        "same_name_collision",
                        str(a["path"]),
                        str(b["path"]),
                        {"name": name, "size_a": int(a["size_bytes"]), "size_b": int(b["size_bytes"])},
                    )
                    c += 1
    return c


def _detect_probable_duplicate(conn: sqlite3.Connection, scan_root_id: int, by_name: dict[str, list]) -> int:
    c = 0
    for name, group in by_name.items():
        if len(group) < 2:
            continue
        for i in range(len(group) - 1):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                if int(a["size_bytes"]) != int(b["size_bytes"]):
                    continue
                date_a = parse_iso_date(str(a["exif_datetime"]) if a["exif_datetime"] else None)
                date_b = parse_iso_date(str(b["exif_datetime"]) if b["exif_datetime"] else None)
                if date_a and date_b and date_a == date_b:
                    _insert(
                        conn,
                        scan_root_id,
                        f"pd:{name}:{i}:{j}",
                        "probable_duplicate",
                        str(a["path"]),
                        str(b["path"]),
                        {"name": name, "size": int(a["size_bytes"]), "date": date_a},
                    )
                    c += 1
    return c


def _detect_transferred_derivative(conn: sqlite3.Connection, scan_root_id: int, by_stem: dict[str, list]) -> int:
    c = 0
    for stem, group in by_stem.items():
        if len(group) < 2:
            continue
        sizes = sorted((int(r["size_bytes"]), str(r["path"]), r) for r in group)
        largest = sizes[-1][0]
        for s, _, row in sizes[:-1]:
            if s < largest:
                _insert(
                    conn,
                    scan_root_id,
                    f"td:{stem}:{row['path']}",
                    "transferred_derivative",
                    str(row["path"]),
                    str(sizes[-1][2]["path"]),
                    {"stem": stem, "smaller_size": s, "larger_size": largest},
                )
                c += 1
    return c


def _detect_folder_pair_burst(conn: sqlite3.Connection, scan_root_id: int, by_name: dict[str, list]) -> int:
    pair_counts: dict[tuple[str, str], int] = defaultdict(int)
    samples: dict[tuple[str, str], tuple[str, str, str]] = {}
    for name, group in by_name.items():
        if len(group) < 2:
            continue
        for i in range(len(group) - 1):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                if int(a["size_bytes"]) != int(b["size_bytes"]):
                    continue
                fa, fb = str(a["folder_path"]), str(b["folder_path"])
                if fa == fb:
                    continue
                pair = tuple(sorted((fa, fb)))
                pair_counts[pair] += 1
                samples[pair] = (str(a["path"]), str(b["path"]), name)
    c = 0
    for pair, count in pair_counts.items():
        if count >= 3:
            left, right, sample_name = samples[pair]
            _insert(
                conn,
                scan_root_id,
                f"fpb:{pair[0]}:{pair[1]}",
                "folder_pair_burst",
                left,
                right,
                {"folder_a": pair[0], "folder_b": pair[1], "match_count": count, "sample_name": sample_name},
            )
            c += 1
    return c
