from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone

from .schemas import utc_now_iso
from .utils import json_dumps, parse_folder_date, parse_iso_date


def audit_dates(conn: sqlite3.Connection, scan_root_id: int) -> dict:
    conn.execute("DELETE FROM metadata_audits WHERE scan_root_id=?", (scan_root_id,))
    rows = conn.execute(
        """
        SELECT folder_path,path,exif_datetime,mtime_ns,size_bytes
        FROM media_files
        WHERE scan_root_id=? AND existence_state='seen'
        """,
        (scan_root_id,),
    ).fetchall()
    by_folder: dict[str, list] = defaultdict(list)
    for row in rows:
        by_folder[str(row["folder_path"])].append(row)

    issues = 0
    for folder, items in by_folder.items():
        folder_date = parse_folder_date(folder)
        exif_dates = [parse_iso_date(str(r["exif_datetime"])) for r in items if r["exif_datetime"]]
        exif_dates = [d for d in exif_dates if d]
        mtime_dates = [datetime.fromtimestamp(int(r["mtime_ns"]) / 1_000_000_000, tz=timezone.utc).date().isoformat() for r in items]

        dominant_exif = Counter(exif_dates).most_common(1)[0][0] if exif_dates else None
        dominant_mtime = Counter(mtime_dates).most_common(1)[0][0] if mtime_dates else None

        if folder_date and dominant_exif and folder_date[:7] != dominant_exif[:7]:
            _insert_issue(
                conn,
                scan_root_id,
                folder,
                "folder_date_vs_exif_month_mismatch",
                "medium",
                {"folder_date": folder_date, "dominant_exif": dominant_exif, "count": len(items)},
            )
            issues += 1
        if dominant_exif and dominant_mtime and dominant_exif[:7] != dominant_mtime[:7]:
            _insert_issue(
                conn,
                scan_root_id,
                folder,
                "exif_vs_mtime_month_mismatch",
                "low",
                {"dominant_exif": dominant_exif, "dominant_mtime": dominant_mtime, "count": len(items)},
            )
            issues += 1
        if not exif_dates:
            _insert_issue(
                conn,
                scan_root_id,
                folder,
                "missing_exif_dates",
                "low",
                {"count": len(items)},
            )
            issues += 1
    conn.commit()
    return {"issue_count": issues}


def _insert_issue(
    conn: sqlite3.Connection,
    scan_root_id: int,
    folder: str,
    issue_type: str,
    severity: str,
    evidence: dict,
) -> None:
    conn.execute(
        """
        INSERT INTO metadata_audits(scan_root_id,folder_path,issue_type,severity,evidence_json,created_at)
        VALUES(?,?,?,?,?,?)
        """,
        (scan_root_id, folder, issue_type, severity, json_dumps(evidence), utc_now_iso()),
    )
