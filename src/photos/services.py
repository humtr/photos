from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .approvals import approve_plan_execute
from .duplicates import analyze_duplicates
from .execution import dry_run, execute_plan
from .folder_packets import export_folder_packets
from .llm_review import import_review as import_folder_review
from .metadata_audit import audit_dates
from .place import enrich_places
from .planning import build_plan
from .reports import summarize
from .scan import run_scan
from .schemas import utc_now_iso
from .store import DEFAULT_PAGE_SIZE, PhotoStore, get_or_create_scan_root, latest_scan_root


@dataclass
class TriStateNode:
    path: str
    parent_path: str | None
    state: int = 0  # 0: unchecked, 1: partial, 2: checked


class FolderSelectionModel:
    def __init__(self, nodes: list[dict[str, Any]]) -> None:
        self.nodes: dict[str, TriStateNode] = {}
        self.children: dict[str, list[str]] = {}
        for row in nodes:
            path = str(row["path"])
            parent_path = row.get("parent_path")
            parent_path = str(parent_path) if parent_path else None
            self.nodes[path] = TriStateNode(path=path, parent_path=parent_path)
            if parent_path:
                self.children.setdefault(parent_path, []).append(path)

    def set_state(self, path: str, checked: bool) -> None:
        value = 2 if checked else 0
        self._set_down(path, value)
        self._refresh_up(path)

    def _set_down(self, path: str, value: int) -> None:
        node = self.nodes.get(path)
        if node is None:
            return
        node.state = value
        for child in self.children.get(path, []):
            self._set_down(child, value)

    def _refresh_up(self, path: str) -> None:
        node = self.nodes.get(path)
        if node is None or node.parent_path is None:
            return
        parent = self.nodes[node.parent_path]
        child_states = [self.nodes[c].state for c in self.children.get(parent.path, [])]
        if not child_states:
            return
        if all(s == 2 for s in child_states):
            parent.state = 2
        elif all(s == 0 for s in child_states):
            parent.state = 0
        else:
            parent.state = 1
        self._refresh_up(parent.path)

    def included_paths(self) -> list[str]:
        return sorted([p for p, n in self.nodes.items() if n.state == 2])

    def excluded_paths(self) -> list[str]:
        return sorted([p for p, n in self.nodes.items() if n.state == 0])

    def partial_paths(self) -> list[str]:
        return sorted([p for p, n in self.nodes.items() if n.state == 1])


