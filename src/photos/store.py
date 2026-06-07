from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Literal

from .contracts import Page, row_to_dict
from .database import connect, utc_now

DEFAULT_PAGE_SIZE = 200
MAX_PAGE_SIZE = 10_000

_ORDER_COLUMNS = {
    "path": "path",
    "name": "name",
    "size_bytes": "size_bytes",
    "mtime_ns": "mtime_ns",
    "media_type": "media_type",
}


PRODUCT_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS scan_roots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_root TEXT NOT NULL,
    archive_root TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    settings_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(source_root, archive_root)
);

CREATE TABLE IF NOT EXISTS scan_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_root_id INTEGER,
    pipeline_run_id INTEGER,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    folder_count INTEGER NOT NULL DEFAULT 0,
    file_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    details_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS folder_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_root_id INTEGER,
    root TEXT NOT NULL,
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
    last_seen_at TEXT NOT NULL,
    UNIQUE(root, path)
);

CREATE TABLE IF NOT EXISTS duplicate_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_key TEXT NOT NULL UNIQUE,
    candidate_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending_review',
    confidence REAL NOT NULL DEFAULT 0,
    recommended_action TEXT NOT NULL DEFAULT 'review',
    evidence_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS candidate_members (
    candidate_id INTEGER NOT NULL,
    path TEXT NOT NULL,
    member_role TEXT NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY(candidate_id, path)
);

CREATE TABLE IF NOT EXISTS date_audit_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    folder_path TEXT NOT NULL,
    issue_type TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending_review',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS date_audit_items (
    group_id INTEGER NOT NULL,
    path TEXT NOT NULL,
    filename_date TEXT,
    folder_date TEXT,
    filesystem_date TEXT,
    proposed_canonical_date TEXT,
    status TEXT NOT NULL DEFAULT 'pending_review',
    PRIMARY KEY(group_id, path)
);

CREATE TABLE IF NOT EXISTS organize_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy TEXT NOT NULL,
    archive_root TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL,
    summary_json TEXT NOT NULL DEFAULT '{}'
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
    reason_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(plan_id, source_path, destination_path)
);

CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    approval_type TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id INTEGER NOT NULL,
    approved INTEGER NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    approved_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS execution_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id INTEGER NOT NULL,
    transfer_method TEXT NOT NULL DEFAULT 'not_selected',
    estimated_bytes INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'planned',
    started_at TEXT NOT NULL,
    finished_at TEXT,
    summary_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS batch_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL,
    plan_action_id INTEGER NOT NULL,
    source_path TEXT NOT NULL,
    destination_path TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
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
    details_json TEXT NOT NULL DEFAULT '{}'
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

