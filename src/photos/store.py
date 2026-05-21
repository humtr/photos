from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable

from .utils import json_dumps

DEFAULT_PAGE_SIZE = 10_000


def now_ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS scan_roots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_root TEXT NOT NULL,
            archive_root TEXT NOT NULL,
            created_at TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            settings_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS scan_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_root_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            folder_count INTEGER NOT NULL DEFAULT 0,
            file_count INTEGER NOT NULL DEFAULT 0,
            error_count INTEGER NOT NULL DEFAULT 0,
            details_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS scan_errors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_run_id INTEGER NOT NULL,
            path TEXT NOT NULL,
            phase TEXT NOT NULL,
            error TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS folder_nodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_root_id INTEGER NOT NULL,
            path TEXT NOT NULL,
            parent_path TEXT,
            depth INTEGER NOT NULL DEFAULT 0,
            direct_file_count INTEGER NOT NULL DEFAULT 0,
            subtree_file_count INTEGER NOT NULL DEFAULT 0,
            direct_bytes INTEGER NOT NULL DEFAULT 0,
            subtree_bytes INTEGER NOT NULL DEFAULT 0,
            extension_counts_json TEXT NOT NULL DEFAULT '{}',
            date_ranges_json TEXT NOT NULL DEFAULT '{}',
            attention_flags_json TEXT NOT NULL DEFAULT '[]',
            last_seen_scan_id INTEGER,
            UNIQUE(scan_root_id, path)
        );
        CREATE TABLE IF NOT EXISTS media_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_root_id INTEGER NOT NULL,
            path TEXT NOT NULL,
            folder_path TEXT NOT NULL,
            name TEXT NOT NULL,
            stem TEXT NOT NULL DEFAULT '',
            suffix TEXT NOT NULL DEFAULT '',
            media_type TEXT NOT NULL DEFAULT 'photo',
            size_bytes INTEGER NOT NULL,
            ctime_ns INTEGER NOT NULL DEFAULT 0,
            mtime_ns INTEGER NOT NULL,
            exif_datetime TEXT,
            gps_lat REAL,
            gps_lon REAL,
            existence_state TEXT NOT NULL DEFAULT 'seen',
            last_seen_scan_id INTEGER,
            UNIQUE(scan_root_id, path)
        );
        CREATE TABLE IF NOT EXISTS folder_places (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_root_id INTEGER NOT NULL,
            folder_path TEXT NOT NULL,
            dominant_place TEXT,
            sample_count INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            UNIQUE(scan_root_id, folder_path)
        );
        CREATE TABLE IF NOT EXISTS place_cache (
            gps_key TEXT PRIMARY KEY,
            place_label TEXT NOT NULL,
            source TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS duplicate_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_root_id INTEGER NOT NULL,
            candidate_key TEXT NOT NULL,
            candidate_type TEXT NOT NULL,
            left_path TEXT NOT NULL,
            right_path TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS metadata_audits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_root_id INTEGER NOT NULL,
            folder_path TEXT NOT NULL,
            issue_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS llm_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            review_type TEXT NOT NULL,
            path TEXT NOT NULL,
            status TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            summary_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS llm_review_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            review_id INTEGER NOT NULL,
            target_type TEXT NOT NULL,
            target_path TEXT NOT NULL,
            proposal_type TEXT NOT NULL,
            proposal_json TEXT NOT NULL,
            confidence REAL NOT NULL,
            status TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS organize_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_root_id INTEGER NOT NULL,
            strategy TEXT NOT NULL,
            archive_root TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            summary_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS plan_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER NOT NULL,
            source_path TEXT NOT NULL,
            destination_path TEXT NOT NULL,
            action_type TEXT NOT NULL,
            expected_size INTEGER NOT NULL,
            expected_mtime_ns INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            reason_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS approvals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            approval_type TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_id INTEGER NOT NULL,
            approved INTEGER NOT NULL,
            note TEXT NOT NULL,
            approved_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS execution_batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER NOT NULL,
            transfer_method TEXT NOT NULL,
            estimated_bytes INTEGER NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            summary_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS batch_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id INTEGER NOT NULL,
            plan_action_id INTEGER NOT NULL,
            source_path TEXT NOT NULL,
            destination_path TEXT NOT NULL,
            status TEXT NOT NULL,
            error_code TEXT,
            error_message TEXT
        );
        CREATE TABLE IF NOT EXISTS transfer_verifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_item_id INTEGER NOT NULL,
            destination_size INTEGER,
            destination_mtime_ns INTEGER,
            verification_status TEXT NOT NULL,
            verified_at TEXT NOT NULL,
            details_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS batch_manifests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id INTEGER NOT NULL,
            manifest_path TEXT NOT NULL,
            manifest_sha256 TEXT NOT NULL,
            item_count INTEGER NOT NULL,
            total_bytes INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_type TEXT NOT NULL,
            path TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            created_at TEXT NOT NULL,
            summary_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS app_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS dry_run_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            error_count INTEGER NOT NULL,
            execute_allowed INTEGER NOT NULL,
            blocking_reasons_json TEXT NOT NULL,
            summary_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    conn.commit()
    _apply_goal_schema_additions(conn)
    _apply_goal_indexes(conn)


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row["name"]) for row in rows}


