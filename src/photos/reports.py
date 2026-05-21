from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
import sqlite3
from collections import Counter
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class ReportEnvelope:
    command: str
    db: str
    ok: bool = True
    summary: dict[str, Any] = field(default_factory=dict)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    started_at: str = field(default_factory=utc_now_iso)
    finished_at: str | None = None

    def finish(self) -> "ReportEnvelope":
        self.finished_at = utc_now_iso()
        if self.errors:
            self.ok = False
        return self

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "ok": self.ok,
            "command": self.command,
            "db": self.db,
            "started_at": self.started_at,
            "finished_at": self.finished_at or utc_now_iso(),
            "summary": self.summary,
            "artifacts": self.artifacts,
            "warnings": self.warnings,
            "errors": self.errors,
        }


def summarize(conn: sqlite3.Connection, scan_root_id: int) -> dict:
    files = conn.execute(
        "SELECT suffix,size_bytes,existence_state FROM media_files WHERE scan_root_id=?",
        (scan_root_id,),
    ).fetchall()
    folders = conn.execute("SELECT attention_flags_json FROM folder_nodes WHERE scan_root_id=?", (scan_root_id,)).fetchall()

    extension_counts: Counter[str] = Counter()
    attention_counts: Counter[str] = Counter()
    seen_files = 0
    total_bytes = 0
    for row in files:
        if str(row["existence_state"]) == "seen":
            seen_files += 1
            total_bytes += int(row["size_bytes"])
            extension_counts[str(row["suffix"])] += 1
    if seen_files == 0:
        ext_rows = conn.execute(
            "SELECT extension_counts_json FROM folder_nodes WHERE scan_root_id=?",
            (scan_root_id,),
        ).fetchall()
        for row in ext_rows:
            counts = json.loads(str(row["extension_counts_json"]))
            for suffix, count in counts.items():
                extension_counts[str(suffix)] += int(count)
        seen_files = int(sum(extension_counts.values()))
    for row in folders:
        flags = json.loads(str(row["attention_flags_json"]))
        for f in flags:
            attention_counts[str(f)] += 1

    folder_count = conn.execute("SELECT COUNT(*) AS c FROM folder_nodes WHERE scan_root_id=?", (scan_root_id,)).fetchone()["c"]
    return {
        "folder_count": int(folder_count),
        "file_count": seen_files,
        "bytes": total_bytes,
        "extension_counts": dict(extension_counts),
        "attention_flag_counts": dict(attention_counts),
    }
