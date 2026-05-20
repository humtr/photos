from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .store import DEFAULT_PAGE_SIZE, PhotoStore


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
        self.store = PhotoStore(db_path)
        self.store.init_schema()
        self.store.set_app_state("source_root", source_root)
        self.store.set_app_state("archive_root", archive_root)
        if not self.store.get_app_state("theme_preset"):
            self.store.set_app_state("theme_preset", "default")
        self.selection = FolderSelectionModel(self.store.fetch_folder_nodes())

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

    def run_plan(self) -> dict[str, Any]:
        return {
            "ok": True,
            "summary": {
                "included_folder_count": len(self.selection.included_paths()),
                "excluded_folder_count": len(self.selection.excluded_paths()),
                "partial_folder_count": len(self.selection.partial_paths()),
            },
        }

    def run_dry_run(self) -> dict[str, Any]:
        missing_selection = len(self.selection.included_paths()) == 0
        error_count = 1 if missing_selection else 0
        blocking = ["no_selected_folders"] if missing_selection else []
        result = {
            "error_count": error_count,
            "execute_allowed": error_count == 0,
            "blocking_reasons": blocking,
            "batch_summaries": [],
            "capacity_checks": [],
        }
        self.store.conn.execute(
            """
            INSERT INTO dry_run_reports(error_count, execute_allowed, blocking_reasons_json, summary_json, created_at)
            VALUES(?, ?, ?, ?, datetime('now'))
            """,
            (
                error_count,
                1 if result["execute_allowed"] else 0,
                json.dumps(blocking, ensure_ascii=True),
                json.dumps(result, ensure_ascii=True),
            ),
        )
        self.store.conn.commit()
        return result

    def can_execute(self) -> tuple[bool, list[str]]:
        row = self.store.conn.execute(
            """
            SELECT error_count, execute_allowed, blocking_reasons_json
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
        return True, []

    def run_execute(self, execute_approved: bool) -> dict[str, Any]:
        allowed, reasons = self.can_execute()
        if not execute_approved:
            return {"ok": False, "errors": [{"code": "approval_required"}]}
        if not allowed:
            return {"ok": False, "errors": [{"code": "dry_run_blocked", "reasons": reasons}]}
        return {
            "ok": True,
            "summary": {"status": "scaffold_only", "message": "Execution wiring ready"},
        }

    def export_packets(self, output_dir: str | Path) -> dict[str, Any]:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        packet_path = out / "folder_packet.json"
        packet_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "review_type": "folder_semantic_review",
                    "items": [],
                },
                ensure_ascii=True,
                indent=2,
            ),
            encoding="utf-8",
        )
        return {"ok": True, "path": str(packet_path)}

    def import_review(self, input_path: str | Path) -> dict[str, Any]:
        path = Path(input_path)
        if not path.exists():
            return {"ok": False, "errors": [{"code": "not_found", "path": str(path)}]}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"ok": False, "errors": [{"code": "invalid_json"}]}
        return {
            "ok": True,
            "review_type": payload.get("review_type"),
            "item_count": len(payload.get("items", [])),
        }

    def smoke(self) -> dict[str, Any]:
        roots = self.get_roots()
        return {
            "ok": True,
            "source_root": roots["source_root"],
            "archive_root": roots["archive_root"],
            "media_total": self.store.count_media_rows(),
        }