def _ensure_columns(conn: sqlite3.Connection, table_name: str, column_defs: list[str]) -> None:
    existing = _table_columns(conn, table_name)
    for coldef in column_defs:
        colname = coldef.split()[0]
        if colname not in existing:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {coldef}")


def _seed_status_values(conn: sqlite3.Connection) -> None:
    required_values = {
        "existence_state": ["seen", "not_seen_this_scan", "confirmed_missing"],
        "duplicate_candidates.group_type": [
            "probable_duplicate",
            "transferred_derivative",
            "same_name_collision",
            "folder_pair_burst",
            "requires_review",
        ],
        "plan_actions.action_type": [
            "move",
            "rename_move",
            "keep_separate",
            "hold",
            "metadata_override",
            "metadata_write_candidate",
        ],
        "transfer_method": ["same_volume_move", "copy_verify_cleanup"],
        "batch_status": ["planned", "dry_run_passed", "running", "verified", "committed", "failed", "held", "cancelled"],
        "item_status": ["pending", "moved", "copied", "verified", "source_changed", "collision", "failed", "held"],
        "llm_review_items.status": ["pending_approval", "approved", "rejected", "superseded"],
    }
    for status_key, values in required_values.items():
        for value in values:
            conn.execute(
                "INSERT OR IGNORE INTO required_status_values(status_key, status_value) VALUES(?,?)",
                (status_key, value),
            )


