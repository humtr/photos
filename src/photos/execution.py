from __future__ import annotations

import json
import os
import shutil
import sqlite3
import uuid
from contextlib import contextmanager
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from .database import utc_now
from .hashing import sha256_file
from .planning import iter_archive_plans

MAX_SAFE_WINDOWS_PATH = 240
MIN_DESTINATION_FREE_MARGIN_BYTES = 10 * 1024 * 1024
DATABASE_BATCH_SIZE = 500
MUTATION_COMMIT_INTERVAL = 50
PROGRESS_FRAME_INTERVAL = 1000


def _json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=False)


def _loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _emit_progress(progress_callback: Callable[[dict[str, Any]], None] | None, payload: dict[str, Any]) -> None:
    if progress_callback is None:
        return
    try:
        progress_callback(payload)
    except Exception:
        pass


def _should_emit_progress(processed: int, total: int) -> bool:
    return processed == 1 or processed == total or processed % PROGRESS_FRAME_INTERVAL == 0


def _iter_id_keyset(
    con: sqlite3.Connection,
    sql: str,
    params: tuple[Any, ...],
    *,
    descending: bool = False,
    batch_size: int = DATABASE_BATCH_SIZE,
) -> Iterator[list[sqlite3.Row]]:
    last_id = 2**63 - 1 if descending else 0
    while True:
        rows = con.execute(sql, (*params, last_id, batch_size)).fetchall()
        if not rows:
            return
        yield rows
        last_id = int(rows[-1]["id"])


def _norm_case(path: str | Path) -> str:
    return os.path.normcase(str(path)).replace("\\", "/").lower()


def _is_relative_archive_path(path: str) -> bool:
    candidate = Path(path)
    return not candidate.is_absolute() and ".." not in candidate.parts


