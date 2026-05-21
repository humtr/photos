from __future__ import annotations

import os
import shutil
from pathlib import Path

from .approvals import is_plan_execute_approved
from .manifest import write_manifest_atomic
from .schemas import DryRunResult, ExecuteResult, utc_now_iso
from .store import Store
from .utils import file_sha256, is_subpath, json_dumps, normalize_case_path
from .volume import free_space_bytes, get_volume_identity, is_same_volume

MAX_WINDOWS_PATH_CHARS = 260
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
EXECUTABLE_ACTION_TYPES = {"move", "rename_move", "metadata_override"}


def _plan_actions_for_execution(store: Store, plan_id: int) -> list:
    return [r for r in store.list_plan_actions(plan_id) if r["action_type"] in EXECUTABLE_ACTION_TYPES]


def _source_snapshot_ok(row) -> bool:
    src = Path(row["source_path"])
    if not src.exists():
        return False
    st = src.stat()
    return int(st.st_size) == int(row["expected_size"]) and int(st.st_mtime_ns) == int(row["expected_mtime_ns"])


def _is_path_too_long(path: Path) -> bool:
    return len(str(path.absolute())) >= MAX_WINDOWS_PATH_CHARS


def _is_reparse_point(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        attrs = getattr(path.lstat(), "st_file_attributes", 0)
        return bool(attrs & FILE_ATTRIBUTE_REPARSE_POINT)
    except OSError:
        return False


def _has_reparse_risk(path: Path, trusted_root: Path | None = None) -> bool:
    candidates: list[Path] = []
    current = path if path.exists() else path.parent
    while True:
        candidates.append(current)
        if trusted_root is not None and normalize_case_path(str(current)) == normalize_case_path(str(trusted_root)):
            break
        parent = current.parent
        if parent == current:
            break
        current = parent
    return any(_is_reparse_point(candidate) for candidate in candidates if candidate.exists())


def _preflight_action(row, archive_root: Path) -> list[str]:
    src = Path(row["source_path"])
    dst = Path(row["destination_path"])
    reasons: list[str] = []

    if _is_path_too_long(src):
        reasons.append(f"path_too_long:{src}")
    if _is_path_too_long(dst):
        reasons.append(f"path_too_long:{dst}")
    if not is_subpath(dst, archive_root):
        reasons.append(f"root_escape:{dst}")
    if dst.exists():
        reasons.append(f"destination_exists:{dst}")
    if not src.exists():
        reasons.append(f"source_missing:{src}")
    elif not _source_snapshot_ok(row):
        reasons.append(f"source_changed:{src}")
    if _has_reparse_risk(src) or _has_reparse_risk(dst, archive_root) or _is_reparse_point(archive_root):
        reasons.append("reparse_point_risk")

    return reasons


def dry_run(store: Store, plan_id: int, reserve_bytes: int = 0) -> DryRunResult:
    plan = store.get_plan(plan_id)
    archive_root = Path(plan["archive_root"])
    actions = _plan_actions_for_execution(store, plan_id)

    result = DryRunResult(plan_id=plan_id)
    if not is_plan_execute_approved(store, plan_id):
        result.blocking_reasons.append("missing_execute_approval")

    ci_destinations: set[str] = set()
    total_bytes = 0
    source_volume = ""
    archive_volume = get_volume_identity(archive_root)

    for row in actions:
        src = Path(row["source_path"])
        dst = Path(row["destination_path"])
        total_bytes += int(row["expected_size"])

        result.blocking_reasons.extend(_preflight_action(row, archive_root))

        dst_ci = normalize_case_path(str(dst))
        if dst_ci in ci_destinations:
            result.blocking_reasons.append(f"case_insensitive_collision:{dst}")
        ci_destinations.add(dst_ci)

        current_source_volume = get_volume_identity(src)
        if not source_volume:
            source_volume = current_source_volume
        if current_source_volume != source_volume:
            result.blocking_reasons.append("mixed_source_volumes_not_supported_in_single_batch")

    same_volume = bool(source_volume and source_volume == archive_volume)
    result.transfer_method = "same_volume_move" if same_volume else "copy_verify_cleanup"

    if not same_volume:
        free_now = free_space_bytes(archive_root)
        needed = total_bytes + reserve_bytes
        capacity_ok = free_now >= needed
        result.capacity_checks.append(
            {
                "archive_root": str(archive_root),
                "free_bytes": free_now,
                "reserve_bytes": reserve_bytes,
                "estimated_bytes": total_bytes,
                "required_bytes": needed,
                "ok": capacity_ok,
            }
        )
        if not capacity_ok:
            result.blocking_reasons.append("insufficient_capacity_for_copy_verify_cleanup")

    result.error_count = len(result.blocking_reasons)
    result.execute_allowed = result.error_count == 0
    result.batch_summaries.append(
        {
            "plan_id": plan_id,
            "action_count": len(actions),
            "estimated_bytes": total_bytes,
            "transfer_method": result.transfer_method,
        }
    )
    return result


def execute_plan(
    store: Store,
    plan_id: int,
    execute_approved_flag: bool,
    manifest_dir: Path,
    reports_dir: Path,
    reserve_bytes: int = 0,
) -> ExecuteResult:
    if not execute_approved_flag:
        raise ValueError("execute requires --execute-approved")

    dry = dry_run(store, plan_id, reserve_bytes=reserve_bytes)
    if not dry.execute_allowed:
        raise ValueError(f"dry-run blocked execution: {','.join(dry.blocking_reasons)}")

    actions = _plan_actions_for_execution(store, plan_id)
    total_bytes = sum(int(r["expected_size"]) for r in actions)
    batch_id = store.create_batch(plan_id, dry.transfer_method, total_bytes, "running", {"dry_run": dry.to_dict()})
    store.insert_batch_items(
        [(batch_id, int(r["id"]), r["source_path"], r["destination_path"], "pending", None, None) for r in actions]
    )

    failed_count = 0
    held_count = 0
    committed_count = 0
    skipped_count = 0
    stop_destructive_actions = False
    manifest_items: list[dict] = []
    started_at = dry.to_dict().get("started_at", None)
    plan_row = store.get_plan(plan_id)
    scan_root = store.get_scan_root(int(plan_row["scan_root_id"]))
    source_root = str(scan_root["source_root"])
    archive_root = str(plan_row["archive_root"])
    scan_run_row = store.conn.execute(
        "SELECT id FROM scan_runs WHERE scan_root_id=? ORDER BY id DESC LIMIT 1",
        (int(plan_row["scan_root_id"]),),
    ).fetchone()
    scan_run_id = int(scan_run_row["id"]) if scan_run_row else None

    for item in store.list_batch_items(batch_id):
        src = Path(item["source_path"])
        dst = Path(item["destination_path"])
        action = store.conn.execute("select * from plan_actions where id=?", (int(item["plan_action_id"]),)).fetchone()
        source_existed_before = src.exists()
        pre_size = int(src.stat().st_size) if source_existed_before else None
        pre_mtime = int(src.stat().st_mtime_ns) if source_existed_before else None

        if stop_destructive_actions:
            store.update_batch_item(
                int(item["id"]),
                "skipped",
                "batch_halted_due_prior_safety_or_verification_issue",
                "batch halted after previous safety or verification issue",
            )
            skipped_count += 1
            manifest_items.append(
                {
                    "plan_action_id": int(item["plan_action_id"]),
                    "source_path": str(src),
                    "destination_path": str(dst),
                    "action_type": str(action["action_type"]),
                    "expected_size": int(action["expected_size"]),
                    "expected_mtime_ns": int(action["expected_mtime_ns"]),
                    "precheck_size": pre_size,
                    "precheck_mtime_ns": pre_mtime,
                    "postcheck_size": None,
                    "postcheck_mtime_ns": None,
                    "source_existed_before": source_existed_before,
                    "source_exists_after": src.exists(),
                    "destination_exists_after": dst.exists(),
                    "verification_status": "skipped",
                    "status": "skipped",
                    "error_code": "batch_halted_due_prior_safety_or_verification_issue",
                    "error_message": "batch halted after previous safety or verification issue",
                }
            )
            continue

        preflight_reasons = _preflight_action(action, Path(archive_root))
        if preflight_reasons:
            error_code = preflight_reasons[0].split(":", 1)[0]
            error_message = "safety preflight failed before execute: " + ",".join(preflight_reasons)
            store.update_batch_item(int(item["id"]), "held", error_code, error_message)
            held_count += 1
            stop_destructive_actions = True
            manifest_items.append(
                {
                    "plan_action_id": int(item["plan_action_id"]),
                    "source_path": str(src),
                    "destination_path": str(dst),
                    "action_type": str(action["action_type"]),
                    "expected_size": int(action["expected_size"]),
                    "expected_mtime_ns": int(action["expected_mtime_ns"]),
                    "precheck_size": pre_size,
                    "precheck_mtime_ns": pre_mtime,
                    "postcheck_size": None,
                    "postcheck_mtime_ns": None,
                    "source_existed_before": source_existed_before,
                    "source_exists_after": src.exists(),
                    "destination_exists_after": dst.exists(),
                    "verification_status": error_code,
                    "status": "held",
                    "error_code": error_code,
                    "error_message": error_message,
                }
            )
            continue

        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            if dry.transfer_method == "same_volume_move" and is_same_volume(src, dst.parent):
                os.replace(src, dst)
                op_status = "moved"
            else:
                shutil.copy2(src, dst)
                if src.stat().st_size != dst.stat().st_size:
                    raise RuntimeError("size_mismatch_after_copy")
                if file_sha256(src) != file_sha256(dst):
                    raise RuntimeError("hash_mismatch_after_copy")
                op_status = "copied_source_retained"

            st = dst.stat()
            store.update_batch_item(int(item["id"]), "verified")
            store.add_transfer_verification(
                int(item["id"]),
                int(st.st_size),
                int(st.st_mtime_ns),
                "verified",
                {"op_status": op_status},
            )
            committed_count += 1
            manifest_items.append(
                {
                    "plan_action_id": int(item["plan_action_id"]),
                    "source_path": str(src),
                    "destination_path": str(dst),
                    "action_type": str(action["action_type"]),
                    "expected_size": int(action["expected_size"]),
                    "expected_mtime_ns": int(action["expected_mtime_ns"]),
                    "precheck_size": pre_size,
                    "precheck_mtime_ns": pre_mtime,
                    "postcheck_size": int(st.st_size),
                    "postcheck_mtime_ns": int(st.st_mtime_ns),
                    "source_existed_before": source_existed_before,
                    "source_exists_after": src.exists(),
                    "destination_exists_after": dst.exists(),
                    "verification_status": "verified",
                    "status": "verified",
                    "error_code": None,
                    "error_message": None,
                }
            )
        except Exception as exc:
            store.update_batch_item(int(item["id"]), "failed", "execution_error", str(exc))
            failed_count += 1
            stop_destructive_actions = True
            manifest_items.append(
                {
                    "plan_action_id": int(item["plan_action_id"]),
                    "source_path": str(src),
                    "destination_path": str(dst),
                    "action_type": str(action["action_type"]),
                    "expected_size": int(action["expected_size"]),
                    "expected_mtime_ns": int(action["expected_mtime_ns"]),
                    "precheck_size": pre_size,
                    "precheck_mtime_ns": pre_mtime,
                    "postcheck_size": int(dst.stat().st_size) if dst.exists() else None,
                    "postcheck_mtime_ns": int(dst.stat().st_mtime_ns) if dst.exists() else None,
                    "source_existed_before": source_existed_before,
                    "source_exists_after": src.exists(),
                    "destination_exists_after": dst.exists(),
                    "verification_status": "failed",
                    "status": "failed",
                    "error_code": "execution_error",
                    "error_message": str(exc),
                }
            )

    batch_status = "committed" if failed_count == 0 and held_count == 0 else "failed"
    manifest_payload = {
        "schema_version": 1,
        "manifest_id": f"batch-{batch_id}",
        "batch_id": batch_id,
        "plan_id": plan_id,
        "scan_run_id": scan_run_id,
        "source_root": source_root,
        "archive_root": archive_root,
        "transfer_method": dry.transfer_method,
        "source_volume": get_volume_identity(Path(actions[0]["source_path"])) if actions else "",
        "archive_volume": get_volume_identity(Path(archive_root)),
        "dry_run_report": dry.to_dict(),
        "approval_ids": [],
        "started_at": utc_now_iso() if started_at is None else started_at,
        "finished_at": utc_now_iso(),
        "command": "photos execute --plan latest --batch latest --execute-approved",
        "operator_context": "local-cli",
        "item_count": len(manifest_items),
        "total_expected_bytes": total_bytes,
        "items": manifest_items,
        "summary": {
            "committed_count": committed_count,
            "failed_count": failed_count,
            "held_count": held_count,
            "skipped_count": skipped_count,
        },
    }
    manifest_path = manifest_dir / f"batch_{batch_id}.manifest.json"
    try:
        final_manifest_path, manifest_sha = write_manifest_atomic(manifest_path, manifest_payload)
    except Exception:
        store.finish_batch(
            batch_id,
            "failed",
            {"committed_count": committed_count, "failed_count": failed_count, "held_count": held_count, "skipped_count": skipped_count},
        )
        raise
    store.add_manifest(batch_id, final_manifest_path, manifest_sha, len(manifest_items), total_bytes)

    rollback_payload = {
        "schema_version": 1,
        "batch_id": batch_id,
        "manifest_path": final_manifest_path,
        "manifest_sha256": manifest_sha,
        "automatic_rollback_supported": False,
        "notes": "manual rollback only in v2",
        "successful_items": [x for x in manifest_items if x["status"] == "verified"],
        "failed_items": [x for x in manifest_items if x["status"] == "failed"],
        "held_items": [x for x in manifest_items if x["status"] == "held"],
        "skipped_items": [x for x in manifest_items if x["status"] == "skipped"],
    }
    rollback_path = reports_dir / f"batch_{batch_id}.rollback.json"
    rollback_path.parent.mkdir(parents=True, exist_ok=True)
    rollback_path.write_text(json_dumps(rollback_payload), encoding="utf-8")

    store.add_report("rollback_reference", str(rollback_path), file_sha256(rollback_path), {"batch_id": batch_id})
    store.finish_batch(
        batch_id,
        batch_status,
        {"committed_count": committed_count, "failed_count": failed_count, "held_count": held_count},
    )

    next_safe_action = "complete" if batch_status == "committed" else "review_failures"
    return ExecuteResult(
        plan_id=plan_id,
        batch_id=batch_id,
        transfer_method=dry.transfer_method,
        committed_count=committed_count,
        failed_count=failed_count,
        held_count=held_count,
        manifest_path=final_manifest_path,
        manifest_sha256=manifest_sha,
        next_safe_action=next_safe_action,
    )