class PhotoOrganizerService:
    def __init__(
        self,
        db_path: str | Path,
        source_root: str = r"D:\\",
        archive_root: str = r"D:\\PICTURES",
    ) -> None:
        self.db_path = Path(db_path)
        self.store = PhotoStore(db_path)
        self.store.init_schema()
        self.store.set_app_state("source_root", source_root)
        self.store.set_app_state("archive_root", archive_root)
        if not self.store.get_app_state("theme_preset"):
            self.store.set_app_state("theme_preset", "default")
        self.selection = FolderSelectionModel(self.store.fetch_folder_nodes())
        self.last_command: str = "init"
        self.last_failure_reason: str = ""
        self.resume_state: str = "ready"

    def close(self) -> None:
        self.store.close()

    def set_roots(self, source_root: str, archive_root: str) -> None:
        self.store.set_app_state("source_root", source_root)
        self.store.set_app_state("archive_root", archive_root)

    def get_roots(self) -> dict[str, str]:
        return {
            "source_root": self.store.get_app_state("source_root", r"D:\\") or r"D:\\",
            "archive_root": self.store.get_app_state("archive_root", r"D:\\PICTURES")
            or r"D:\\PICTURES",
        }

    def refresh_selection_model(self) -> None:
        self.selection = FolderSelectionModel(self.store.fetch_folder_nodes())

    def run_init(self) -> dict[str, Any]:
        self.store.init_schema()
        self._mark_ok("init")
        return {"ok": True, "summary": {"initialized": True}}

    def _active_scan_root_id(self) -> int:
        row = latest_scan_root(self.store.conn)
        if row is None:
            raise RuntimeError("no active scan root; run scan first")
        return int(row["id"])

    def _latest_plan_id(self) -> int:
        return self.store.store.latest_plan_id()

    def _mark_ok(self, command: str, resume_state: str = "ready") -> None:
        self.last_command = command
        self.last_failure_reason = ""
        self.resume_state = resume_state

    def _mark_error(self, command: str, exc: Exception) -> dict[str, Any]:
        self.last_command = command
        self.last_failure_reason = str(exc)
        self.resume_state = "blocked"
        return {"ok": False, "errors": [{"code": "service_error", "message": str(exc)}]}

    def set_theme_preset(self, theme_preset: str) -> None:
        self.store.set_app_state("theme_preset", theme_preset)

    def get_theme_preset(self, default: str = "default") -> str:
        return self.store.get_app_state("theme_preset", default) or default

    def load_folder_panels(self) -> dict[str, list[str]]:
        return {
            "all": sorted(self.selection.nodes.keys()),
            "included": self.selection.included_paths(),
            "excluded": self.selection.excluded_paths(),
            "partial": self.selection.partial_paths(),
        }

    def set_folder_checked(self, path: str, checked: bool) -> dict[str, list[str]]:
        self.selection.set_state(path, checked)
        return self.load_folder_panels()

    def page_media(self, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE) -> dict[str, Any]:
        rows, total = self.store.fetch_media_page(page=page, page_size=page_size)
        return {
            "page": page,
            "page_size": page_size,
            "total": total,
            "rows": rows,
        }

    def run_scan(self) -> dict[str, Any]:
        command = "scan"
        try:
            roots = self.get_roots()
            scan_root_id = get_or_create_scan_root(
                self.store.conn,
                roots["source_root"],
                roots["archive_root"],
                utc_now_iso(),
            )
            result = run_scan(self.store.conn, scan_root_id, Path(roots["source_root"]))
            self.refresh_selection_model()
            summary = {
                "scan_root_id": scan_root_id,
                "scan_run_id": result.scan_run_id,
                "folder_count": result.folder_count,
                "file_count": result.file_count,
                "error_count": result.error_count,
            }
            self._mark_ok(command, "scan_complete")
            return {"ok": result.error_count == 0, "summary": summary}
        except Exception as exc:
            return self._mark_error(command, exc)

    def run_summarize(self) -> dict[str, Any]:
        command = "summarize"
        try:
            summary = summarize(self.store.conn, self._active_scan_root_id())
            self._mark_ok(command)
            return {"ok": True, "summary": summary}
        except Exception as exc:
            return self._mark_error(command, exc)

    def run_enrich_places(self, gps_mode: str = "summary") -> dict[str, Any]:
        command = "enrich-places"
        try:
            summary = enrich_places(self.store.conn, self._active_scan_root_id(), gps_mode)
            self._mark_ok(command)
            return {"ok": True, "summary": summary}
        except Exception as exc:
            return self._mark_error(command, exc)

    def run_analyze_duplicates(self) -> dict[str, Any]:
        command = "analyze-duplicates"
        try:
            summary = analyze_duplicates(self.store.conn, self._active_scan_root_id())
            self._mark_ok(command)
            return {"ok": True, "summary": summary}
        except Exception as exc:
            return self._mark_error(command, exc)

    def run_audit_dates(self) -> dict[str, Any]:
        command = "audit-dates"
        try:
            summary = audit_dates(self.store.conn, self._active_scan_root_id())
            self._mark_ok(command)
            return {"ok": True, "summary": summary}
        except Exception as exc:
            return self._mark_error(command, exc)

    def run_plan(self) -> dict[str, Any]:
        command = "plan"
        try:
            roots = self.get_roots()
            scan_root_id = self._active_scan_root_id()
            self.store.conn.execute("UPDATE scan_roots SET archive_root=? WHERE id=?", (roots["archive_root"], scan_root_id))
            self.store.conn.commit()
            plan_id = build_plan(self.store.store, scan_root_id, strategy="hybrid")
            self._mark_ok(command, "plan_ready")
            return {
                "ok": True,
                "summary": {
                    "plan_id": plan_id,
                    "strategy": "hybrid",
                    "included_folder_count": len(self.selection.included_paths()),
                    "excluded_folder_count": len(self.selection.excluded_paths()),
                    "partial_folder_count": len(self.selection.partial_paths()),
                },
            }
        except Exception as exc:
            return self._mark_error(command, exc)

    def approve_latest_plan_execute(self, note: str = "gui execute approval") -> dict[str, Any]:
        command = "approve-execute"
        try:
            plan_id = self._latest_plan_id()
            approval_id = approve_plan_execute(self.store.store, plan_id, note=note)
            self._mark_ok(command, "approval_recorded")
            return {"ok": True, "summary": {"plan_id": plan_id, "approval_id": approval_id}}
        except Exception as exc:
            return self._mark_error(command, exc)

    def run_dry_run(self) -> dict[str, Any]:
        command = "dry-run"
        try:
            result = dry_run(self.store.store, self._latest_plan_id())
            payload = result.to_dict()
            self.store.conn.execute(
                """
                INSERT INTO dry_run_reports(error_count, execute_allowed, blocking_reasons_json, summary_json, created_at)
                VALUES(?, ?, ?, ?, datetime('now'))
                """,
                (
                    int(payload["error_count"]),
                    1 if payload["execute_allowed"] else 0,
                    json.dumps(payload["blocking_reasons"], ensure_ascii=True),
                    json.dumps(payload, ensure_ascii=True),
                ),
            )
            self.store.conn.commit()
            self._mark_ok(command, "dry_run_passed" if payload["execute_allowed"] else "dry_run_blocked")
            return payload
        except Exception as exc:
            error = self._mark_error(command, exc)
            error.update({"error_count": 1, "execute_allowed": False, "blocking_reasons": [str(exc)]})
            return error

    def can_execute(self) -> tuple[bool, list[str]]:
        row = self.store.conn.execute(
            """
            SELECT error_count, execute_allowed, blocking_reasons_json, summary_json
            FROM dry_run_reports
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return False, ["dry_run_not_run"]
        if int(row["error_count"]) > 0 or int(row["execute_allowed"]) == 0:
            try:
                reasons = json.loads(row["blocking_reasons_json"])
            except json.JSONDecodeError:
                reasons = ["dry_run_blocked"]
            return False, reasons
        try:
            summary = json.loads(str(row["summary_json"]))
        except json.JSONDecodeError:
            return False, ["dry_run_summary_invalid"]
        plan_id = summary.get("plan_id")
        if not plan_id:
            return False, ["dry_run_plan_missing"]
        if not self.store.store.is_approved("execute", "plan", int(plan_id)):
            return False, ["missing_execute_approval"]
        return True, []

    def run_execute(self, execute_approved: bool) -> dict[str, Any]:
        allowed, reasons = self.can_execute()
        if not execute_approved:
            return {"ok": False, "errors": [{"code": "approval_required"}]}
        if not allowed:
            return {"ok": False, "errors": [{"code": "dry_run_blocked", "reasons": reasons}]}
        command = "execute"
        try:
            result = execute_plan(
                self.store.store,
                plan_id=self._latest_plan_id(),
                execute_approved_flag=True,
                manifest_dir=self.db_path.parent / "manifests",
                reports_dir=self.db_path.parent / "reports",
            )
            self._mark_ok(command, result.next_safe_action)
            return {"ok": True, "summary": result.to_dict()}
        except Exception as exc:
            return self._mark_error(command, exc)

    def export_packets(self, output_dir: str | Path) -> dict[str, Any]:
        command = "export-folder-packets"
        try:
            result = export_folder_packets(self.store.conn, self._active_scan_root_id(), Path(output_dir), "summary")
            self._mark_ok(command)
            return {"ok": True, "summary": result, "path": result["index_path"]}
        except Exception as exc:
            return self._mark_error(command, exc)

    def import_review(self, input_path: str | Path) -> dict[str, Any]:
        command = "import-folder-review"
        try:
            root = latest_scan_root(self.store.conn)
            if root is None:
                raise RuntimeError("no active scan root; run scan first")
            summary = import_folder_review(
                self.store.conn,
                int(root["id"]),
                Path(input_path),
                Path(str(root["source_root"])),
            )
            ok = int(summary.get("rejected", 0)) == 0
            if ok:
                self._mark_ok(command)
            else:
                self.last_command = command
                self.last_failure_reason = json.dumps(summary.get("errors", []), ensure_ascii=True)
                self.resume_state = "review_import_errors"
            return {"ok": ok, "summary": summary, "errors": summary.get("errors", [])}
        except Exception as exc:
            return self._mark_error(command, exc)

    def workflow_state(self) -> dict[str, str]:
        return {
            "last_command": self.last_command,
            "failure_reason": self.last_failure_reason,
            "resume_state": self.resume_state,
        }

    def smoke(self) -> dict[str, Any]:
        roots = self.get_roots()
        return {
            "ok": True,
            "source_root": roots["source_root"],
            "archive_root": roots["archive_root"],
            "media_total": self.store.count_media_rows(),
        }