def _safe_resolve(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _safe_join(root: str | Path, child: str) -> Path:
    root_path = _safe_resolve(root)
    destination = (root_path / child).resolve()
    try:
        destination.relative_to(root_path)
    except ValueError as exc:
        raise ValueError(f"destination escapes archive root: {destination}") from exc
    return destination


def _relative_to_or_empty(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def _paths_overlap(parent: Path, child: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _is_windows_reparse_point(path: Path) -> bool:
    """Return True for Windows junctions/reparse points when attributes exist."""

    try:
        stat = path.stat()
    except OSError:
        return False
    file_attributes = getattr(stat, "st_file_attributes", 0)
    # FILE_ATTRIBUTE_REPARSE_POINT = 0x400.  On POSIX this attribute is absent.
    return bool(file_attributes & 0x400)


@contextmanager
def _operation_lock(con: sqlite3.Connection, lock_name: str, *, details: dict[str, Any] | None = None):
    """SQLite-backed single-writer lock for dangerous operations.

    This prevents a GUI button double-click, a second CLI process, or a retrying
    automation from running two executions/rollbacks against the same DB.
    """

    owner = f"{os.getpid()}-{uuid.uuid4().hex}"
    try:
        con.execute(
            """
            INSERT INTO operation_locks(lock_name, owner, acquired_at, details_json)
            VALUES(?, ?, ?, ?)
            """,
            (lock_name, owner, utc_now(), _json(details or {})),
        )
        con.commit()
    except sqlite3.IntegrityError as exc:
        row = con.execute(
            "SELECT owner, acquired_at, details_json FROM operation_locks WHERE lock_name = ?",
            (lock_name,),
        ).fetchone()
        locked_by = dict(row) if row else {"lock_name": lock_name}
        raise RuntimeError(f"operation already running: {locked_by}") from exc
    try:
        yield owner
    finally:
        con.execute(
            "DELETE FROM operation_locks WHERE lock_name = ? AND owner = ?",
            (lock_name, owner),
        )
        con.commit()


def _database_path(con: sqlite3.Connection) -> Path | None:
    row = con.execute("PRAGMA database_list").fetchone()
    if row is None or not row["file"]:
        return None
    return Path(row["file"]).expanduser().resolve()


def _backup_database(con: sqlite3.Connection, *, archive_root: Path, label: str) -> dict[str, Any]:
    db_path = _database_path(con)
    if db_path is None or not db_path.exists():
        return {"created": False, "reason": "memory_database_or_missing_db_file"}
    backup_dir = archive_root / ".photos-manifests" / "db-backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{label}-{utc_now().replace(':', '').replace('+', 'Z')}.sqlite"
    con.commit()
    dest = sqlite3.connect(str(backup_path))
    try:
        con.backup(dest)
    finally:
        dest.close()
    digest = sha256_file(backup_path)
    return {"created": True, "path": str(backup_path), "sha256": digest}


def run_integrity_check(con: sqlite3.Connection) -> dict[str, Any]:
    quick_rows = [row[0] for row in con.execute("PRAGMA quick_check").fetchall()]
    fk_rows = [dict(row) for row in con.execute("PRAGMA foreign_key_check").fetchall()]
    counts = {}
    for table in [
        "media_files",
        "plan_actions",
        "execution_batches",
        "batch_items",
        "transfer_verifications",
        "batch_manifests",
        "dry_run_reports",
    ]:
        counts[table] = int(con.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"])
    status = "ok" if quick_rows == ["ok"] and not fk_rows else "attention_required"
    report = {
        "status": status,
        "quick_check": quick_rows,
        "foreign_key_check": fk_rows,
        "counts": counts,
    }
    con.execute(
        """
        INSERT INTO integrity_reports(report_type, status, details_json, created_at)
        VALUES('sqlite_quick_check', ?, ?, ?)
        """,
        (status, _json(report), utc_now()),
    )
    con.commit()
    return report


def create_archive_plan(
    con: sqlite3.Connection,
    *,
    archive_root: str | Path,
    strategy: str = "date_archive_v1",
    event_threshold: int = 10,
) -> dict[str, Any]:
    """Create an approval-gated archive plan from the current media inventory.

    The destination path is materialized into ``plan_actions`` and is safe-joined
    under ``archive_root``.  This function does not move files.
    """

    archive_root_path = _safe_resolve(archive_root)
    logical_plans = iter_archive_plans(
        con,
        archive_root="archive",
        event_threshold=event_threshold,
    )
    cur = con.execute(
        """
        INSERT INTO organize_plans(strategy, archive_root, status, created_at, summary_json)
        VALUES(?, ?, 'draft', ?, ?)
        """,
        (
            strategy,
            str(archive_root_path),
            utc_now(),
            _json({"source": "planning_records", "event_threshold": event_threshold}),
        ),
    )
    plan_id = int(cur.lastrowid)
    action_count = 0
    total_bytes = 0
    for plan in logical_plans:
        source_path = str(plan["source_path"])
        planned_path = str(plan["planned_path"])
        if not planned_path.startswith("archive/") or not _is_relative_archive_path(planned_path):
            raise ValueError(f"unsafe planned relative path: {planned_path}")
        archive_rel_path = planned_path.removeprefix("archive/")
        destination = _safe_join(archive_root_path, archive_rel_path)
        row = con.execute(
            """
            SELECT root, rel_path, parent_key, name, stem_key, suffix, media_type,
                   size_bytes, mtime_ns, sha256
            FROM media_files
            WHERE path = ? AND exists_on_disk = 1
            """,
            (source_path,),
        ).fetchone()
        if row is None:
            continue
        expected_size = int(row["size_bytes"])
        reason = {
            "logical_planned_path": planned_path,
            "archive_rel_path": archive_rel_path,
            "source_root": row["root"],
            "source_rel_path": row["rel_path"],
            "source_parent_key": row["parent_key"],
            "source_name": row["name"],
            "source_stem_key": row["stem_key"],
            "source_suffix": row["suffix"],
            "source_media_type": row["media_type"],
            "source_sha256": row["sha256"],
        }
        con.execute(
            """
            INSERT INTO plan_actions(
                plan_id, source_path, destination_path, action_type,
                expected_size, expected_mtime_ns, status, reason_json
            )
            VALUES(?, ?, ?, 'move_after_approval', ?, ?, 'pending', ?)
            """,
            (
                plan_id,
                source_path,
                str(destination),
                expected_size,
                int(row["mtime_ns"]),
                _json(reason),
            ),
        )
        action_count += 1
        total_bytes += expected_size
        if action_count % DATABASE_BATCH_SIZE == 0:
            con.commit()
    con.execute(
        "UPDATE organize_plans SET summary_json = ? WHERE id = ?",
        (
            _json(
                {
                    "action_count": action_count,
                    "event_threshold": event_threshold,
                    "estimated_bytes": total_bytes,
                    "execution_mode": "approval_gated_copy_verify_unlink",
                }
            ),
            plan_id,
        ),
    )
    con.commit()
    return {
        "plan_id": plan_id,
        "action_count": action_count,
        "archive_root": str(archive_root_path),
        "estimated_bytes": total_bytes,
    }


def list_plans(con: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = con.execute(
        """
        SELECT organize_plans.*,
               (SELECT COUNT(*) FROM plan_actions WHERE plan_id = organize_plans.id) AS action_count
        FROM organize_plans
        ORDER BY id DESC
        """
    ).fetchall()
    return [
        {
            "id": row["id"],
            "strategy": row["strategy"],
            "archive_root": row["archive_root"],
            "status": row["status"],
            "created_at": row["created_at"],
            "summary": json.loads(row["summary_json"] or "{}"),
            "action_count": int(row["action_count"]),
        }
        for row in rows
    ]


def list_plan_actions(
    con: sqlite3.Connection,
    plan_id: int,
    *,
    status: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> dict[str, Any]:
    filters = ["plan_id = ?"]
    params: list[Any] = [plan_id]
    if status:
        filters.append("status = ?")
        params.append(status)
    where = " AND ".join(filters)
    total = int(
        con.execute(f"SELECT COUNT(*) AS count FROM plan_actions WHERE {where}", params).fetchone()[
            "count"
        ]
    )
    rows = con.execute(
        f"""
        SELECT *
        FROM plan_actions
        WHERE {where}
        ORDER BY id
        LIMIT ? OFFSET ?
        """,
        [*params, max(1, min(10_000, int(limit))), max(0, int(offset))],
    ).fetchall()
    return {
        "plan_id": plan_id,
        "total": total,
        "rows": [
            {
                "id": row["id"],
                "source_path": row["source_path"],
                "destination_path": row["destination_path"],
                "action_type": row["action_type"],
                "expected_size": int(row["expected_size"]),
                "expected_mtime_ns": int(row["expected_mtime_ns"]),
                "status": row["status"],
                "reason": _loads(row["reason_json"]),
            }
            for row in rows
        ],
    }


def approve_plan(
    con: sqlite3.Connection,
    *,
    plan_id: int,
    approved: bool,
    note: str = "",
    approval_type: str = "execute_plan",
) -> dict[str, Any]:
    row = con.execute("SELECT id FROM organize_plans WHERE id = ?", (plan_id,)).fetchone()
    if row is None:
        raise ValueError(f"plan not found: {plan_id}")
    con.execute(
        """
        INSERT INTO approvals(approval_type, target_type, target_id, approved, note, approved_at)
        VALUES(?, 'organize_plan', ?, ?, ?, ?)
        """,
        (approval_type, plan_id, 1 if approved else 0, note, utc_now()),
    )
    con.execute(
        "UPDATE organize_plans SET status = ? WHERE id = ?",
        ("approved" if approved else "rejected", plan_id),
    )
    con.commit()
    return {"plan_id": plan_id, "approved": bool(approved), "note": note}


def latest_plan_approval(con: sqlite3.Connection, plan_id: int) -> bool:
    row = con.execute(
        """
        SELECT approved
        FROM approvals
        WHERE target_type = 'organize_plan'
          AND target_id = ?
          AND approval_type = 'execute_plan'
        ORDER BY id DESC
        LIMIT 1
        """,
        (plan_id,),
    ).fetchone()
    return bool(row and int(row["approved"]) == 1)


def _active_source_roots(con: sqlite3.Connection) -> list[Path]:
    roots = []
    for row in con.execute(
        """
        SELECT DISTINCT root
        FROM media_files
        WHERE exists_on_disk = 1
        ORDER BY root
        """
    ):
        try:
            roots.append(_safe_resolve(row["root"]))
        except OSError:
            continue
    return roots


def _has_case_collision_on_disk(destination: Path) -> bool:
    parent = destination.parent
    if not parent.exists() or not parent.is_dir():
        return False
    target = destination.name.lower()
    try:
        for child in parent.iterdir():
            if child.name.lower() == target and child.name != destination.name:
                return True
    except OSError:
        return True
    return False


class _SqlitePathSet:
    """Set-like destination tracker that keeps large dry-runs out of Python memory."""

    def __init__(self, con: sqlite3.Connection) -> None:
        self.con = con
        con.execute("DROP TABLE IF EXISTS temp.photos_seen_destinations")
        con.execute(
            "CREATE TEMP TABLE photos_seen_destinations(path_ci TEXT PRIMARY KEY) WITHOUT ROWID"
        )

    def __contains__(self, value: str) -> bool:
        return (
            self.con.execute(
                "SELECT 1 FROM photos_seen_destinations WHERE path_ci = ?",
                (value,),
            ).fetchone()
            is not None
        )

    def add(self, value: str) -> None:
        self.con.execute(
            "INSERT OR IGNORE INTO photos_seen_destinations(path_ci) VALUES(?)",
            (value,),
        )

    def close(self) -> None:
        self.con.execute("DROP TABLE IF EXISTS temp.photos_seen_destinations")


def _validate_action(
    con: sqlite3.Connection,
    action: sqlite3.Row,
    *,
    archive_root: Path,
    seen_destinations: Any,
) -> tuple[list[str], list[str]]:
    blocking: list[str] = []
    warnings: list[str] = []
    source = Path(action["source_path"])
    destination = Path(action["destination_path"])

    try:
        destination.resolve().relative_to(archive_root)
    except ValueError:
        blocking.append("destination_escapes_archive_root")
    if source.resolve() == destination.resolve():
        blocking.append("source_equals_destination")
    if _is_windows_reparse_point(source):
        blocking.append("source_reparse_point_not_allowed")
    if _is_windows_reparse_point(destination.parent):
        blocking.append("destination_parent_reparse_point_not_allowed")
    if len(str(destination)) > MAX_SAFE_WINDOWS_PATH:
        blocking.append("destination_path_too_long_for_default_windows_policy")
    ci = _norm_case(destination)
    if ci in seen_destinations:
        blocking.append("case_insensitive_destination_collision_in_plan")
    seen_destinations.add(ci)
    if destination.exists():
        blocking.append("destination_already_exists")
    if _has_case_collision_on_disk(destination):
        blocking.append("destination_case_collision_on_disk")
    existing_dest = con.execute(
        """
        SELECT path
        FROM media_files
        WHERE exists_on_disk = 1
          AND lower(path) = lower(?)
          AND path != ?
        LIMIT 1
        """,
        (str(destination), str(source)),
    ).fetchone()
    if existing_dest is not None:
        blocking.append("destination_path_already_active_in_db")

    if not source.exists():
        blocking.append("source_missing")
    else:
        try:
            stat = source.stat()
        except OSError as exc:
            blocking.append(f"source_stat_failed:{exc.__class__.__name__}")
        else:
            if int(stat.st_size) != int(action["expected_size"]):
                blocking.append("source_size_changed")
            if int(stat.st_mtime_ns) != int(action["expected_mtime_ns"]):
                blocking.append("source_mtime_changed")
            if not source.is_file():
                blocking.append("source_not_regular_file")
            if source.is_symlink():
                blocking.append("source_symlink_not_allowed")
            if destination.parent.resolve() == source.parent.resolve():
                warnings.append("destination_same_folder_as_source")
    return blocking, warnings


def dry_run_plan(
    con: sqlite3.Connection,
    plan_id: int,
    *,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    plan = con.execute("SELECT * FROM organize_plans WHERE id = ?", (plan_id,)).fetchone()
    if plan is None:
        raise ValueError(f"plan not found: {plan_id}")

    blocking: list[str] = []
    warnings: list[str] = []
    destination_ci = _SqlitePathSet(con)
    total_bytes = 0
    largest_file = 0
    action_count = 0
    archive_root = _safe_resolve(plan["archive_root"])
    _emit_progress(
        progress_callback,
        {
            "operation": "dry_run_plan",
            "phase": "starting",
            "plan_id": plan_id,
            "action_count": 0,
            "estimated_bytes": 0,
            "blocking_count": 0,
            "warning_count": 0,
        },
    )

    if not latest_plan_approval(con, plan_id):
        warnings.append("missing_execute_approval")

    # The archive root may be created during execution; free-space checks use
    # the nearest existing parent.
    nearest_existing = archive_root
    while not nearest_existing.exists() and nearest_existing.parent != nearest_existing:
        nearest_existing = nearest_existing.parent
    try:
        free_bytes = shutil.disk_usage(nearest_existing).free
    except OSError:
        free_bytes = None
        warnings.append("destination_free_space_unknown")

    samples: list[dict[str, Any]] = []
    action_warnings: list[str] = []
    try:
        for actions in _iter_id_keyset(
            con,
            """
            SELECT * FROM plan_actions
            WHERE plan_id = ? AND status IN ('pending', 'held') AND id > ?
            ORDER BY id
            LIMIT ?
            """,
            (plan_id,),
        ):
            for action in actions:
                action_count += 1
                total_bytes += int(action["expected_size"])
                largest_file = max(largest_file, int(action["expected_size"]))
                item_reasons, item_warnings = _validate_action(
                    con,
                    action,
                    archive_root=archive_root,
                    seen_destinations=destination_ci,
                )
                action_warnings.extend(f"action:{action['id']}:{reason}" for reason in item_warnings)
                if item_reasons:
                    blocking.extend(f"action:{action['id']}:{reason}" for reason in item_reasons)
                if len(samples) < 20:
                    samples.append(
                        {
                            "action_id": int(action["id"]),
                            "source_path": str(action["source_path"]),
                            "destination_path": str(action["destination_path"]),
                            "blocking_reasons": item_reasons,
                            "warnings": item_warnings,
                        }
                    )
                if action_count == 1 or action_count % PROGRESS_FRAME_INTERVAL == 0:
                    _emit_progress(
                        progress_callback,
                        {
                            "operation": "dry_run_plan",
                            "phase": "validating",
                            "plan_id": plan_id,
                            "action_count": action_count,
                            "estimated_bytes": total_bytes,
                            "largest_file_bytes": largest_file,
                            "blocking_count": len(blocking),
                            "warning_count": len(warnings) + len(action_warnings),
                        },
                    )
    finally:
        destination_ci.close()

    for source_root in _active_source_roots(con):
        if source_root == archive_root:
            continue
        if _paths_overlap(source_root, archive_root):
            blocking.append("archive_root_inside_active_source_root")
        if _paths_overlap(archive_root, source_root):
            blocking.append("active_source_root_inside_archive_root")

    if free_bytes is not None and action_count:
        required_peak = largest_file + MIN_DESTINATION_FREE_MARGIN_BYTES
        if free_bytes < required_peak:
            blocking.append("insufficient_destination_free_space_for_largest_file")

    # Keep blocker lists stable for UI diffing and tests.
    blocking = sorted(set(blocking))
    warnings.extend(action_warnings)
    warnings = sorted(set(warnings))
    execute_allowed = not blocking and latest_plan_approval(con, plan_id)
    summary = {
        "plan_id": plan_id,
        "action_count": action_count,
        "estimated_bytes": total_bytes,
        "largest_file_bytes": largest_file,
        "archive_root": str(archive_root),
        "execute_allowed": execute_allowed,
        "blocking_reasons": blocking,
        "warnings": warnings,
        "samples": samples,
        "destructive_action_performed": False,
        "execution_method": "copy2_to_temp_verify_replace_unlink_source",
    }
    con.execute(
        """
        INSERT INTO dry_run_reports(
            plan_id, error_count, execute_allowed, blocking_reasons_json, summary_json, created_at
        )
        VALUES(?, ?, ?, ?, ?, ?)
        """,
        (plan_id, len(blocking), 1 if execute_allowed else 0, _json(blocking), _json(summary), utc_now()),
    )
    con.execute(
        "UPDATE organize_plans SET status = ? WHERE id = ?",
        ("dry_run_passed" if execute_allowed else "dry_run_blocked", plan_id),
    )
    con.commit()
    _emit_progress(
        progress_callback,
        {
            "operation": "dry_run_plan",
            "phase": "completed",
            "plan_id": plan_id,
            "action_count": action_count,
            "estimated_bytes": total_bytes,
            "largest_file_bytes": largest_file,
            "blocking_count": len(blocking),
            "warning_count": len(warnings),
            "execute_allowed": execute_allowed,
        },
    )
    return summary


def can_execute(con: sqlite3.Connection, plan_id: int) -> dict[str, Any]:
    dry = dry_run_plan(con, plan_id)
    reasons = list(dry["blocking_reasons"])
    if not latest_plan_approval(con, plan_id):
        reasons.append("missing_execute_approval")
    enabled = bool(dry["execute_allowed"] and not reasons)
    return {
        "plan_id": plan_id,
        "can_execute": enabled,
        "blocking_reasons": reasons,
        "warnings": dry.get("warnings", []),
        "dry_run": dry,
        "destructive_action_performed": False,
    }


def _insert_batch(
    con: sqlite3.Connection,
    *,
    plan_id: int,
    transfer_method: str,
    estimated_bytes: int,
    status: str,
    summary: dict[str, Any] | None = None,
) -> int:
    cur = con.execute(
        """
        INSERT INTO execution_batches(plan_id, transfer_method, estimated_bytes, status, started_at, summary_json)
        VALUES(?, ?, ?, ?, ?, ?)
        """,
        (plan_id, transfer_method, estimated_bytes, status, utc_now(), _json(summary or {})),
    )
    con.commit()
    return int(cur.lastrowid)


def _set_batch_finished(
    con: sqlite3.Connection,
    batch_id: int,
    *,
    status: str,
    summary: dict[str, Any],
) -> None:
    con.execute(
        """
        UPDATE execution_batches
        SET status = ?, finished_at = ?, summary_json = ?
        WHERE id = ?
        """,
        (status, utc_now(), _json(summary), batch_id),
    )
    con.commit()


def _record_verification(
    con: sqlite3.Connection,
    *,
    batch_item_id: int,
    destination: Path,
    status: str,
    details: dict[str, Any],
) -> None:
    size = None
    mtime = None
    if destination.exists():
        try:
            stat = destination.stat()
            size = int(stat.st_size)
            mtime = int(stat.st_mtime_ns)
        except OSError:
            pass
    con.execute(
        """
        INSERT INTO transfer_verifications(
            batch_item_id, destination_size, destination_mtime_ns,
            verification_status, verified_at, details_json
        )
        VALUES(?, ?, ?, ?, ?, ?)
        """,
        (batch_item_id, size, mtime, status, utc_now(), _json(details)),
    )


def _update_media_row_after_move(
    con: sqlite3.Connection,
    *,
    source: Path,
    destination: Path,
    archive_root: Path,
    sha256: str | None,
) -> None:
    stat = destination.stat()
    rel_path = _relative_to_or_empty(destination, archive_root)
    parent = Path(rel_path).parent.as_posix()
    parent_key = "" if parent == "." else parent.lower()
    con.execute(
        """
        UPDATE media_files
        SET root = ?, path = ?, rel_path = ?, parent_key = ?, name = ?, stem_key = ?,
            suffix = ?, size_bytes = ?, mtime_ns = ?, sha256 = COALESCE(?, sha256),
            indexed_at = ?, exists_on_disk = 1, missing_at = NULL, last_seen_at = ?
        WHERE path = ?
        """,
        (
            str(archive_root),
            str(destination),
            rel_path,
            parent_key,
            destination.name,
            destination.stem.lower(),
            destination.suffix.lower(),
            int(stat.st_size),
            int(stat.st_mtime_ns),
            sha256,
            utc_now(),
            utc_now(),
            str(source),
        ),
    )


def _update_media_row_after_rollback(
    con: sqlite3.Connection,
    *,
    source: Path,
    destination: Path,
    reason: dict[str, Any],
    sha256: str | None,
) -> None:
    stat = source.stat()
    con.execute(
        """
        UPDATE media_files
        SET root = ?, path = ?, rel_path = ?, parent_key = ?, name = ?, stem_key = ?,
            suffix = ?, size_bytes = ?, mtime_ns = ?, sha256 = COALESCE(?, sha256),
            indexed_at = ?, exists_on_disk = 1, missing_at = NULL, last_seen_at = ?
        WHERE path = ?
        """,
        (
            reason.get("source_root", str(source.parent)),
            str(source),
            reason.get("source_rel_path", source.name),
            reason.get("source_parent_key", source.parent.name.lower()),
            reason.get("source_name", source.name),
            reason.get("source_stem_key", source.stem.lower()),
            reason.get("source_suffix", source.suffix.lower()),
            int(stat.st_size),
            int(stat.st_mtime_ns),
            sha256,
            utc_now(),
            utc_now(),
            str(destination),
        ),
    )


def _copy_verify_replace(
    *,
    source: Path,
    destination: Path,
    expected_size: int,
    expected_sha256: str | None,
    batch_id: int,
    action_id: int,
    verify_hashes: bool,
) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(destination)
    tmp = destination.parent / f".{destination.name}.photos-copy-{batch_id}-{action_id}.part"
    if tmp.exists():
        raise FileExistsError(tmp)
    try:
        shutil.copy2(source, tmp)
        tmp_stat = tmp.stat()
        if int(tmp_stat.st_size) != int(expected_size):
            raise IOError("copied_size_mismatch")
        actual_sha = None
        source_sha = expected_sha256
        if verify_hashes:
            if source_sha is None:
                source_sha = sha256_file(source)
            actual_sha = sha256_file(tmp)
            if actual_sha != source_sha:
                raise IOError("copied_sha256_mismatch")
        os.replace(tmp, destination)
        final_stat = destination.stat()
        if int(final_stat.st_size) != int(expected_size):
            raise IOError("destination_size_mismatch_after_replace")
        return {
            "source_sha256": source_sha,
            "destination_sha256": actual_sha or source_sha,
            "destination_size": int(final_stat.st_size),
            "destination_mtime_ns": int(final_stat.st_mtime_ns),
        }
    except Exception:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise


def _write_batch_manifest(con: sqlite3.Connection, batch_id: int) -> dict[str, Any]:
    batch = con.execute("SELECT * FROM execution_batches WHERE id = ?", (batch_id,)).fetchone()
    if batch is None:
        raise ValueError(f"batch not found: {batch_id}")
    plan = con.execute("SELECT * FROM organize_plans WHERE id = ?", (batch["plan_id"],)).fetchone()
    archive_root = _safe_resolve(plan["archive_root"]) if plan is not None else Path.cwd().resolve()
    manifest_dir = archive_root / ".photos-manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    aggregate = con.execute(
        """
        SELECT COUNT(*) AS item_count,
               COALESCE(SUM(plan_actions.expected_size), 0) AS total_bytes,
               COALESCE(MAX(CASE WHEN batch_items.status = 'completed' THEN 1 ELSE 0 END), 0)
                   AS destructive_action_performed
        FROM batch_items
        JOIN plan_actions ON plan_actions.id = batch_items.plan_action_id
        WHERE batch_items.batch_id = ?
        """,
        (batch_id,),
    ).fetchone()
    item_count = int(aggregate["item_count"])
    total_bytes = int(aggregate["total_bytes"])
    manifest = {
        "schema_version": "formal-execution-manifest-v1",
        "batch_id": int(batch["id"]),
        "plan_id": int(batch["plan_id"]),
        "transfer_method": batch["transfer_method"],
        "status": batch["status"],
        "started_at": batch["started_at"],
        "finished_at": batch["finished_at"],
        "archive_root": str(archive_root),
        "summary": _loads(batch["summary_json"]),
        "item_count": item_count,
        "total_bytes": total_bytes,
        "destructive_action_performed": bool(aggregate["destructive_action_performed"]),
        "safety": {
            "execution_requires_db_approval": True,
            "execution_requires_runtime_confirmation": True,
            "source_removed_only_after_verified_copy": True,
            "rollback_reference_included": True,
        },
    }
    path = manifest_dir / f"batch-{batch_id:06d}.json"
    tmp = path.with_suffix(".json.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write("{")
            first_field = True
            for key, value in manifest.items():
                if not first_field:
                    handle.write(",")
                handle.write(json.dumps(key))
                handle.write(":")
                json.dump(value, handle, sort_keys=True, ensure_ascii=False)
                first_field = False
            handle.write(',"items":[')
            first_item = True
            for item_page in _iter_id_keyset(
                con,
                """
                SELECT batch_items.*, plan_actions.reason_json, plan_actions.expected_size,
                       plan_actions.expected_mtime_ns, plan_actions.action_type
                FROM batch_items
                JOIN plan_actions ON plan_actions.id = batch_items.plan_action_id
                WHERE batch_items.batch_id = ? AND batch_items.id > ?
                ORDER BY batch_items.id
                LIMIT ?
                """,
                (batch_id,),
            ):
                for item in item_page:
                    if not first_item:
                        handle.write(",")
                    first_item = False
                    item_fields = {
                "batch_item_id": int(item["id"]),
                "plan_action_id": int(item["plan_action_id"]),
                "source_path": item["source_path"],
                "destination_path": item["destination_path"],
                "action_type": item["action_type"],
                "expected_size": int(item["expected_size"]),
                "expected_mtime_ns": int(item["expected_mtime_ns"]),
                "status": item["status"],
                "error_code": item["error_code"],
                "error_message": item["error_message"],
                "reason": _loads(item["reason_json"]),
                "rollback_instruction": {
                    "method": "copy_verify_replace_back_then_unlink_archive_copy",
                    "from": item["destination_path"],
                    "to": item["source_path"],
                    "requires_destination_to_match_verification": True,
                    "requires_original_source_path_to_be_absent": True,
                },
            }
                    handle.write("{")
                    first_item_field = True
                    for key, value in item_fields.items():
                        if not first_item_field:
                            handle.write(",")
                        handle.write(json.dumps(key))
                        handle.write(":")
                        json.dump(value, handle, sort_keys=True, ensure_ascii=False)
                        first_item_field = False
                    handle.write(',"verifications":[')
                    first_verification = True
                    for verification in con.execute(
                        """
                        SELECT * FROM transfer_verifications
                        WHERE batch_item_id = ?
                        ORDER BY id
                        """,
                        (item["id"],),
                    ):
                        if not first_verification:
                            handle.write(",")
                        first_verification = False
                        json.dump(
                            {
                                "id": int(verification["id"]),
                                "destination_size": verification["destination_size"],
                                "destination_mtime_ns": verification["destination_mtime_ns"],
                                "verification_status": verification["verification_status"],
                                "verified_at": verification["verified_at"],
                                "details": _loads(verification["details_json"]),
                            },
                            handle,
                            sort_keys=True,
                            ensure_ascii=False,
                        )
                    handle.write("]}")
            handle.write("]}")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
    digest = sha256_file(path)
    con.execute(
        """
        INSERT INTO batch_manifests(batch_id, manifest_path, manifest_sha256, item_count, total_bytes, created_at)
        VALUES(?, ?, ?, ?, ?, ?)
        """,
        (batch_id, str(path), digest, item_count, total_bytes, utc_now()),
    )
    con.commit()
    return {
        "manifest_path": str(path),
        "manifest_sha256": digest,
        "item_count": item_count,
        "total_bytes": total_bytes,
    }


def _execute_plan_unlocked(
    con: sqlite3.Connection,
    plan_id: int,
    *,
    execute_approved: bool = False,
    verify_hashes: bool = True,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    progress_operation: str = "execute_plan",
) -> dict[str, Any]:
    """Execute an approved archive plan using copy-verify-unlink semantics.

    Safety gates:
    1. plan approval must be recorded in the DB;
    2. caller must pass ``execute_approved=True`` for this specific invocation;
    3. dry-run must pass immediately before file mutation;
    4. every file is copied to a temp file, verified, atomically renamed, then
       the source is unlinked.
    """

    gate = can_execute(con, plan_id)
    estimated_bytes = int(gate.get("dry_run", {}).get("estimated_bytes", 0))
    if not execute_approved:
        batch_id = _insert_batch(
            con,
            plan_id=plan_id,
            transfer_method="copy_verify_unlink",
            estimated_bytes=estimated_bytes,
            status="held",
            summary={"gate": gate, "reason": "runtime_execute_confirmation_missing"},
        )
        return {
            "batch_id": batch_id,
            "executed": False,
            "gate": gate,
            "blocking_reasons": ["runtime_execute_confirmation_missing"],
            "destructive_action_performed": False,
        }
    if not gate["can_execute"]:
        batch_id = _insert_batch(
            con,
            plan_id=plan_id,
            transfer_method="copy_verify_unlink",
            estimated_bytes=estimated_bytes,
            status="held",
            summary={"gate": gate, "reason": "execution_gate_blocked"},
        )
        return {
            "batch_id": batch_id,
            "executed": False,
            "gate": gate,
            "blocking_reasons": gate.get("blocking_reasons", []),
            "destructive_action_performed": False,
        }

    plan = con.execute("SELECT * FROM organize_plans WHERE id = ?", (plan_id,)).fetchone()
    if plan is None:
        raise ValueError(f"plan not found: {plan_id}")
    archive_root = _safe_resolve(plan["archive_root"])
    total_actions = int(
        con.execute(
            """
            SELECT COUNT(*) AS count
            FROM plan_actions
            WHERE plan_id = ? AND status IN ('pending', 'held')
            """,
            (plan_id,),
        ).fetchone()["count"]
    )
    db_backup = _backup_database(con, archive_root=archive_root, label=f"before-execute-plan-{plan_id}")
    batch_id = _insert_batch(
        con,
        plan_id=plan_id,
        transfer_method="copy_verify_unlink",
        estimated_bytes=estimated_bytes,
        status="running",
        summary={"gate": gate},
    )
    _emit_progress(
        progress_callback,
        {
            "operation": progress_operation,
            "phase": "starting",
            "plan_id": plan_id,
            "batch_id": batch_id,
            "total": total_actions,
            "completed": 0,
            "failed": 0,
        },
    )

    completed = 0
    failed = 0
    bytes_completed = 0
    item_samples: list[dict[str, Any]] = []
    stop = False
    for actions in _iter_id_keyset(
        con,
        """
        SELECT * FROM plan_actions
        WHERE plan_id = ? AND status IN ('pending', 'held') AND id > ?
        ORDER BY id
        LIMIT ?
        """,
        (plan_id,),
    ):
        registered: list[tuple[sqlite3.Row, int]] = []
        for action in actions:
            cur = con.execute(
                """
                INSERT INTO batch_items(batch_id, plan_action_id, source_path, destination_path, status)
                VALUES(?, ?, ?, ?, 'running')
                """,
                (
                    batch_id,
                    int(action["id"]),
                    str(action["source_path"]),
                    str(action["destination_path"]),
                ),
            )
            registered.append((action, int(cur.lastrowid)))
        # Every filesystem mutation in this chunk now has durable recovery evidence.
        con.commit()
        for chunk_index, (action, batch_item_id) in enumerate(registered, start=1):
            source = Path(action["source_path"])
            destination = Path(action["destination_path"])
            reason = _loads(action["reason_json"])
            expected_sha = reason.get("source_sha256")
            try:
                copy_details = _copy_verify_replace(
                    source=source,
                    destination=destination,
                    expected_size=int(action["expected_size"]),
                    expected_sha256=expected_sha,
                    batch_id=batch_id,
                    action_id=int(action["id"]),
                    verify_hashes=verify_hashes,
                )
                source.unlink()
                final_sha = copy_details.get("destination_sha256") or copy_details.get("source_sha256")
                _update_media_row_after_move(
                    con,
                    source=source,
                    destination=destination,
                    archive_root=archive_root,
                    sha256=final_sha,
                )
                con.execute("UPDATE plan_actions SET status = 'completed' WHERE id = ?", (action["id"],))
                con.execute("UPDATE batch_items SET status = 'completed' WHERE id = ?", (batch_item_id,))
                _record_verification(
                    con,
                    batch_item_id=batch_item_id,
                    destination=destination,
                    status="verified",
                    details={
                        **copy_details,
                        "source_removed_after_verified_copy": True,
                        "verify_hashes": verify_hashes,
                    },
                )
                completed += 1
                bytes_completed += int(action["expected_size"])
                if len(item_samples) < 20:
                    item_samples.append(
                        {
                            "action_id": int(action["id"]),
                            "status": "completed",
                            "source_path": str(source),
                            "destination_path": str(destination),
                        }
                    )
                processed = completed + failed
                if _should_emit_progress(processed, total_actions):
                    _emit_progress(
                        progress_callback,
                        {
                            "operation": progress_operation,
                            "phase": "executing",
                            "plan_id": plan_id,
                            "batch_id": batch_id,
                            "total": total_actions,
                            "completed": completed,
                            "failed": failed,
                            "current_action_id": int(action["id"]),
                            "current_source_path": str(source),
                            "current_destination_path": str(destination),
                            "status": "completed",
                        },
                    )
                if chunk_index % MUTATION_COMMIT_INTERVAL == 0:
                    con.commit()
            except Exception as exc:
                failed += 1
                error_code = exc.__class__.__name__
                con.execute(
                    """
                    UPDATE batch_items
                    SET status = 'failed', error_code = ?, error_message = ?
                    WHERE id = ?
                    """,
                    (error_code, str(exc), batch_item_id),
                )
                con.execute("UPDATE plan_actions SET status = 'failed' WHERE id = ?", (action["id"],))
                _record_verification(
                    con,
                    batch_item_id=batch_item_id,
                    destination=destination,
                    status="failed",
                    details={"error_code": error_code, "error_message": str(exc)},
                )
                if len(item_samples) < 20:
                    item_samples.append(
                        {
                            "action_id": int(action["id"]),
                            "status": "failed",
                            "source_path": str(source),
                            "destination_path": str(destination),
                            "error_code": error_code,
                            "error_message": str(exc),
                        }
                    )
                _emit_progress(
                    progress_callback,
                    {
                        "operation": progress_operation,
                        "phase": "executing",
                        "plan_id": plan_id,
                        "batch_id": batch_id,
                        "total": total_actions,
                        "completed": completed,
                        "failed": failed,
                        "current_action_id": int(action["id"]),
                        "current_source_path": str(source),
                        "current_destination_path": str(destination),
                        "status": "failed",
                        "error_code": error_code,
                    },
                )
                con.commit()
                stop = True
                break
        con.commit()
        if stop:
            break

    status = "completed" if failed == 0 else "completed_with_errors"
    plan_status = "executed" if failed == 0 else "partially_executed"
    summary = {
        "plan_id": plan_id,
        "batch_id": batch_id,
        "executed": completed > 0,
        "completed_count": completed,
        "failed_count": failed,
        "bytes_completed": bytes_completed,
        "item_samples": item_samples,
        "destructive_action_performed": completed > 0,
        "execution_method": "copy2_temp_verify_replace_unlink_source",
        "database_backup": db_backup,
    }
    _set_batch_finished(con, batch_id, status=status, summary=summary)
    con.execute("UPDATE organize_plans SET status = ? WHERE id = ?", (plan_status, plan_id))
    con.commit()
    manifest = _write_batch_manifest(con, batch_id)
    summary.update(manifest)
    _emit_progress(
        progress_callback,
        {
            "operation": progress_operation,
            "phase": "completed" if failed == 0 else "completed_with_errors",
            "plan_id": plan_id,
            "batch_id": batch_id,
            "total": total_actions,
            "completed": completed,
            "failed": failed,
            "bytes_completed": bytes_completed,
        },
    )
    return summary


def list_execution_batches(
    con: sqlite3.Connection,
    *,
    plan_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    filters = ["1 = 1"]
    params: list[Any] = []
    if plan_id is not None:
        filters.append("plan_id = ?")
        params.append(plan_id)
    where = " AND ".join(filters)
    total = int(
        con.execute(f"SELECT COUNT(*) AS count FROM execution_batches WHERE {where}", params).fetchone()[
            "count"
        ]
    )
    rows = con.execute(
        f"""
        SELECT execution_batches.*,
               (SELECT COUNT(*) FROM batch_items WHERE batch_id = execution_batches.id) AS item_count,
               (SELECT manifest_path FROM batch_manifests WHERE batch_id = execution_batches.id ORDER BY id DESC LIMIT 1) AS manifest_path
        FROM execution_batches
        WHERE {where}
        ORDER BY id DESC
        LIMIT ? OFFSET ?
        """,
        [*params, max(1, min(1000, int(limit))), max(0, int(offset))],
    ).fetchall()
    return {
        "total": total,
        "rows": [
            {
                "id": int(row["id"]),
                "plan_id": int(row["plan_id"]),
                "transfer_method": row["transfer_method"],
                "estimated_bytes": int(row["estimated_bytes"]),
                "status": row["status"],
                "started_at": row["started_at"],
                "finished_at": row["finished_at"],
                "summary": _loads(row["summary_json"]),
                "item_count": int(row["item_count"]),
                "manifest_path": row["manifest_path"],
            }
            for row in rows
        ],
    }


def list_batch_items(
    con: sqlite3.Connection,
    batch_id: int,
    *,
    limit: int = 500,
    offset: int = 0,
) -> dict[str, Any]:
    total = int(
        con.execute("SELECT COUNT(*) AS count FROM batch_items WHERE batch_id = ?", (batch_id,)).fetchone()[
            "count"
        ]
    )
    rows = con.execute(
        """
        SELECT * FROM batch_items
        WHERE batch_id = ?
        ORDER BY id
        LIMIT ? OFFSET ?
        """,
        (batch_id, max(1, min(10_000, int(limit))), max(0, int(offset))),
    ).fetchall()
    return {
        "batch_id": batch_id,
        "total": total,
        "rows": [
            {
                "id": int(row["id"]),
                "plan_action_id": int(row["plan_action_id"]),
                "source_path": row["source_path"],
                "destination_path": row["destination_path"],
                "status": row["status"],
                "error_code": row["error_code"],
                "error_message": row["error_message"],
            }
            for row in rows
        ],
    }


def _rollback_batch_unlocked(
    con: sqlite3.Connection,
    batch_id: int,
    *,
    execute_approved: bool = False,
    verify_hashes: bool = True,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    progress_operation: str = "rollback_batch",
) -> dict[str, Any]:
    """Reverse a completed archive batch when the archive copy still verifies.

    Rollback uses the same safety model as execution and refuses to overwrite an
    existing original source path.
    """

    original = con.execute("SELECT * FROM execution_batches WHERE id = ?", (batch_id,)).fetchone()
    if original is None:
        raise ValueError(f"batch not found: {batch_id}")
    if original["transfer_method"] == "rollback":
        raise ValueError("cannot rollback a rollback batch")
    if not execute_approved:
        rollback_id = _insert_batch(
            con,
            plan_id=int(original["plan_id"]),
            transfer_method="rollback",
            estimated_bytes=int(original["estimated_bytes"]),
            status="held",
            summary={"source_batch_id": batch_id, "reason": "runtime_rollback_confirmation_missing"},
        )
        return {
            "batch_id": rollback_id,
            "source_batch_id": batch_id,
            "rolled_back": False,
            "blocking_reasons": ["runtime_rollback_confirmation_missing"],
            "destructive_action_performed": False,
        }

    blockers: list[str] = []
    rollback_items_sql = """
        SELECT batch_items.*, plan_actions.reason_json, plan_actions.expected_size
        FROM batch_items
        JOIN plan_actions ON plan_actions.id = batch_items.plan_action_id
        WHERE batch_items.batch_id = ? AND batch_items.status = 'completed'
          AND batch_items.id < ?
        ORDER BY batch_items.id DESC
        LIMIT ?
    """
    for original_items in _iter_id_keyset(
        con,
        rollback_items_sql,
        (batch_id,),
        descending=True,
    ):
        for item in original_items:
            source = Path(item["source_path"])
            destination = Path(item["destination_path"])
            if source.exists():
                blockers.append(f"item:{item['id']}:source_path_already_exists")
            if not destination.exists():
                blockers.append(f"item:{item['id']}:destination_missing")
            elif int(destination.stat().st_size) != int(item["expected_size"]):
                blockers.append(f"item:{item['id']}:destination_size_changed")
    if blockers:
        rollback_id = _insert_batch(
            con,
            plan_id=int(original["plan_id"]),
            transfer_method="rollback",
            estimated_bytes=int(original["estimated_bytes"]),
            status="held",
            summary={"source_batch_id": batch_id, "blocking_reasons": blockers},
        )
        return {
            "batch_id": rollback_id,
            "source_batch_id": batch_id,
            "rolled_back": False,
            "blocking_reasons": blockers,
            "destructive_action_performed": False,
        }

    plan = con.execute("SELECT * FROM organize_plans WHERE id = ?", (int(original["plan_id"]),)).fetchone()
    archive_root = _safe_resolve(plan["archive_root"]) if plan is not None else Path.cwd().resolve()
    total_items = int(
        con.execute(
            """
            SELECT COUNT(*) AS count
            FROM batch_items
            WHERE batch_id = ? AND status = 'completed'
            """,
            (batch_id,),
        ).fetchone()["count"]
    )
    db_backup = _backup_database(con, archive_root=archive_root, label=f"before-rollback-batch-{batch_id}")

    rollback_id = _insert_batch(
        con,
        plan_id=int(original["plan_id"]),
        transfer_method="rollback",
        estimated_bytes=int(original["estimated_bytes"]),
        status="running",
        summary={"source_batch_id": batch_id},
    )
    _emit_progress(
        progress_callback,
        {
            "operation": progress_operation,
            "phase": "starting",
            "batch_id": rollback_id,
            "source_batch_id": batch_id,
            "total": total_items,
            "completed": 0,
            "failed": 0,
        },
    )
    completed = 0
    failed = 0
    stop = False
    for original_items in _iter_id_keyset(
        con,
        rollback_items_sql,
        (batch_id,),
        descending=True,
    ):
        registered: list[tuple[sqlite3.Row, int]] = []
        for item in original_items:
            cur = con.execute(
                """
                INSERT INTO batch_items(batch_id, plan_action_id, source_path, destination_path, status)
                VALUES(?, ?, ?, ?, 'running')
                """,
                (
                    rollback_id,
                    int(item["plan_action_id"]),
                    str(item["destination_path"]),
                    str(item["source_path"]),
                ),
            )
            registered.append((item, int(cur.lastrowid)))
        con.commit()
        for chunk_index, (item, rollback_item_id) in enumerate(registered, start=1):
            source = Path(item["source_path"])
            destination = Path(item["destination_path"])
            action_id = int(item["plan_action_id"])
            reason = _loads(item["reason_json"])
            expected_sha = reason.get("source_sha256")
            try:
                copy_details = _copy_verify_replace(
                    source=destination,
                    destination=source,
                    expected_size=int(item["expected_size"]),
                    expected_sha256=expected_sha,
                    batch_id=rollback_id,
                    action_id=action_id,
                    verify_hashes=verify_hashes,
                )
                destination.unlink()
                final_sha = copy_details.get("destination_sha256") or copy_details.get("source_sha256")
                _update_media_row_after_rollback(
                    con,
                    source=source,
                    destination=destination,
                    reason=reason,
                    sha256=final_sha,
                )
                con.execute("UPDATE plan_actions SET status = 'rolled_back' WHERE id = ?", (action_id,))
                con.execute("UPDATE batch_items SET status = 'completed' WHERE id = ?", (rollback_item_id,))
                _record_verification(
                    con,
                    batch_item_id=rollback_item_id,
                    destination=source,
                    status="verified",
                    details={
                        **copy_details,
                        "archive_copy_removed_after_verified_restore": True,
                        "verify_hashes": verify_hashes,
                    },
                )
                completed += 1
                if chunk_index % MUTATION_COMMIT_INTERVAL == 0:
                    con.commit()
                processed = completed + failed
                if _should_emit_progress(processed, total_items):
                    _emit_progress(
                        progress_callback,
                        {
                            "operation": progress_operation,
                            "phase": "rolling_back",
                            "batch_id": rollback_id,
                            "source_batch_id": batch_id,
                            "total": total_items,
                            "completed": completed,
                            "failed": failed,
                            "current_action_id": action_id,
                            "current_source_path": str(source),
                            "current_destination_path": str(destination),
                            "status": "completed",
                        },
                    )
            except Exception as exc:
                failed += 1
                con.execute(
                    """
                    UPDATE batch_items
                    SET status = 'failed', error_code = ?, error_message = ?
                    WHERE id = ?
                    """,
                    (exc.__class__.__name__, str(exc), rollback_item_id),
                )
                _record_verification(
                    con,
                    batch_item_id=rollback_item_id,
                    destination=source,
                    status="failed",
                    details={"error_code": exc.__class__.__name__, "error_message": str(exc)},
                )
                con.commit()
                _emit_progress(
                    progress_callback,
                    {
                        "operation": progress_operation,
                        "phase": "rolling_back",
                        "batch_id": rollback_id,
                        "source_batch_id": batch_id,
                        "total": total_items,
                        "completed": completed,
                        "failed": failed,
                        "current_action_id": action_id,
                        "current_source_path": str(source),
                        "current_destination_path": str(destination),
                        "status": "failed",
                        "error_code": exc.__class__.__name__,
                    },
                )
                stop = True
                break
        con.commit()
        if stop:
            break

    status = "completed" if failed == 0 else "completed_with_errors"
    plan_status = "rolled_back" if failed == 0 else "rollback_partial"
    summary = {
        "source_batch_id": batch_id,
        "rollback_batch_id": rollback_id,
        "rolled_back": completed > 0 and failed == 0,
        "completed_count": completed,
        "failed_count": failed,
        "destructive_action_performed": completed > 0,
        "execution_method": "rollback_copy_verify_replace_unlink_archive_copy",
        "database_backup": db_backup,
    }
    _set_batch_finished(con, rollback_id, status=status, summary=summary)
    con.execute("UPDATE organize_plans SET status = ? WHERE id = ?", (plan_status, int(original["plan_id"])))
    con.commit()
    manifest = _write_batch_manifest(con, rollback_id)
    summary.update({"batch_id": rollback_id, **manifest})
    _emit_progress(
        progress_callback,
        {
            "operation": progress_operation,
            "phase": "completed" if failed == 0 else "completed_with_errors",
            "batch_id": rollback_id,
            "source_batch_id": batch_id,
            "total": total_items,
            "completed": completed,
            "failed": failed,
        },
    )
    return summary


def execute_plan(
    con: sqlite3.Connection,
    plan_id: int,
    *,
    execute_approved: bool = False,
    verify_hashes: bool = True,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    with _operation_lock(con, "filesystem-mutation", details={"operation": "execute_plan", "plan_id": plan_id}):
        return _execute_plan_unlocked(
            con,
            plan_id,
            execute_approved=execute_approved,
            verify_hashes=verify_hashes,
            progress_callback=progress_callback,
        )


def rollback_batch(
    con: sqlite3.Connection,
    batch_id: int,
    *,
    execute_approved: bool = False,
    verify_hashes: bool = True,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    with _operation_lock(con, "filesystem-mutation", details={"operation": "rollback_batch", "batch_id": batch_id}):
        return _rollback_batch_unlocked(
            con,
            batch_id,
            execute_approved=execute_approved,
            verify_hashes=verify_hashes,
            progress_callback=progress_callback,
        )


def validate_batch_manifest(
    con: sqlite3.Connection,
    batch_id: int,
    *,
    verify_files: bool = False,
) -> dict[str, Any]:
    row = con.execute(
        """
        SELECT *
        FROM batch_manifests
        WHERE batch_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (batch_id,),
    ).fetchone()
    if row is None:
        return {
            "batch_id": batch_id,
            "status": "missing_manifest_record",
            "valid": False,
            "errors": ["missing_manifest_record"],
        }
    manifest_path = Path(row["manifest_path"])
    errors: list[str] = []
    manifest: dict[str, Any] = {}
    actual_sha = None
    if not manifest_path.exists():
        errors.append("manifest_file_missing")
    else:
        actual_sha = sha256_file(manifest_path)
        if actual_sha != row["manifest_sha256"]:
            errors.append("manifest_sha256_mismatch")
        try:
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                manifest = loaded
            else:
                errors.append("manifest_json_not_object")
        except json.JSONDecodeError:
            errors.append("manifest_json_invalid")

    db_item_count = int(
        con.execute("SELECT COUNT(*) AS count FROM batch_items WHERE batch_id = ?", (batch_id,)).fetchone()[
            "count"
        ]
    )
    if manifest and int(manifest.get("item_count", -1)) != db_item_count:
        errors.append("manifest_item_count_mismatch")
    if manifest and int(manifest.get("total_bytes", -1)) != int(row["total_bytes"]):
        errors.append("manifest_total_bytes_mismatch")

    file_errors: list[str] = []
    if verify_files and manifest:
        for item in manifest.get("items", []):
            if item.get("status") != "completed":
                continue
            destination = Path(str(item.get("destination_path", "")))
            if not destination.exists():
                file_errors.append(f"item:{item.get('batch_item_id')}:destination_missing")
                continue
            try:
                size = destination.stat().st_size
            except OSError as exc:
                file_errors.append(f"item:{item.get('batch_item_id')}:stat_failed:{exc.__class__.__name__}")
                continue
            if int(size) != int(item.get("expected_size", -1)):
                file_errors.append(f"item:{item.get('batch_item_id')}:destination_size_mismatch")
    errors.extend(file_errors)
    status = "valid" if not errors else "invalid"
    return {
        "batch_id": batch_id,
        "status": status,
        "valid": not errors,
        "errors": errors,
        "manifest_path": str(manifest_path),
        "recorded_sha256": row["manifest_sha256"],
        "actual_sha256": actual_sha,
        "db_item_count": db_item_count,
        "manifest_item_count": manifest.get("item_count"),
        "verify_files": verify_files,
    }


def reconcile_batch(
    con: sqlite3.Connection,
    batch_id: int,
    *,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    progress_operation: str = "reconcile_batch",
) -> dict[str, Any]:
    batch = con.execute("SELECT * FROM execution_batches WHERE id = ?", (batch_id,)).fetchone()
    if batch is None:
        raise ValueError(f"batch not found: {batch_id}")
    if batch["transfer_method"] != "copy_verify_unlink":
        return {
            "batch_id": batch_id,
            "reconciled": False,
            "blocking_reasons": ["unsupported_batch_transfer_method"],
        }

    plan = con.execute("SELECT * FROM organize_plans WHERE id = ?", (batch["plan_id"],)).fetchone()
    archive_root = _safe_resolve(plan["archive_root"]) if plan is not None else Path.cwd().resolve()
    total_items = int(
        con.execute(
            "SELECT COUNT(*) AS count FROM batch_items WHERE batch_id = ?",
            (batch_id,),
        ).fetchone()["count"]
    )
    recovered_completed = 0
    retryable = 0
    already_good = 0
    blocking: list[str] = []
    details: list[dict[str, Any]] = []
    processed = 0
    _emit_progress(
        progress_callback,
        {
            "operation": progress_operation,
            "phase": "starting",
            "batch_id": batch_id,
            "total": total_items,
            "processed": 0,
            "recovered_completed": 0,
            "retryable": 0,
            "already_good": 0,
        },
    )
    for rows in _iter_id_keyset(
        con,
        """
        SELECT batch_items.*, plan_actions.reason_json, plan_actions.expected_size
        FROM batch_items
        JOIN plan_actions ON plan_actions.id = batch_items.plan_action_id
        WHERE batch_items.batch_id = ? AND batch_items.id > ?
        ORDER BY batch_items.id
        LIMIT ?
        """,
        (batch_id,),
    ):
        for item in rows:
            processed += 1
            source = Path(item["source_path"])
            destination = Path(item["destination_path"])
            source_exists = source.exists()
            destination_exists = destination.exists()
            expected_size = int(item["expected_size"])
            action_id = int(item["plan_action_id"])
            reason = _loads(item["reason_json"])
            status = item["status"]
            should_emit_progress = _should_emit_progress(processed, total_items)
            if status == "completed" and destination_exists and not source_exists:
                already_good += 1
                continue
            if destination_exists and not source_exists:
                try:
                    if destination.stat().st_size != expected_size:
                        raise IOError("destination_size_mismatch")
                    sha = reason.get("source_sha256")
                    _update_media_row_after_move(
                        con,
                        source=source,
                        destination=destination,
                        archive_root=archive_root,
                        sha256=sha,
                    )
                    con.execute("UPDATE plan_actions SET status = 'completed' WHERE id = ?", (action_id,))
                    con.execute("UPDATE batch_items SET status = 'completed' WHERE id = ?", (item["id"],))
                    _record_verification(
                        con,
                        batch_item_id=int(item["id"]),
                        destination=destination,
                        status="reconciled_verified",
                        details={"reason": "destination_exists_source_absent"},
                    )
                    recovered_completed += 1
                    if len(details) < 50:
                        details.append({"batch_item_id": int(item["id"]), "status": "recovered_completed"})
                    if should_emit_progress:
                        _emit_progress(
                            progress_callback,
                            {
                                "operation": progress_operation,
                                "phase": "reconciling",
                                "batch_id": batch_id,
                                "total": total_items,
                                "processed": processed,
                                "recovered_completed": recovered_completed,
                                "retryable": retryable,
                                "already_good": already_good,
                                "current_batch_item_id": int(item["id"]),
                                "status": "recovered_completed",
                            },
                        )
                except Exception as exc:
                    blocking.append(f"item:{item['id']}:reconcile_failed:{exc.__class__.__name__}")
                    _emit_progress(
                        progress_callback,
                        {
                            "operation": progress_operation,
                            "phase": "reconciling",
                            "batch_id": batch_id,
                            "total": total_items,
                            "processed": processed,
                            "recovered_completed": recovered_completed,
                            "retryable": retryable,
                            "already_good": already_good,
                            "current_batch_item_id": int(item["id"]),
                            "status": "failed",
                            "error_code": exc.__class__.__name__,
                        },
                    )
            elif source_exists and not destination_exists:
                con.execute("UPDATE plan_actions SET status = 'pending' WHERE id = ?", (action_id,))
                con.execute(
                    "UPDATE batch_items SET status = 'ready_for_retry', error_code = NULL, error_message = NULL WHERE id = ?",
                    (item["id"],),
                )
                retryable += 1
                if len(details) < 50:
                    details.append({"batch_item_id": int(item["id"]), "status": "ready_for_retry"})
                if should_emit_progress:
                    _emit_progress(
                        progress_callback,
                        {
                            "operation": progress_operation,
                            "phase": "reconciling",
                            "batch_id": batch_id,
                            "total": total_items,
                            "processed": processed,
                            "recovered_completed": recovered_completed,
                            "retryable": retryable,
                            "already_good": already_good,
                            "current_batch_item_id": int(item["id"]),
                            "status": "ready_for_retry",
                        },
                    )
            elif source_exists and destination_exists:
                blocking.append(f"item:{item['id']}:source_and_destination_both_exist")
                con.execute(
                    "UPDATE batch_items SET status = 'manual_review', error_code = ?, error_message = ? WHERE id = ?",
                    ("source_and_destination_both_exist", "Both copies exist; manual decision required.", item["id"]),
                )
                if should_emit_progress:
                    _emit_progress(
                        progress_callback,
                        {
                            "operation": progress_operation,
                            "phase": "reconciling",
                            "batch_id": batch_id,
                            "total": total_items,
                            "processed": processed,
                            "recovered_completed": recovered_completed,
                            "retryable": retryable,
                            "already_good": already_good,
                            "current_batch_item_id": int(item["id"]),
                            "status": "manual_review",
                        },
                    )
            else:
                blocking.append(f"item:{item['id']}:source_and_destination_missing")
                con.execute(
                    "UPDATE batch_items SET status = 'manual_review', error_code = ?, error_message = ? WHERE id = ?",
                    ("source_and_destination_missing", "Neither copy exists; restore from backup may be required.", item["id"]),
                )
                if should_emit_progress:
                    _emit_progress(
                        progress_callback,
                        {
                            "operation": progress_operation,
                            "phase": "reconciling",
                            "batch_id": batch_id,
                            "total": total_items,
                            "processed": processed,
                            "recovered_completed": recovered_completed,
                            "retryable": retryable,
                            "already_good": already_good,
                            "current_batch_item_id": int(item["id"]),
                            "status": "manual_review",
                        },
                    )
            if processed % MUTATION_COMMIT_INTERVAL == 0:
                con.commit()
        con.commit()
    if blocking:
        batch_status = "needs_manual_review"
    elif retryable:
        batch_status = "resume_ready"
    else:
        batch_status = "reconciled"
    con.execute(
        "UPDATE execution_batches SET status = ?, summary_json = ? WHERE id = ?",
        (
            batch_status,
            _json(
                {
                    "recovered_completed": recovered_completed,
                    "retryable": retryable,
                    "already_good": already_good,
                    "blocking_reasons": blocking,
                }
            ),
            batch_id,
        ),
    )
    con.commit()
    _emit_progress(
        progress_callback,
        {
            "operation": progress_operation,
            "phase": "completed" if not blocking else "completed_with_blockers",
            "batch_id": batch_id,
            "total": total_items,
            "processed": processed,
            "recovered_completed": recovered_completed,
            "retryable": retryable,
            "already_good": already_good,
            "blocking_count": len(blocking),
        },
    )
    return {
        "batch_id": batch_id,
        "reconciled": not blocking,
        "status": batch_status,
        "recovered_completed": recovered_completed,
        "retryable_count": retryable,
        "already_good_count": already_good,
        "blocking_reasons": blocking,
        "details": details,
    }


def resume_batch(
    con: sqlite3.Connection,
    batch_id: int,
    *,
    execute_approved: bool = False,
    verify_hashes: bool = True,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    with _operation_lock(con, "filesystem-mutation", details={"operation": "resume_batch", "batch_id": batch_id}):
        batch = con.execute("SELECT * FROM execution_batches WHERE id = ?", (batch_id,)).fetchone()
        if batch is None:
            raise ValueError(f"batch not found: {batch_id}")
        if not execute_approved:
            return {
                "batch_id": batch_id,
                "resumed": False,
                "blocking_reasons": ["runtime_resume_confirmation_missing"],
                "destructive_action_performed": False,
            }
        reconciliation = reconcile_batch(con, batch_id, progress_callback=progress_callback, progress_operation="resume_batch_reconcile")
        if reconciliation.get("blocking_reasons"):
            return {
                "batch_id": batch_id,
                "resumed": False,
                "reconciliation": reconciliation,
                "blocking_reasons": reconciliation["blocking_reasons"],
                "destructive_action_performed": False,
            }
        if reconciliation.get("retryable_count", 0) <= 0:
            return {
                "batch_id": batch_id,
                "resumed": False,
                "reconciliation": reconciliation,
                "blocking_reasons": ["no_retryable_items"],
                "destructive_action_performed": False,
            }
        execution = _execute_plan_unlocked(
            con,
            int(batch["plan_id"]),
            execute_approved=True,
            verify_hashes=verify_hashes,
            progress_callback=progress_callback,
            progress_operation="resume_batch",
        )
        return {
            "batch_id": batch_id,
            "resumed": bool(execution.get("executed")),
            "reconciliation": reconciliation,
            "execution": execution,
            "destructive_action_performed": bool(execution.get("destructive_action_performed")),
        }
