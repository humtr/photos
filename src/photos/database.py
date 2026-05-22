from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import MediaRecord

SCHEMA_VERSION = 2


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(path: str | Path = ":memory:") -> sqlite3.Connection:
    if path != ":memory:":
        path = Path(path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout = 5000")
    init_db(con)
    return con


def _column_names(con: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in con.execute(f"PRAGMA table_info({table})")}


def _ensure_column(con: sqlite3.Connection, table: str, definition: str) -> None:
    column = definition.split(maxsplit=1)[0]
    if column not in _column_names(con, table):
        con.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")


def init_db(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS media_files (
            id INTEGER PRIMARY KEY,
            root TEXT NOT NULL,
            path TEXT NOT NULL UNIQUE,
            rel_path TEXT NOT NULL,
            parent_key TEXT NOT NULL,
            name TEXT NOT NULL,
            stem_key TEXT NOT NULL,
            suffix TEXT NOT NULL,
            media_type TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            mtime_ns INTEGER NOT NULL,
            sha256 TEXT,
            indexed_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_media_sha256 ON media_files(sha256);
        CREATE INDEX IF NOT EXISTS idx_media_pairing ON media_files(parent_key, stem_key);
        CREATE INDEX IF NOT EXISTS idx_media_type ON media_files(media_type);
        CREATE INDEX IF NOT EXISTS idx_media_suffix_size ON media_files(suffix, size_bytes);
        CREATE INDEX IF NOT EXISTS idx_media_name ON media_files(name);

        CREATE TABLE IF NOT EXISTS review_decisions (
            id INTEGER PRIMARY KEY,
            group_key TEXT NOT NULL,
            path TEXT NOT NULL,
            decision TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            UNIQUE(group_key, path)
        );

        CREATE TABLE IF NOT EXISTS planning_records (
            id INTEGER PRIMARY KEY,
            kind TEXT NOT NULL,
            action TEXT NOT NULL,
            source_path TEXT NOT NULL,
            planned_path TEXT NOT NULL,
            status TEXT NOT NULL,
            details_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(kind, action, source_path, planned_path)
        );

        CREATE TABLE IF NOT EXISTS deletion_manifests (
            id INTEGER PRIMARY KEY,
            manifest_path TEXT NOT NULL,
            candidates_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS pipeline_runs (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            details_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS classification_results (
            path TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            confidence REAL,
            model TEXT NOT NULL DEFAULT '',
            details_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS scan_errors (
            id INTEGER PRIMARY KEY,
            root TEXT NOT NULL,
            path TEXT NOT NULL,
            phase TEXT NOT NULL,
            error TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_scan_errors_path ON scan_errors(path);
        CREATE INDEX IF NOT EXISTS idx_scan_errors_phase ON scan_errors(phase);
        """
    )
    _ensure_column(con, "media_files", "exists_on_disk INTEGER NOT NULL DEFAULT 1")
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_media_exists_path ON media_files(exists_on_disk, path)"
    )
    _ensure_column(con, "media_files", "missing_at TEXT")
    _ensure_column(con, "media_files", "last_seen_at TEXT NOT NULL DEFAULT ''")
    con.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    con.commit()


def upsert_media_file(
    con: sqlite3.Connection, record: MediaRecord, *, seen_at: str | None = None
) -> None:
    timestamp = seen_at or utc_now()
    con.execute(
        """
        INSERT INTO media_files(
            root, path, rel_path, parent_key, name, stem_key, suffix, media_type,
            size_bytes, mtime_ns, sha256, indexed_at, exists_on_disk, missing_at, last_seen_at
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, NULL, ?)
        ON CONFLICT(path) DO UPDATE SET
            root = excluded.root,
            rel_path = excluded.rel_path,
            parent_key = excluded.parent_key,
            name = excluded.name,
            stem_key = excluded.stem_key,
            suffix = excluded.suffix,
            media_type = excluded.media_type,
            size_bytes = excluded.size_bytes,
            mtime_ns = excluded.mtime_ns,
            sha256 = CASE
                WHEN media_files.size_bytes != excluded.size_bytes
                  OR media_files.mtime_ns != excluded.mtime_ns
                THEN excluded.sha256
                ELSE COALESCE(media_files.sha256, excluded.sha256)
            END,
            indexed_at = excluded.indexed_at,
            exists_on_disk = 1,
            missing_at = NULL,
            last_seen_at = excluded.last_seen_at
        """,
        (
            record.root,
            record.path,
            record.rel_path,
            record.parent_key,
            record.name,
            record.stem_key,
            record.suffix,
            record.media_type,
            record.size_bytes,
            record.mtime_ns,
            record.sha256,
            timestamp,
            timestamp,
        ),
    )


def list_media(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(con.execute("SELECT * FROM media_files WHERE exists_on_disk = 1 ORDER BY path"))


def mark_missing_media_files(con: sqlite3.Connection, *, root: str, scan_started_at: str) -> int:
    cur = con.execute(
        """
        UPDATE media_files
        SET exists_on_disk = 0, missing_at = ?
        WHERE root = ?
          AND exists_on_disk = 1
          AND last_seen_at < ?
        """,
        (utc_now(), root, scan_started_at),
    )
    return int(cur.rowcount)


def mark_media_missing(con: sqlite3.Connection, path: str, *, phase: str, error: str = "") -> None:
    con.execute(
        """
        UPDATE media_files
        SET exists_on_disk = 0, missing_at = ?
        WHERE path = ?
        """,
        (utc_now(), path),
    )
    if error:
        row = con.execute("SELECT root FROM media_files WHERE path = ?", (path,)).fetchone()
        record_scan_error(
            con,
            root=row["root"] if row else "",
            path=path,
            phase=phase,
            error=error,
        )


def record_scan_error(
    con: sqlite3.Connection,
    *,
    root: str,
    path: str,
    phase: str,
    error: str,
) -> None:
    con.execute(
        """
        INSERT INTO scan_errors(root, path, phase, error, created_at)
        VALUES(?, ?, ?, ?, ?)
        """,
        (root, path, phase, error, utc_now()),
    )


def record_review_decision(
    con: sqlite3.Connection, group_key: str, path: str, decision: str, note: str = ""
) -> None:
    con.execute(
        """
        INSERT INTO review_decisions(group_key, path, decision, note, updated_at)
        VALUES(?, ?, ?, ?, ?)
        ON CONFLICT(group_key, path) DO UPDATE SET
            decision = excluded.decision,
            note = excluded.note,
            updated_at = excluded.updated_at
        """,
        (group_key, path, decision, note, utc_now()),
    )
    con.commit()


def record_classification_result(
    con: sqlite3.Connection,
    *,
    path: str,
    label: str,
    confidence: float | None = None,
    model: str = "",
    details: dict[str, Any] | None = None,
) -> None:
    con.execute(
        """
        INSERT INTO classification_results(path, label, confidence, model, details_json, updated_at)
        VALUES(?, ?, ?, ?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
            label = excluded.label,
            confidence = excluded.confidence,
            model = excluded.model,
            details_json = excluded.details_json,
            updated_at = excluded.updated_at
        """,
        (path, label, confidence, model, json.dumps(details or {}, sort_keys=True), utc_now()),
    )
    con.commit()


def add_planning_record(
    con: sqlite3.Connection,
    *,
    kind: str,
    action: str,
    source_path: str,
    planned_path: str,
    status: str,
    details: dict[str, Any],
) -> None:
    con.execute(
        """
        INSERT INTO planning_records(
            kind, action, source_path, planned_path, status, details_json, created_at
        )
        VALUES(?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(kind, action, source_path, planned_path) DO UPDATE SET
            status = excluded.status,
            details_json = excluded.details_json
        """,
        (
            kind,
            action,
            source_path,
            planned_path,
            status,
            json.dumps(details, sort_keys=True),
            utc_now(),
        ),
    )
    con.commit()


def start_run(con: sqlite3.Connection, name: str, details: dict[str, Any] | None = None) -> int:
    cur = con.execute(
        """
        INSERT INTO pipeline_runs(name, status, started_at, details_json)
        VALUES(?, 'running', ?, ?)
        """,
        (name, utc_now(), json.dumps(details or {}, sort_keys=True)),
    )
    con.commit()
    return int(cur.lastrowid)


def finish_run(
    con: sqlite3.Connection, run_id: int, status: str, details: dict[str, Any] | None = None
) -> None:
    con.execute(
        """
        UPDATE pipeline_runs
        SET status = ?, finished_at = ?, details_json = ?
        WHERE id = ?
        """,
        (status, utc_now(), json.dumps(details or {}, sort_keys=True), run_id),
    )
    con.commit()


def recover_interrupted_runs(con: sqlite3.Connection) -> int:
    cur = con.execute(
        """
        UPDATE pipeline_runs
        SET status = 'interrupted', finished_at = ?
        WHERE status = 'running'
        """,
        (utc_now(),),
    )
    con.commit()
    return int(cur.rowcount)
