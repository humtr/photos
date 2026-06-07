from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .classification import import_classification_csv
from .contracts import fail, ok
from .date_audit import list_date_audits, refresh_date_audit
from .dry_run import run_media_analysis
from .duplicates import list_duplicate_candidates, refresh_duplicate_candidates
from .execution import (
    approve_plan,
    can_execute,
    create_archive_plan,
    dry_run_plan,
    execute_plan,
    list_batch_items,
    list_execution_batches,
    list_plan_actions,
    list_plans,
    rollback_batch,
    reconcile_batch,
    resume_batch,
    run_integrity_check,
    validate_batch_manifest,
)
from .hashing import compute_missing_hashes, hash_backlog
from .reports import (
    build_management_report,
    write_management_report,
    write_management_report_page,
)
from .review import export_review_package, import_review_decisions, write_decision_manifest
from .scanner import scan_media
from .store import DEFAULT_PAGE_SIZE, PhotoStore


class PhotoOrganizerService:
    """Single backend facade for GUI, CLI, and automation callers.

    Contract rules:
    - Frontend code imports this service, not scanner/database/planning internals.
    - Every method returns the stable ``ok/errors/warnings/next_safe_action`` envelope.
    - Real file movement is available only through approval-gated service methods.
    """

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self.store = PhotoStore(db_path)

    def close(self) -> None:
        self.store.close()

    def _reopen_store(self) -> None:
        db_path = self.store.db_path
        self.store.close()
        self.store = PhotoStore(db_path)

    def __enter__(self) -> "PhotoOrganizerService":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    @property
    def con(self):  # pragma: no cover - thin compatibility affordance.
        return self.store.con

    def health(self) -> dict[str, Any]:
        command = "health"
        try:
            return ok(command, self.store.health(), next_safe_action="select_source_root")
        except Exception as exc:  # pragma: no cover - defensive boundary.
            return fail(command, exc)

    def scan_inventory(
        self,
        root: str | Path,
        *,
        hash_files: bool = False,
        max_hash_files: int | None = None,
    ) -> dict[str, Any]:
        command = "scan_inventory"
        try:
            root_path = Path(root).expanduser()
            if not root_path.exists():
                raise FileNotFoundError(root_path)
            scanned = scan_media(self.store.con, root_path)
            hashed = 0
            if hash_files:
                hashed = compute_missing_hashes(self.store.con, max_files=max_hash_files)
            folder_sync = self.store.sync_folder_nodes(root_path)
            scan_run_id = self.store.record_scan_run(
                scan_root_id=int(folder_sync["scan_root_id"]),
                status="completed",
                file_count=scanned,
                folder_count=int(folder_sync["folder_count"]),
                details={"hash_files": hash_files, "hashed": hashed},
            )
            return ok(
                command,
                {
                    "root": str(root_path.resolve()),
                    "scanned": scanned,
                    "hashed": hashed,
                    "hash_backlog": hash_backlog(self.store.con),
                    "folder_count": int(folder_sync["folder_count"]),
                    "scan_run_id": scan_run_id,
                },
                next_safe_action="review_inventory_or_hash_backlog",
            )
        except Exception as exc:
            return fail(command, exc)

    def analyze(
        self,
        root: str | Path,
        *,
        output_dir: str | Path,
        hash_files: bool = True,
        free_bytes: int | None = None,
        top_folders: int = 20,
        max_review_shortcuts: int = 250,
        max_detail_items: int = 10_000,
        run_name: str = "service_analyze",
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        command = "analyze"
        try:
            output = Path(output_dir)
            try:
                summary = run_media_analysis(
                    root,
                    db_path=self.store.db_path,
                    output_dir=output,
                    free_bytes=free_bytes,
                    hash_files=hash_files,
                top_folders=top_folders,
                max_review_shortcuts=max_review_shortcuts,
                max_detail_items=max_detail_items,
                run_name=run_name,
                progress_callback=progress_callback,
            )
            finally:
                # Analysis helpers use a separate connection. Reopen even after
                # failure so later service calls see the effective DB state.
                self._reopen_store()
            folder_sync = self.store.sync_folder_nodes(root)
            duplicates = refresh_duplicate_candidates(self.store.con)
            date_audit = refresh_date_audit(self.store.con)
            summary.update(
                {
                    "folder_count": folder_sync["folder_count"],
                    "duplicate_candidates": duplicates,
                    "date_audit": date_audit,
                }
            )
            return ok(command, summary, next_safe_action="review_candidates_and_dates")
        except Exception as exc:
            return fail(command, exc)

    def sample_dry_run(
        self,
        root: str | Path,
        *,
        output_dir: str | Path,
        free_bytes: int | None = None,
        hash_files: bool = True,
        top_folders: int = 20,
        max_review_shortcuts: int = 250,
        max_detail_items: int = 10_000,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        command = "sample_dry_run"
        try:
            try:
                summary = run_media_analysis(
                    root,
                    db_path=self.store.db_path,
                    output_dir=output_dir,
                    free_bytes=free_bytes,
                    hash_files=hash_files,
                    top_folders=top_folders,
                    max_review_shortcuts=max_review_shortcuts,
                    max_detail_items=max_detail_items,
                    run_name="sample_dry_run",
                    progress_callback=progress_callback,
                )
            finally:
                self._reopen_store()
            return ok(command, summary, next_safe_action="review_dry_run_artifacts")
        except Exception as exc:
            return fail(command, exc)

    def hash_backlog(self) -> dict[str, Any]:
        command = "hash_backlog"
        try:
            return ok(command, hash_backlog(self.store.con), next_safe_action="hash_backlog_if_needed")
        except Exception as exc:
            return fail(command, exc)

    def hash_missing(
        self,
        *,
        max_files: int | None = None,
        commit_interval: int = 100,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        command = "hash_missing"
        try:
            before = hash_backlog(self.store.con)
            hashed = compute_missing_hashes(
                self.store.con,
                max_files=max_files,
                commit_interval=commit_interval,
                progress_callback=progress_callback,
            )
            after = hash_backlog(self.store.con)
            return ok(
                command,
                {"hashed": hashed, "backlog_before": before, "backlog_after": after},
                next_safe_action="refresh_duplicate_candidates",
            )
        except Exception as exc:
            return fail(command, exc)

    def refresh_duplicate_candidates(self) -> dict[str, Any]:
        command = "refresh_duplicate_candidates"
        try:
            return ok(
                command,
                refresh_duplicate_candidates(self.store.con),
                next_safe_action="review_duplicate_candidates",
            )
        except Exception as exc:
            return fail(command, exc)

    def list_duplicate_candidates(
        self,
        *,
        candidate_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        command = "list_duplicate_candidates"
        try:
            return ok(
                command,
                list_duplicate_candidates(
                    self.store.con,
                    candidate_type=candidate_type,
                    limit=limit,
                    offset=offset,
                ),
                next_safe_action="review_duplicate_candidate_detail",
            )
        except Exception as exc:
            return fail(command, exc)

    def refresh_date_audit(self) -> dict[str, Any]:
        command = "refresh_date_audit"
        try:
            return ok(
                command,
                refresh_date_audit(self.store.con),
                next_safe_action="review_date_audit",
            )
        except Exception as exc:
            return fail(command, exc)

    def list_date_audits(self, *, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        command = "list_date_audits"
        try:
            return ok(
                command,
                list_date_audits(self.store.con, limit=limit, offset=offset),
                next_safe_action="review_date_audit_detail",
            )
        except Exception as exc:
            return fail(command, exc)

    def list_media(
        self,
        *,
        page: int = 1,
        page_size: int = 200,
        media_type: str | None = None,
        text: str | None = None,
        order_by: str = "path",
        direction: str = "asc",
    ) -> dict[str, Any]:
        command = "list_media"
        try:
            return ok(
                command,
                self.store.list_media(
                    page=page,
                    page_size=page_size,
                    media_type=media_type,
                    text=text,
                    order_by=order_by,
                    direction="desc" if direction.lower() == "desc" else "asc",
                ),
                next_safe_action="select_items_or_page",
            )
        except Exception as exc:
            return fail(command, exc)

    def folder_tree(
        self,
        root: str | Path | None = None,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> dict[str, Any]:
        command = "folder_tree"
        try:
            return ok(
                command,
                self.store.list_folder_nodes(root, page=page, page_size=page_size),
                next_safe_action="select_folders",
            )
        except Exception as exc:
            return fail(command, exc)

    def management_report(self, *, top_folders: int = 20) -> dict[str, Any]:
        command = "management_report"
        try:
            return ok(
                command,
                build_management_report(self.store.con, top_folders=top_folders),
                next_safe_action="review_report",
            )
        except Exception as exc:
            return fail(command, exc)

    def write_management_report(
        self,
        output_path: str | Path,
        *,
        top_folders: int = 20,
        max_detail_items: int = 10_000,
    ) -> dict[str, Any]:
        command = "write_management_report"
        try:
            report = write_management_report(
                self.store.con,
                output_path,
                top_folders=top_folders,
                max_detail_items=max_detail_items,
            )
            return ok(
                command,
                {
                    "output": str(output_path),
                    "review_queues": report["review_queues"],
                    "report": report,
                },
                next_safe_action="review_report",
            )
        except Exception as exc:
            return fail(command, exc)

    def write_management_report_page(
        self,
        output_path: str | Path,
        *,
        section: str,
        page: int,
        page_size: int = 10_000,
    ) -> dict[str, Any]:
        command = "write_management_report_page"
        try:
            payload = write_management_report_page(
                self.store.con,
                output_path,
                section=section,
                page=page,
                page_size=page_size,
            )
            return ok(
                command,
                {
                    "output": str(output_path),
                    "total_pages": payload["total_pages"],
                    "page": payload,
                },
                next_safe_action="review_report_page",
            )
        except Exception as exc:
            return fail(command, exc)

    def export_review_package(
        self,
        output_dir: str | Path,
        *,
        max_shortcuts_per_queue: int = 250,
    ) -> dict[str, Any]:
        command = "export_review_package"
        try:
            summary = export_review_package(
                self.store.con,
                output_dir,
                max_shortcuts_per_queue=max_shortcuts_per_queue,
            )
            return ok(command, summary, next_safe_action="external_review_then_import_decisions")
        except Exception as exc:
            return fail(command, exc)

    def import_classification_csv(self, csv_path: str | Path) -> dict[str, Any]:
        command = "import_classification_csv"
        try:
            imported = import_classification_csv(self.store.con, csv_path)
            return ok(command, {"imported": imported}, next_safe_action="review_classifications")
        except Exception as exc:
            return fail(command, exc)

    def import_review_decisions(self, csv_path: str | Path) -> dict[str, Any]:
        command = "import_review_decisions"
        try:
            imported = import_review_decisions(self.store.con, csv_path)
            return ok(command, {"imported": imported}, next_safe_action="write_decision_manifest")
        except Exception as exc:
            return fail(command, exc)

    def write_decision_manifest(self, output_path: str | Path) -> dict[str, Any]:
        command = "write_decision_manifest"
        try:
            manifest = write_decision_manifest(self.store.con, output_path)
            return ok(
                command,
                {
                    "output": str(output_path),
                    "candidate_count": manifest["candidate_count"],
                    "manifest": manifest,
                },
                next_safe_action="review_decision_manifest",
            )
        except Exception as exc:
            return fail(command, exc)

    def create_archive_plan(
        self,
        archive_root: str | Path,
        *,
        strategy: str = "date_archive_v1",
        event_threshold: int = 10,
    ) -> dict[str, Any]:
        command = "create_archive_plan"
        try:
            summary = create_archive_plan(
                self.store.con,
                archive_root=archive_root,
                strategy=strategy,
                event_threshold=event_threshold,
            )
            return ok(command, summary, next_safe_action="review_plan_actions")
        except Exception as exc:
            return fail(command, exc)

    def list_plans(self) -> dict[str, Any]:
        command = "list_plans"
        try:
            return ok(command, {"rows": list_plans(self.store.con)}, next_safe_action="select_plan")
        except Exception as exc:
            return fail(command, exc)

    def list_plan_actions(
        self,
        plan_id: int,
        *,
        status: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> dict[str, Any]:
        command = "list_plan_actions"
        try:
            return ok(
                command,
                list_plan_actions(
                    self.store.con,
                    plan_id,
                    status=status,
                    limit=limit,
                    offset=offset,
                ),
                next_safe_action="approve_or_adjust_plan",
            )
        except Exception as exc:
            return fail(command, exc)

    def approve_plan(self, plan_id: int, *, approved: bool, note: str = "") -> dict[str, Any]:
        command = "approve_plan"
        try:
            summary = approve_plan(
                self.store.con,
                plan_id=plan_id,
                approved=approved,
                note=note,
            )
            return ok(command, summary, next_safe_action="dry_run_plan")
        except Exception as exc:
            return fail(command, exc)

    def dry_run_plan(
        self,
        plan_id: int,
        *,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        command = "dry_run_plan"
        try:
            summary = dry_run_plan(self.store.con, plan_id, progress_callback=progress_callback)
            return ok(
                command,
                summary,
                warnings=summary.get("warnings", []),
                next_safe_action="resolve_blockers_or_check_execution_gate",
            )
        except Exception as exc:
            return fail(command, exc)

    def can_execute(self, plan_id: int) -> dict[str, Any]:
        command = "can_execute"
        try:
            summary = can_execute(self.store.con, plan_id)
            return ok(
                command,
                summary,
                warnings=summary.get("warnings", []),
                next_safe_action="execute_plan" if summary.get("can_execute") else "resolve_blockers",
            )
        except Exception as exc:
            return fail(command, exc)

    def execute_plan(
        self,
        plan_id: int,
        *,
        execute_approved: bool = False,
        verify_hashes: bool = True,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        command = "execute_plan"
        try:
            summary = execute_plan(
                self.store.con,
                plan_id,
                execute_approved=execute_approved,
                verify_hashes=verify_hashes,
                progress_callback=progress_callback,
            )
            return ok(
                command,
                summary,
                warnings=[] if summary.get("executed") else summary.get("blocking_reasons", []),
                next_safe_action="review_manifest_or_rollback_reference"
                if summary.get("executed")
                else "resolve_blockers",
            )
        except Exception as exc:
            return fail(command, exc)

    def list_execution_batches(
        self,
        *,
        plan_id: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        command = "list_execution_batches"
        try:
            return ok(
                command,
                list_execution_batches(
                    self.store.con,
                    plan_id=plan_id,
                    limit=limit,
                    offset=offset,
                ),
                next_safe_action="inspect_batch_or_manifest",
            )
        except Exception as exc:
            return fail(command, exc)

    def list_batch_items(
        self,
        batch_id: int,
        *,
        limit: int = 500,
        offset: int = 0,
    ) -> dict[str, Any]:
        command = "list_batch_items"
        try:
            return ok(
                command,
                list_batch_items(self.store.con, batch_id, limit=limit, offset=offset),
                next_safe_action="inspect_item_errors_or_manifest",
            )
        except Exception as exc:
            return fail(command, exc)

    def rollback_batch(
        self,
        batch_id: int,
        *,
        execute_approved: bool = False,
        verify_hashes: bool = True,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        command = "rollback_batch"
        try:
            summary = rollback_batch(
                self.store.con,
                batch_id,
                execute_approved=execute_approved,
                verify_hashes=verify_hashes,
                progress_callback=progress_callback,
            )
            return ok(
                command,
                summary,
                warnings=[] if summary.get("rolled_back") else summary.get("blocking_reasons", []),
                next_safe_action="review_rollback_manifest"
                if summary.get("rolled_back")
                else "resolve_rollback_blockers",
            )
        except Exception as exc:
            return fail(command, exc)

    def validate_batch_manifest(self, batch_id: int, *, verify_files: bool = False) -> dict[str, Any]:
        command = "validate_batch_manifest"
        try:
            summary = validate_batch_manifest(
                self.store.con,
                batch_id,
                verify_files=verify_files,
            )
            return ok(
                command,
                summary,
                warnings=[] if summary.get("valid") else summary.get("errors", []),
                next_safe_action="batch_manifest_validated"
                if summary.get("valid")
                else "inspect_manifest_errors",
            )
        except Exception as exc:
            return fail(command, exc)

    def reconcile_batch(
        self,
        batch_id: int,
        *,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        command = "reconcile_batch"
        try:
            summary = reconcile_batch(self.store.con, batch_id, progress_callback=progress_callback)
            return ok(
                command,
                summary,
                warnings=summary.get("blocking_reasons", []),
                next_safe_action="resume_batch"
                if summary.get("retryable_count", 0) > 0 and not summary.get("blocking_reasons")
                else "inspect_reconciliation",
            )
        except Exception as exc:
            return fail(command, exc)

    def resume_batch(
        self,
        batch_id: int,
        *,
        execute_approved: bool = False,
        verify_hashes: bool = True,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        command = "resume_batch"
        try:
            summary = resume_batch(
                self.store.con,
                batch_id,
                execute_approved=execute_approved,
                verify_hashes=verify_hashes,
                progress_callback=progress_callback,
            )
            return ok(
                command,
                summary,
                warnings=[] if summary.get("resumed") else summary.get("blocking_reasons", []),
                next_safe_action="review_resumed_batch_manifest"
                if summary.get("resumed")
                else "resolve_resume_blockers",
            )
        except Exception as exc:
            return fail(command, exc)

    def integrity_check(self) -> dict[str, Any]:
        command = "integrity_check"
        try:
            summary = run_integrity_check(self.store.con)
            return ok(
                command,
                summary,
                warnings=[] if summary.get("status") == "ok" else ["integrity_attention_required"],
                next_safe_action="continue" if summary.get("status") == "ok" else "inspect_integrity_report",
            )
        except Exception as exc:
            return fail(command, exc)


def service_smoke(
    root: str | Path,
    *,
    db_path: str | Path,
    output_dir: str | Path,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """End-to-end service smoke used by handoff scripts and CI."""

    with PhotoOrganizerService(db_path) as service:
        free_bytes = shutil.disk_usage(
            Path(output_dir).parent if Path(output_dir).parent.exists() else Path.cwd()
        ).free
        analyzed = service.analyze(
            root,
            output_dir=output_dir,
            hash_files=True,
            free_bytes=free_bytes,
            max_review_shortcuts=5,
            progress_callback=progress_callback,
        )
        if not analyzed["ok"]:
            return analyzed
        media = service.list_media(page=1, page_size=10)
        dupes = service.list_duplicate_candidates(limit=10)
        dates = service.list_date_audits(limit=10)
        return ok(
            "service_smoke",
            {
                "analyze": analyzed["data"],
                "media_page": media["data"],
                "duplicate_candidates": dupes["data"],
                "date_audits": dates["data"],
            },
            next_safe_action="service_ready",
        )
