from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .schemas import utc_now_iso
from .utils import json_dumps, parse_folder_date, parse_iso_date


def audit_dates(conn: sqlite3.Connection, scan_root_id: int) -> dict:
    conn.execute("DELETE FROM metadata_audits WHERE scan_root_id=?", (scan_root_id,))
    conn.execute("DELETE FROM date_audit_items")
    conn.execute("DELETE FROM date_audit_groups")
    conn.execute("DELETE FROM metadata_edit_suggestions")
    folder_places = _folder_places(conn, scan_root_id)
    rows = conn.execute(
        """
        SELECT folder_path,path,name,exif_datetime,ctime_ns,mtime_ns,size_bytes,gps_lat,gps_lon
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
        facts = [_date_facts(row, folder) for row in items]
        folder_date = parse_folder_date(folder)
        exif_dates = [f["exif_date"] for f in facts if f["exif_date"]]
        filename_dates = [f["filename_date"] for f in facts if f["filename_date"]]
        mtime_dates = [f["filesystem_mtime_date"] for f in facts if f["filesystem_mtime_date"]]
        ctime_dates = [f["filesystem_ctime_date"] for f in facts if f["filesystem_ctime_date"]]
        sequence_range = _sequence_date_range(filename_dates)
        sequence_date = sequence_range["start"] if sequence_range and sequence_range["start"] == sequence_range["end"] else None
        gps_context = _gps_context(facts)

        dominant_exif = _dominant(exif_dates)
        dominant_filename = _dominant(filename_dates)
        dominant_mtime = _dominant(mtime_dates)
        dominant_ctime = _dominant(ctime_dates)
        canonical = _choose_canonical_date(folder_date, dominant_filename, sequence_date, dominant_exif, dominant_mtime)
        issue_types = _classify_folder_dates(
            folder_date,
            dominant_filename,
            sequence_date,
            dominant_exif,
            dominant_mtime,
            dominant_ctime,
            bool(exif_dates),
        )

        for issue_type, confidence in issue_types:
            evidence = {
                "folder_date": folder_date,
                "dominant_filename": dominant_filename,
                "sequence_date_range": sequence_range,
                "dominant_exif": dominant_exif,
                "dominant_filesystem": dominant_mtime,
                "dominant_filesystem_mtime": dominant_mtime,
                "dominant_filesystem_ctime": dominant_ctime,
                "filesystem_dates": {"mtime": mtime_dates, "ctime": ctime_dates},
                "folder_place": folder_places.get(folder),
                "gps_context": gps_context,
                "proposed_canonical_date": canonical,
                "count": len(items),
            }
            group_id = _insert_group(conn, folder, issue_type, confidence, evidence)
            _insert_issue(conn, scan_root_id, folder, issue_type, _severity(confidence), evidence)
            for fact in facts:
                _insert_item(conn, group_id, fact, canonical)
                if canonical and fact["exif_date"] != canonical:
                    _insert_metadata_suggestion(conn, fact["path"], canonical, issue_type, evidence)
            issues += 1
    conn.commit()
    return {"issue_count": issues}


def _dominant(values: list[str]) -> str | None:
    return Counter(values).most_common(1)[0][0] if values else None


def _month(value: str | None) -> str | None:
    return value[:7] if value else None


def _fs_date(mtime_ns: int) -> str:
    return datetime.fromtimestamp(mtime_ns / 1_000_000_000, tz=timezone.utc).date().isoformat()


def _date_facts(row: sqlite3.Row, folder: str) -> dict:
    filename_date = parse_folder_date(str(row["name"])) or parse_folder_date(Path(str(row["path"])).name)
    mtime_date = _fs_date(int(row["mtime_ns"]))
    ctime_date = _fs_date(int(row["ctime_ns"]))
    return {
        "path": str(row["path"]),
        "filename_date": filename_date,
        "folder_date": parse_folder_date(folder),
        "exif_date": parse_iso_date(str(row["exif_datetime"])) if row["exif_datetime"] else None,
        "filesystem_date": mtime_date,
        "filesystem_mtime_date": mtime_date,
        "filesystem_ctime_date": ctime_date,
        "gps_lat": float(row["gps_lat"]) if row["gps_lat"] is not None else None,
        "gps_lon": float(row["gps_lon"]) if row["gps_lon"] is not None else None,
    }


def _choose_canonical_date(
    folder_date: str | None,
    filename_date: str | None,
    sequence_date: str | None,
    exif_date: str | None,
    filesystem_date: str | None,
) -> str | None:
    if folder_date and filename_date and _month(folder_date) == _month(filename_date):
        return folder_date
    if sequence_date:
        return sequence_date
    if exif_date:
        return exif_date
    if filename_date:
        return filename_date
    if folder_date:
        return folder_date
    return filesystem_date


def _classify_folder_dates(
    folder_date: str | None,
    filename_date: str | None,
    sequence_date: str | None,
    exif_date: str | None,
    filesystem_mtime_date: str | None,
    filesystem_ctime_date: str | None,
    has_exif: bool,
) -> list[tuple[str, float]]:
    issues: list[tuple[str, float]] = []
    folder_month = _month(folder_date)
    filename_month = _month(filename_date)
    sequence_month = _month(sequence_date)
    exif_month = _month(exif_date)
    mtime_month = _month(filesystem_mtime_date)
    ctime_month = _month(filesystem_ctime_date)

    if not has_exif:
        issues.append(("missing_exif_cluster", 0.55))

    if folder_month and exif_month and folder_month != exif_month:
        issues.append(("folder_date_conflict", 0.78))

    local_month = folder_month or filename_month or sequence_month
    if local_month and exif_month and exif_month != local_month:
        issues.append(("exif_untrusted_cluster", 0.86))

    trusted_month = folder_month or filename_month or sequence_month or exif_month
    if trusted_month and (mtime_month and trusted_month != mtime_month or ctime_month and trusted_month != ctime_month):
        issues.append(("filesystem_backup_date_suspected", 0.65))

    months = {m for m in [folder_month, filename_month, sequence_month, exif_month, mtime_month, ctime_month] if m}
    if len(months) >= 3:
        issues.append(("date_conflict_cluster", 0.70))

    return issues


def _sequence_date_range(values: list[str]) -> dict | None:
    unique = sorted(set(values))
    if not unique:
        return None
    return {"start": unique[0], "end": unique[-1], "count": len(values), "unique_count": len(unique)}


def _gps_context(facts: list[dict]) -> dict:
    samples = [
        {"path": f["path"], "gps_lat": f["gps_lat"], "gps_lon": f["gps_lon"]}
        for f in facts
        if f["gps_lat"] is not None and f["gps_lon"] is not None
    ]
    return {"gps_file_count": len(samples), "samples": samples[:5]}


def _folder_places(conn: sqlite3.Connection, scan_root_id: int) -> dict[str, dict]:
    rows = conn.execute(
        """
        SELECT folder_path,dominant_place,sample_count
        FROM folder_places
        WHERE scan_root_id=?
        """,
        (scan_root_id,),
    ).fetchall()
    return {
        str(row["folder_path"]): {
            "dominant_place": row["dominant_place"],
            "sample_count": int(row["sample_count"]),
        }
        for row in rows
    }


def _severity(confidence: float) -> str:
    if confidence >= 0.80:
        return "high"
    if confidence >= 0.65:
        return "medium"
    return "low"


def _insert_group(conn: sqlite3.Connection, folder: str, issue_type: str, confidence: float, evidence: dict) -> int:
    cur = conn.execute(
        """
        INSERT INTO date_audit_groups(folder_path, issue_type, confidence, evidence_json, status)
        VALUES(?,?,?,?,?)
        """,
        (folder, issue_type, confidence, json_dumps(evidence), "pending_review"),
    )
    return int(cur.lastrowid)


def _insert_item(conn: sqlite3.Connection, group_id: int, fact: dict, canonical: str | None) -> None:
    conn.execute(
        """
        INSERT INTO date_audit_items(
            group_id,path,filename_date,folder_date,exif_date,filesystem_date,proposed_canonical_date,status
        )
        VALUES(?,?,?,?,?,?,?,?)
        """,
        (
            group_id,
            fact["path"],
            fact["filename_date"],
            fact["folder_date"],
            fact["exif_date"],
            fact["filesystem_date"],
            canonical,
            "pending_review",
        ),
    )


def _insert_metadata_suggestion(conn: sqlite3.Connection, path: str, canonical: str, issue_type: str, evidence: dict) -> None:
    conn.execute(
        """
        INSERT INTO metadata_edit_suggestions(target_type,target_path,proposed_value,source,status,reason_json)
        VALUES(?,?,?,?,?,?)
        """,
        ("media_file", path, canonical, issue_type, "pending_approval", json_dumps(evidence)),
    )


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
