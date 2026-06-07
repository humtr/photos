from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from typing import Any

from .database import utc_now

MAX_DATE_AUDIT_PAGE_SIZE = 1000
DEFAULT_DATE_AUDIT_ITEMS_PER_GROUP = 50
MAX_DATE_AUDIT_ITEMS_PER_GROUP = 200

_DATE_PATTERNS = [
    re.compile(r"(?<!\d)(20\d{2}|19\d{2})[-_. ]?(0[1-9]|1[0-2])[-_. ]?([0-2]\d|3[01])(?!\d)"),
    re.compile(r"(?<!\d)(20\d{2}|19\d{2})[-_. ](0[1-9]|1[0-2])(?!\d)"),
]


def _json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=False)


def _date_from_text(text: str) -> str | None:
    for pattern in _DATE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        year = match.group(1)
        month = match.group(2)
        day = match.group(3) if len(match.groups()) >= 3 and match.group(3) else "01"
        try:
            datetime(int(year), int(month), int(day))
        except ValueError:
            continue
        return f"{year}-{month}-{day}"
    return None


def _filesystem_date(mtime_ns: int) -> str:
    return datetime.fromtimestamp(mtime_ns / 1_000_000_000).strftime("%Y-%m-%d")


def _update_group_evidence(
    con: sqlite3.Connection,
    *,
    folder: str,
    groups: dict[str, tuple[int, int]],
) -> None:
    for issue, (group_id, item_count) in groups.items():
        evidence = {
            "folder_path": folder,
            "issue_type": issue,
            "item_count": item_count,
            "rule": "filename_folder_filesystem_date_comparison",
        }
        con.execute(
            "UPDATE date_audit_groups SET evidence_json = ? WHERE id = ?",
            (_json(evidence), group_id),
        )


def refresh_date_audit(con: sqlite3.Connection) -> dict[str, Any]:
    """Find date evidence conflicts using filename, folder name, and filesystem mtime.

    This implementation deliberately does not write EXIF. It creates review records only.
    """

    con.execute("DELETE FROM date_audit_items")
    con.execute("DELETE FROM date_audit_groups")

    current_folder: str | None = None
    current_groups: dict[str, tuple[int, int]] = {}
    inserted_groups = 0
    inserted_items = 0
    for row in con.execute(
        """
        SELECT path, rel_path, parent_key, name, mtime_ns
        FROM media_files
        WHERE exists_on_disk = 1
        ORDER BY parent_key, path
        """
    ):
        folder = str(row["parent_key"])
        if current_folder != folder:
            if current_folder is not None:
                _update_group_evidence(con, folder=current_folder, groups=current_groups)
            current_folder = folder
            current_groups = {}

        path = str(row["path"])
        filename_date = _date_from_text(str(row["name"]))
        folder_date = _date_from_text(folder)
        filesystem_date = _filesystem_date(int(row["mtime_ns"]))
        signals = [value for value in [filename_date, folder_date, filesystem_date] if value]
        signal_years = {value[:4] for value in signals}
        if filename_date and folder_date and filename_date[:7] != folder_date[:7]:
            issue = "filename_folder_date_conflict"
        elif len(signal_years) > 1:
            issue = "filesystem_date_year_conflict"
        else:
            continue
        proposed = filename_date or folder_date or filesystem_date
        group = current_groups.get(issue)
        if group is None:
            evidence = {
                "folder_path": folder,
                "issue_type": issue,
                "item_count": 0,
                "rule": "filename_folder_filesystem_date_comparison",
            }
            cur = con.execute(
                """
                INSERT INTO date_audit_groups(
                    folder_path, issue_type, confidence, evidence_json, status, created_at
                )
                VALUES(?, ?, ?, ?, 'pending_review', ?)
                """,
                (folder, issue, 0.65, _json(evidence), utc_now()),
            )
            group_id = int(cur.lastrowid)
            item_count = 0
            inserted_groups += 1
        else:
            group_id, item_count = group
        con.execute(
            """
            INSERT INTO date_audit_items(
                group_id, path, filename_date, folder_date, filesystem_date,
                proposed_canonical_date, status
            )
            VALUES(?, ?, ?, ?, ?, ?, 'pending_review')
            """,
            (
                group_id,
                path,
                filename_date,
                folder_date,
                filesystem_date,
                proposed,
            ),
        )
        inserted_items += 1
        current_groups[issue] = (group_id, item_count + 1)

    if current_folder is not None:
        _update_group_evidence(con, folder=current_folder, groups=current_groups)
    con.commit()
    return {"group_count": inserted_groups, "item_count": inserted_items}


def list_date_audits(
    con: sqlite3.Connection,
    *,
    limit: int = 100,
    offset: int = 0,
    item_limit: int = DEFAULT_DATE_AUDIT_ITEMS_PER_GROUP,
) -> dict[str, Any]:
    total = int(con.execute("SELECT COUNT(*) AS count FROM date_audit_groups").fetchone()["count"])
    rows = []
    page_limit = max(1, min(MAX_DATE_AUDIT_PAGE_SIZE, int(limit)))
    group_item_limit = max(1, min(MAX_DATE_AUDIT_ITEMS_PER_GROUP, int(item_limit)))
    for group in con.execute(
        """
        SELECT * FROM date_audit_groups
        ORDER BY status, issue_type, folder_path
        LIMIT ? OFFSET ?
        """,
        (page_limit, max(0, int(offset))),
    ):
        items = con.execute(
            """
            SELECT * FROM date_audit_items
            WHERE group_id = ?
            ORDER BY path
            LIMIT ?
            """,
            (group["id"], group_item_limit),
        ).fetchall()
        rows.append(
            {
                "id": group["id"],
                "folder_path": group["folder_path"],
                "issue_type": group["issue_type"],
                "confidence": group["confidence"],
                "status": group["status"],
                "evidence": json.loads(group["evidence_json"] or "{}"),
                "items": [dict(item) for item in items],
            }
        )
    return {"total": total, "rows": rows}