def _apply_goal_schema_additions(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS folder_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            folder_path TEXT NOT NULL,
            sample_type TEXT NOT NULL,
            path TEXT NOT NULL,
            name TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            dates_json TEXT NOT NULL,
            gps_place_id INTEGER
        );
        CREATE TABLE IF NOT EXISTS places (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lat_bucket TEXT NOT NULL,
            lon_bucket TEXT NOT NULL,
            label TEXT NOT NULL,
            provider TEXT NOT NULL,
            confidence REAL NOT NULL,
            raw_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS folder_place_summaries (
            folder_path TEXT PRIMARY KEY,
            dominant_places_json TEXT NOT NULL,
            gps_file_count INTEGER NOT NULL,
            non_gps_file_count INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS name_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            normalized_name TEXT NOT NULL,
            member_count INTEGER NOT NULL,
            size_variants INTEGER NOT NULL,
            date_range_json TEXT NOT NULL,
            status TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS candidate_members (
            candidate_id INTEGER NOT NULL,
            path TEXT NOT NULL,
            member_role TEXT NOT NULL,
            evidence_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS folder_pair_relations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            folder_a TEXT NOT NULL,
            folder_b TEXT NOT NULL,
            matched_name_count INTEGER NOT NULL,
            same_size_count INTEGER NOT NULL,
            same_exif_count INTEGER NOT NULL,
            derivative_count INTEGER NOT NULL,
            collision_count INTEGER NOT NULL,
            dominant_place TEXT,
            date_range_json TEXT NOT NULL,
            confidence REAL NOT NULL,
            reason_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS date_audit_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            folder_path TEXT NOT NULL,
            issue_type TEXT NOT NULL,
            confidence REAL NOT NULL,
            evidence_json TEXT NOT NULL,
            status TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS date_audit_items (
            group_id INTEGER NOT NULL,
            path TEXT NOT NULL,
            filename_date TEXT,
            folder_date TEXT,
            exif_date TEXT,
            filesystem_date TEXT,
            proposed_canonical_date TEXT,
            status TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS metadata_edit_suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_type TEXT NOT NULL,
            target_path TEXT NOT NULL,
            proposed_value TEXT NOT NULL,
            source TEXT NOT NULL,
            status TEXT NOT NULL,
            reason_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS llm_packets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            packet_type TEXT NOT NULL,
            path TEXT NOT NULL,
            root_folder TEXT NOT NULL,
            created_at TEXT NOT NULL,
            row_count INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            settings_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS required_status_values (
            status_key TEXT NOT NULL,
            status_value TEXT NOT NULL,
            PRIMARY KEY (status_key, status_value)
        );
        """
    )
    _ensure_columns(
        conn,
        "duplicate_candidates",
        [
            "group_type TEXT",
            "confidence REAL",
            "recommended_action TEXT",
            "reason_json TEXT",
            "created_at TEXT",
        ],
    )
    _seed_status_values(conn)
    conn.execute(
        "INSERT OR REPLACE INTO app_state(key, value) VALUES('schema_version', '2')"
    )
    conn.commit()


def _apply_goal_indexes(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_media_scan_state_path
            ON media_files(scan_root_id, existence_state, path);
        CREATE INDEX IF NOT EXISTS idx_media_scan_suffix_size
            ON media_files(scan_root_id, suffix, size_bytes);
        CREATE INDEX IF NOT EXISTS idx_media_scan_name
            ON media_files(scan_root_id, name);
        CREATE INDEX IF NOT EXISTS idx_media_scan_folder_name
            ON media_files(scan_root_id, folder_path, name);
        CREATE INDEX IF NOT EXISTS idx_media_scan_folder_size
            ON media_files(scan_root_id, folder_path, size_bytes);

        CREATE INDEX IF NOT EXISTS idx_folder_nodes_scan_parent_path
            ON folder_nodes(scan_root_id, parent_path, path);
        CREATE INDEX IF NOT EXISTS idx_folder_nodes_scan_last_seen
            ON folder_nodes(scan_root_id, last_seen_scan_id, path);

        CREATE INDEX IF NOT EXISTS idx_duplicate_candidates_scan_status_type
            ON duplicate_candidates(scan_root_id, status, candidate_type);
        CREATE INDEX IF NOT EXISTS idx_duplicate_candidates_scan_group_type
            ON duplicate_candidates(scan_root_id, group_type, status);
        CREATE INDEX IF NOT EXISTS idx_candidate_members_candidate_path
            ON candidate_members(candidate_id, path);
        CREATE INDEX IF NOT EXISTS idx_folder_pair_relations_folders
            ON folder_pair_relations(folder_a, folder_b);

        CREATE INDEX IF NOT EXISTS idx_metadata_audits_scan_issue_folder
            ON metadata_audits(scan_root_id, issue_type, folder_path);
        CREATE INDEX IF NOT EXISTS idx_date_audit_groups_status
            ON date_audit_groups(status, issue_type, folder_path);
        CREATE INDEX IF NOT EXISTS idx_date_audit_items_group_status
            ON date_audit_items(group_id, status);
        CREATE INDEX IF NOT EXISTS idx_metadata_edit_suggestions_status
            ON metadata_edit_suggestions(status, target_type, target_path);
        """
    )
    conn.commit()


def get_or_create_scan_root(conn: sqlite3.Connection, source_root: str, archive_root: str, created_at: str) -> int:
    row = conn.execute(
        "SELECT id FROM scan_roots WHERE source_root=? AND archive_root=? ORDER BY id DESC LIMIT 1",
        (source_root, archive_root),
    ).fetchone()
    if row:
        conn.execute("UPDATE scan_roots SET active=0")
        conn.execute("UPDATE scan_roots SET active=1 WHERE id=?", (int(row["id"]),))
        conn.commit()
        return int(row["id"])
    cur = conn.execute(
        "INSERT INTO scan_roots(source_root, archive_root, created_at, active, settings_json) VALUES(?,?,?,1,'{}')",
        (source_root, archive_root, created_at),
    )
    conn.commit()
    return int(cur.lastrowid)


def latest_scan_root(conn: sqlite3.Connection) -> sqlite3.Row | None:
    row = conn.execute("SELECT * FROM scan_roots WHERE active=1 ORDER BY id DESC LIMIT 1").fetchone()
    if row:
        return row
    return conn.execute("SELECT * FROM scan_roots ORDER BY id DESC LIMIT 1").fetchone()


class Store:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.conn = connect(db_path)

    def close(self) -> None:
        self.conn.close()

    def init_schema(self) -> None:
        init_db(self.conn)

    def add_scan_root(self, source_root: str, archive_root: str) -> int:
        return get_or_create_scan_root(self.conn, source_root, archive_root, now_ts())

    def add_media_file(self, scan_root_id: int, path: Path) -> None:
        st = path.stat()
        self.conn.execute(
            """
            INSERT INTO media_files(
                scan_root_id,path,folder_path,name,stem,suffix,media_type,size_bytes,ctime_ns,mtime_ns,exif_datetime,gps_lat,gps_lon,existence_state,last_seen_scan_id
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)
            ON CONFLICT(scan_root_id,path) DO UPDATE SET
                folder_path=excluded.folder_path,
                name=excluded.name,
                stem=excluded.stem,
                suffix=excluded.suffix,
                media_type=excluded.media_type,
                size_bytes=excluded.size_bytes,
                ctime_ns=excluded.ctime_ns,
                mtime_ns=excluded.mtime_ns,
                exif_datetime=excluded.exif_datetime,
                gps_lat=excluded.gps_lat,
                gps_lon=excluded.gps_lon,
                existence_state=excluded.existence_state
            """,
            (
                scan_root_id,
                str(path),
                str(path.parent),
                path.name,
                path.stem,
                path.suffix.lower(),
                "photo",
                int(st.st_size),
                int(st.st_ctime_ns),
                int(st.st_mtime_ns),
                None,
                None,
                None,
                "seen",
            ),
        )
        self.conn.commit()

    def get_scan_root(self, scan_root_id: int) -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM scan_roots WHERE id=?", (scan_root_id,)).fetchone()
        if row is None:
            raise ValueError(f"scan_root not found: {scan_root_id}")
        return row

    def list_media(self, scan_root_id: int) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                "SELECT * FROM media_files WHERE scan_root_id=? AND existence_state='seen' ORDER BY path",
                (scan_root_id,),
            )
        )

    def create_plan(self, scan_root_id: int, strategy: str, archive_root: str, summary: dict) -> int:
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO organize_plans(scan_root_id, strategy, archive_root, status, created_at, summary_json)
            VALUES(?,?,?,?,?,?)
            """,
            (scan_root_id, strategy, archive_root, "planned", now_ts(), json_dumps(summary)),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def insert_plan_actions(self, rows_or_plan_id: int | Iterable[tuple], maybe_rows: Iterable[tuple] | None = None) -> None:
        rows: Iterable[tuple]
        if isinstance(rows_or_plan_id, int):
            rows = maybe_rows or []
        else:
            rows = rows_or_plan_id
        self.conn.executemany(
            """
            INSERT INTO plan_actions(plan_id, source_path, destination_path, action_type, expected_size, expected_mtime_ns, status, reason_json)
            VALUES(?,?,?,?,?,?,?,?)
            """,
            rows,
        )
        self.conn.commit()

    def get_plan(self, plan_id: int) -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM organize_plans WHERE id=?", (plan_id,)).fetchone()
        if row is None:
            raise ValueError(f"plan not found: {plan_id}")
        return row

    def latest_plan_id(self) -> int:
        row = self.conn.execute("SELECT id FROM organize_plans ORDER BY id DESC LIMIT 1").fetchone()
        if row is None:
            raise ValueError("no plans found")
        return int(row["id"])

    def list_plan_actions(self, plan_id: int) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM plan_actions WHERE plan_id=? ORDER BY id", (plan_id,)))

    def add_approval(self, approval_type: str, target_type: str, target_id: int, approved: bool, note: str) -> int:
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO approvals(approval_type, target_type, target_id, approved, note, approved_at)
            VALUES(?,?,?,?,?,?)
            """,
            (approval_type, target_type, target_id, 1 if approved else 0, note, now_ts()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def is_approved(self, approval_type: str, target_type: str, target_id: int) -> bool:
        row = self.conn.execute(
            """
            SELECT approved FROM approvals
            WHERE approval_type=? AND target_type=? AND target_id=?
            ORDER BY id DESC LIMIT 1
            """,
            (approval_type, target_type, target_id),
        ).fetchone()
        return bool(row and int(row["approved"]) == 1)

    def create_batch(self, plan_id: int, transfer_method: str, estimated_bytes: int, status: str, summary: dict) -> int:
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO execution_batches(plan_id, transfer_method, estimated_bytes, status, started_at, summary_json)
            VALUES(?,?,?,?,?,?)
            """,
            (plan_id, transfer_method, estimated_bytes, status, now_ts(), json_dumps(summary)),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def finish_batch(self, batch_id: int, status: str, summary: dict) -> None:
        self.conn.execute(
            "UPDATE execution_batches SET status=?, finished_at=?, summary_json=? WHERE id=?",
            (status, now_ts(), json_dumps(summary), batch_id),
        )
        self.conn.commit()

    def insert_batch_items(self, rows: Iterable[tuple]) -> None:
        self.conn.executemany(
            """
            INSERT INTO batch_items(batch_id, plan_action_id, source_path, destination_path, status, error_code, error_message)
            VALUES(?,?,?,?,?,?,?)
            """,
            rows,
        )
        self.conn.commit()

    def update_batch_item(self, batch_item_id: int, status: str, error_code: str | None = None, error_message: str | None = None) -> None:
        self.conn.execute(
            "UPDATE batch_items SET status=?, error_code=?, error_message=? WHERE id=?",
            (status, error_code, error_message, batch_item_id),
        )
        self.conn.commit()

    def list_batch_items(self, batch_id: int) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM batch_items WHERE batch_id=? ORDER BY id", (batch_id,)))

    def add_transfer_verification(
        self, batch_item_id: int, destination_size: int, destination_mtime_ns: int, verification_status: str, details: dict
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO transfer_verifications(batch_item_id, destination_size, destination_mtime_ns, verification_status, verified_at, details_json)
            VALUES(?,?,?,?,?,?)
            """,
            (batch_item_id, destination_size, destination_mtime_ns, verification_status, now_ts(), json_dumps(details)),
        )
        self.conn.commit()

    def add_manifest(self, batch_id: int, manifest_path: str, manifest_sha256: str, item_count: int, total_bytes: int) -> None:
        self.conn.execute(
            """
            INSERT INTO batch_manifests(batch_id, manifest_path, manifest_sha256, item_count, total_bytes, created_at)
            VALUES(?,?,?,?,?,?)
            """,
            (batch_id, manifest_path, manifest_sha256, item_count, total_bytes, now_ts()),
        )
        self.conn.commit()

    def add_report(self, report_type: str, path: str, sha256: str, summary: dict) -> None:
        self.conn.execute(
            "INSERT INTO reports(report_type, path, sha256, created_at, summary_json) VALUES(?,?,?,?,?)",
            (report_type, path, sha256, now_ts(), json_dumps(summary)),
        )
        self.conn.commit()


class PhotoStore:
    """GUI shell adapter over the shared SQLite file."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.store = Store(self.db_path)
        self.conn = self.store.conn

    def close(self) -> None:
        self.store.close()

    def init_schema(self) -> None:
        self.store.init_schema()

    def set_app_state(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO app_state(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self.conn.commit()

    def get_app_state(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT value FROM app_state WHERE key=?", (key,)).fetchone()
        if row is None:
            return default
        return str(row["value"])

    def fetch_folder_nodes(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT path, parent_path, depth,
                   COALESCE(subtree_file_count, 0) AS subtree_file_count,
                   COALESCE(subtree_bytes, 0) AS subtree_bytes
            FROM folder_nodes
            ORDER BY depth, path
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def count_media_rows(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) AS c FROM media_files").fetchone()
        return int(row["c"])

    def fetch_media_page(self, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE) -> tuple[list[dict[str, Any]], int]:
        if page < 1:
            raise ValueError("page must be >= 1")
        if page_size < 1:
            raise ValueError("page_size must be >= 1")
        total = self.count_media_rows()
        offset = (page - 1) * page_size
        rows = self.conn.execute(
            """
            SELECT path, folder_path, name, size_bytes, mtime_ns
            FROM media_files
            ORDER BY folder_path, name, path
            LIMIT ? OFFSET ?
            """,
            (page_size, offset),
        ).fetchall()
        return [dict(r) for r in rows], total
