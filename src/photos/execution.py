from __future__ import annotations

import os
import shutil
from pathlib import Path

from .approvals import is_plan_execute_approved
from .manifest import write_manifest_atomic
from .schemas import DryRunResult, ExecuteResult
from .store import Store
from .utils import file_sha256, is_subpath, json_dumps, normalize_case_path
from .volume import free_space_bytes, get_volume_identity, is_same_volume


def _plan_actions_for_execution(store: Store, plan_id: int) -> list:
    return [r for r in store.list_plan_actions(plan_id) if r["action_type"] in {"move", "rename_move"}]


def _source_snapshot_ok(row) -> bool:
    src = Path(row["source_path"])
    if not src.exists():
        return False
    st = src.stat()
    return int(st.st_size) == int(row["expected_size"]) and int(st.st_mtime_ns) == int(row["expected_mtime_ns"])


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

        if not is_subpath(dst, archive_root):
            result.blocking_reasons.append(f"root_escape:{dst}")
            continue

        dst_ci = normalize_case_path(str(dst))
        if dst_ci in ci_destinations:
            result.blocking_reasons.append(f"case_insensitive_collision:{dst}")
        ci_destinations.add(dst_ci)

        if dst.exists():
            result.blocking_reasons.append(f"destination_exists:{dst}")

        if not _source_snapshot_ok(row):
            result.blocking_reasons.append(f"source_changed:{src}")

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
    manifest_items: list[dict] = []

    for item in store.list_batch_items(batch_id):
        src = Path(item["source_path"])
        dst = Path(item["destination_path"])
        if not _source_snapshot_ok(
            store.conn.execute("select * from plan_actions where id=?", (int(item["plan_action_id"]),)).fetchone()
        ):
            store.update_batch_item(int(item["id"]), "held", "source_changed", "source changed before execute")
            held_count += 1
            manifest_items.append(
                {"batch_item_id": int(item["id"]), "status": "held", "source_path": str(src), "destination_path": str(dst)}
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
                src.unlink()
                op_status = "copied"

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
                    "batch_item_id": int(item["id"]),
                    "status": "verified",
                    "source_path": str(src),
                    "destination_path": str(dst),
                    "destination_size": int(st.st_size),
                    "destination_mtime_ns": int(st.st_mtime_ns),
                }
            )
        except Exception as exc:
            store.update_batch_item(int(item["id"]), "failed", "execution_error", str(exc))
            failed_count += 1
            manifest_items.append(
                {
                    "batch_item_id": int(item["id"]),
                    "status": "failed",
                    "source_path": str(src),
                    "destination_path": str(dst),
                    "error": str(exc),
                }
            )

    batch_status = "committed" if failed_count == 0 and held_count == 0 else "failed"
    manifest_payload = {
        "schema_version": 1,
        "manifest_id": f"batch-{batch_id}",
        "batch_id": batch_id,
        "plan_id": plan_id,
        "transfer_method": dry.transfer_method,
        "source_volume_identity": get_volume_identity(Path(actions[0]["source_path"])) if actions else "",
        "archive_volume_identity": get_volume_identity(Path(store.get_plan(plan_id)["archive_root"])),
        "approval_ids": [],
        "items": manifest_items,
        "summary": {"committed_count": committed_count, "failed_count": failed_count, "held_count": held_count},
    }
    manifest_path = manifest_dir / f"batch_{batch_id}.manifest.json"
    final_manifest_path, manifest_sha = write_manifest_atomic(manifest_path, manifest_payload)
    store.add_manifest(batch_id, final_manifest_path, manifest_sha, len(manifest_items), total_bytes)

    rollback_payload = {
        "schema_version": 1,
        "batch_id": batch_id,
        "manifest_path": final_manifest_path,
        "manifest_sha256": manifest_sha,
        "automatic_rollback_supported": False,
        "notes": "manual rollback only in v2",
        "failed_items": [x for x in manifest_items if x["status"] != "verified"],
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
