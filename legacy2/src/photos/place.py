from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict

from .schemas import utc_now_iso


def gps_key(lat: float, lon: float) -> str:
    return f"{lat:.3f},{lon:.3f}"


def enrich_places(conn: sqlite3.Connection, scan_root_id: int, gps_mode: str = "summary") -> dict:
    del gps_mode
    rows = conn.execute(
        """
        SELECT folder_path,gps_lat,gps_lon
        FROM media_files
        WHERE scan_root_id=? AND existence_state='seen' AND gps_lat IS NOT NULL AND gps_lon IS NOT NULL
        """,
        (scan_root_id,),
    ).fetchall()
    folder_labels: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        key = gps_key(float(row["gps_lat"]), float(row["gps_lon"]))
        label = _lookup_or_insert_place(conn, key)
        folder_labels[str(row["folder_path"])].append(label)
    updated = 0
    for folder, labels in folder_labels.items():
        dominant = Counter(labels).most_common(1)[0][0] if labels else None
        conn.execute(
            """
            INSERT INTO folder_places(scan_root_id,folder_path,dominant_place,sample_count,updated_at)
            VALUES(?,?,?,?,?)
            ON CONFLICT(scan_root_id,folder_path) DO UPDATE SET
              dominant_place=excluded.dominant_place,
              sample_count=excluded.sample_count,
              updated_at=excluded.updated_at
            """,
            (scan_root_id, folder, dominant, len(labels), utc_now_iso()),
        )
        updated += 1
    conn.commit()
    return {"folders_with_place": updated, "gps_points": len(rows)}


def _lookup_or_insert_place(conn: sqlite3.Connection, key: str) -> str:
    row = conn.execute("SELECT place_label FROM place_cache WHERE gps_key=?", (key,)).fetchone()
    if row:
        return str(row["place_label"])
    label = f"GPS({key})"
    conn.execute(
        "INSERT INTO place_cache(gps_key,place_label,source,created_at) VALUES(?,?,?,?)",
        (key, label, "summary_cache", utc_now_iso()),
    )
    return label