CREATE TABLE IF NOT EXISTS dry_run_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id INTEGER,
    error_count INTEGER NOT NULL,
    execute_allowed INTEGER NOT NULL,
    blocking_reasons_json TEXT NOT NULL,
    summary_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS operation_locks (
    lock_name TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS integrity_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_type TEXT NOT NULL,
    status TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_folder_nodes_root_parent_path
    ON folder_nodes(root, parent_path, path);
CREATE INDEX IF NOT EXISTS idx_duplicate_candidates_status_type
    ON duplicate_candidates(status, candidate_type);
CREATE INDEX IF NOT EXISTS idx_candidate_members_path
    ON candidate_members(path);
CREATE INDEX IF NOT EXISTS idx_date_audit_groups_status
    ON date_audit_groups(status, issue_type, folder_path);
CREATE INDEX IF NOT EXISTS idx_plan_actions_plan_status
    ON plan_actions(plan_id, status);
CREATE INDEX IF NOT EXISTS idx_plan_actions_destination_ci
    ON plan_actions(plan_id, destination_path COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_batch_items_batch_status
    ON batch_items(batch_id, status);
CREATE INDEX IF NOT EXISTS idx_batch_items_plan_action
    ON batch_items(plan_action_id);
CREATE INDEX IF NOT EXISTS idx_batch_manifests_batch
    ON batch_manifests(batch_id, id);
"""


def init_product_tables(con: sqlite3.Connection) -> None:
    """Install product tables without replacing the existing v1 tables.

    This is intentionally additive. It lets GPT-5.5 continue the backend work
    without forcing a risky one-shot migration from ``legacy2``.
    """

    con.executescript(PRODUCT_SCHEMA_SQL)
    con.execute(
        "INSERT OR REPLACE INTO app_state(key, value) VALUES('product_schema', ?)",
        ("commercial-safety-v1",),
    )
    con.commit()


def _clamp_page(page: int, page_size: int) -> tuple[int, int, int]:
    page = max(1, int(page))
    page_size = min(MAX_PAGE_SIZE, max(1, int(page_size)))
    offset = (page - 1) * page_size
    return page, page_size, offset


def _json_dumps(data: Any) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=False)


class PhotoStore:
    """Small SQLite store facade for the formal service boundary."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self.db_path = db_path
        self.con = connect(db_path)
        init_product_tables(self.con)

    def close(self) -> None:
        self.con.close()

    def __enter__(self) -> "PhotoStore":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def app_state(self, key: str, default: str = "") -> str:
        row = self.con.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row else default

    def set_app_state(self, key: str, value: str) -> None:
        self.con.execute(
            "INSERT OR REPLACE INTO app_state(key, value) VALUES(?, ?)",
            (key, value),
        )
        self.con.commit()

    def health(self) -> dict[str, Any]:
        media_count = self.con.execute(
            "SELECT COUNT(*) AS count FROM media_files WHERE exists_on_disk = 1"
        ).fetchone()["count"]
        table_rows = self.con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall()
        return {
            "ok": True,
            "db_path": str(self.db_path),
            "product_schema": self.app_state("product_schema"),
            "media_count": int(media_count),
            "tables": [str(row["name"]) for row in table_rows],
        }

    def get_or_create_scan_root(self, root: str | Path, archive_root: str | Path = "") -> int:
        root_text = str(Path(root).expanduser().resolve())
        archive_text = str(archive_root)
        now = utc_now()
        self.con.execute("UPDATE scan_roots SET active = 0")
        cur = self.con.execute(
            """
            INSERT INTO scan_roots(source_root, archive_root, created_at, active, settings_json)
            VALUES(?, ?, ?, 1, '{}')
            ON CONFLICT(source_root, archive_root) DO UPDATE SET active = 1
            """,
            (root_text, archive_text, now),
        )
        row = self.con.execute(
            "SELECT id FROM scan_roots WHERE source_root = ? AND archive_root = ?",
            (root_text, archive_text),
        ).fetchone()
        self.con.commit()
        return int(row["id"] if row else cur.lastrowid)

    def record_scan_run(
        self,
        *,
        scan_root_id: int | None,
        status: str,
        file_count: int,
        folder_count: int,
        error_count: int = 0,
        details: dict[str, Any] | None = None,
        pipeline_run_id: int | None = None,
    ) -> int:
        now = utc_now()
        cur = self.con.execute(
            """
            INSERT INTO scan_runs(
                scan_root_id, pipeline_run_id, status, started_at, finished_at,
                folder_count, file_count, error_count, details_json
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                scan_root_id,
                pipeline_run_id,
                status,
                now,
                now,
                folder_count,
                file_count,
                error_count,
                _json_dumps(details or {}),
            ),
        )
        self.con.commit()
        return int(cur.lastrowid)

    def sync_folder_nodes(self, root: str | Path) -> dict[str, Any]:
        root_path = Path(root).expanduser().resolve()
        root_text = str(root_path)
        scan_root_id = self.get_or_create_scan_root(root_path)
        now = utc_now()
        self.con.execute("DELETE FROM folder_nodes WHERE root = ?", (root_text,))

        direct: dict[str, dict[str, Any]] = {}
        for row in self.con.execute(
            """
            SELECT path, rel_path, suffix, size_bytes, mtime_ns
            FROM media_files
            WHERE root = ? AND exists_on_disk = 1
            ORDER BY path
            """,
            (root_text,),
        ):
            rel_parent = Path(str(row["rel_path"])).parent.as_posix()
            folder = "" if rel_parent == "." else rel_parent
            node = direct.setdefault(
                folder,
                {"count": 0, "bytes": 0, "extensions": {}, "min_mtime": None, "max_mtime": None},
            )
            node["count"] += 1
            node["bytes"] += int(row["size_bytes"])
            suffix = str(row["suffix"] or "").lower()
            node["extensions"][suffix] = int(node["extensions"].get(suffix, 0)) + 1
            mtime = int(row["mtime_ns"])
            node["min_mtime"] = mtime if node["min_mtime"] is None else min(node["min_mtime"], mtime)
            node["max_mtime"] = mtime if node["max_mtime"] is None else max(node["max_mtime"], mtime)

        all_folders = set(direct)
        for folder in list(direct):
            current = Path(folder)
            while str(current) not in {".", ""}:
                parent = current.parent.as_posix()
                all_folders.add("" if parent == "." else parent)
                current = current.parent
        all_folders.add("")

        subtree: dict[str, dict[str, int]] = {
            folder: {
                "count": int(direct.get(folder, {}).get("count", 0)),
                "bytes": int(direct.get(folder, {}).get("bytes", 0)),
            }
            for folder in all_folders
        }
        folders_by_depth = sorted(
            all_folders,
            key=lambda folder: len(Path(folder).parts) if folder else 0,
            reverse=True,
        )
        for folder in folders_by_depth:
            if not folder:
                continue
            parent_text = Path(folder).parent.as_posix()
            parent = "" if parent_text == "." else parent_text
            subtree[parent]["count"] += subtree[folder]["count"]
            subtree[parent]["bytes"] += subtree[folder]["bytes"]

        for folder in sorted(all_folders):
            parent = None
            if folder:
                parent_text = Path(folder).parent.as_posix()
                parent = "" if parent_text == "." else parent_text
            stats = direct.get(folder, {"count": 0, "bytes": 0, "extensions": {}})
            date_range = {
                "min_mtime_ns": stats.get("min_mtime"),
                "max_mtime_ns": stats.get("max_mtime"),
            }
            self.con.execute(
                """
                INSERT INTO folder_nodes(
                    scan_root_id, root, path, parent_path, depth, direct_file_count,
                    subtree_file_count, direct_bytes, subtree_bytes, extension_counts_json,
                    date_ranges_json, attention_flags_json, last_seen_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', ?)
                """,
                (
                    scan_root_id,
                    root_text,
                    folder,
                    parent,
                    0 if not folder else len(Path(folder).parts),
                    int(stats.get("count", 0)),
                    subtree[folder]["count"],
                    int(stats.get("bytes", 0)),
                    subtree[folder]["bytes"],
                    _json_dumps(stats.get("extensions", {})),
                    _json_dumps(date_range),
                    now,
                ),
            )
        self.con.commit()
        return {"scan_root_id": scan_root_id, "folder_count": len(all_folders)}

    def list_folder_nodes(
        self,
        root: str | Path | None = None,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> dict[str, Any]:
        page, page_size, offset = _clamp_page(page, page_size)
        params: list[Any] = []
        where = ""
        if root is not None:
            where = "WHERE root = ?"
            params.append(str(Path(root).expanduser().resolve()))
        total = int(
            self.con.execute(
                f"SELECT COUNT(*) AS count FROM folder_nodes {where}",
                params,
            ).fetchone()["count"]
        )
        rows = self.con.execute(
            f"""
            SELECT * FROM folder_nodes
            {where}
            ORDER BY depth, path
            LIMIT ? OFFSET ?
            """,
            [*params, page_size, offset],
        ).fetchall()
        return Page(
            page=page,
            page_size=page_size,
            total=total,
            rows=[row_to_dict(row) for row in rows],
        ).to_dict()

    def folder_nodes(self, root: str | Path | None = None) -> list[dict[str, Any]]:
        """Return a bounded first page for legacy callers expecting a row list."""

        return self.list_folder_nodes(root)["rows"]

    def list_media(
        self,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        media_type: str | None = None,
        text: str | None = None,
        order_by: str = "path",
        direction: Literal["asc", "desc"] = "asc",
    ) -> dict[str, Any]:
        page, page_size, offset = _clamp_page(page, page_size)
        filters = ["exists_on_disk = 1"]
        params: list[Any] = []
        if media_type:
            filters.append("media_type = ?")
            params.append(media_type)
        if text:
            filters.append("(path LIKE ? OR name LIKE ?)")
            like = f"%{text}%"
            params.extend([like, like])
        where = " AND ".join(filters)
        column = _ORDER_COLUMNS.get(order_by, "path")
        sort_dir = "DESC" if direction.lower() == "desc" else "ASC"
        total = int(
            self.con.execute(
                f"SELECT COUNT(*) AS count FROM media_files WHERE {where}", params
            ).fetchone()["count"]
        )
        rows = self.con.execute(
            f"""
            SELECT id, root, path, rel_path, parent_key, name, stem_key, suffix,
                   media_type, size_bytes, mtime_ns, sha256, indexed_at,
                   exists_on_disk, missing_at, last_seen_at
            FROM media_files
            WHERE {where}
            ORDER BY {column} {sort_dir}, path ASC
            LIMIT ? OFFSET ?
            """,
            [*params, page_size, offset],
        ).fetchall()
        return Page(
            page=page,
            page_size=page_size,
            total=total,
            rows=[row_to_dict(row) for row in rows],
        ).to_dict()

    def folder_summary(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.con.execute(
            """
            SELECT parent_key AS folder, COUNT(*) AS file_count, COALESCE(SUM(size_bytes), 0) AS bytes
            FROM media_files
            WHERE exists_on_disk = 1
            GROUP BY parent_key
            ORDER BY bytes DESC, folder ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [row_to_dict(row) for row in rows]
