from __future__ import annotations

import argparse
import json
import re
import os
import subprocess
import sys
from pathlib import Path
import ctypes
from concurrent.futures import Future, ThreadPoolExecutor

from .services import PhotoOrganizerService
from .store import DEFAULT_PAGE_SIZE

try:
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import (
        QApplication,
        QFileDialog,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QComboBox,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QSpinBox,
        QTreeWidget,
        QTreeWidgetItem,
        QVBoxLayout,
        QWidget,
    )
except Exception:  # pragma: no cover - GUI dependency is optional in tests
    QApplication = None
    Qt = object
    QFileDialog = object
    QHBoxLayout = object
    QLabel = object
    QLineEdit = object
    QListWidget = object
    QComboBox = object
    QMainWindow = object
    QMessageBox = object
    QPushButton = object
    QTimer = object
    QSpinBox = object
    QTreeWidget = object
    QTreeWidgetItem = object
    QVBoxLayout = object
    QWidget = object

THEME_PRESETS: tuple[tuple[str, str], ...] = (
    ("Default", "default"),
    ("Professional", "professional"),
    ("Minimal", "minimal"),
)
DEFAULT_THEME_PRESET = "default"
ADVANCED_ACTIONS: tuple[tuple[str, str], ...] = (
    ("Select...", ""),
    ("Initialize Database", "init"),
    ("Summarize Inventory", "summarize"),
    ("Enrich Places", "enrich-places"),
    ("Analyze Duplicates", "analyze-duplicates"),
    ("Audit Dates", "audit-dates"),
    ("Approve Execute", "approve-execute"),
    ("Export Review Packets", "export-folder-packets"),
    ("Import Review", "import-folder-review"),
)


def parse_design_tokens(tokens_css: str) -> dict[str, str]:
    clean = re.sub(r"/\*.*?\*/", "", tokens_css, flags=re.DOTALL)
    root_match = re.search(r":root\s*\{(?P<body>.*?)\}", clean, flags=re.DOTALL)
    if not root_match:
        return {}
    body = root_match.group("body")
    token_pattern = re.compile(r"--([a-zA-Z0-9_-]+)\s*:\s*([^;]+);")
    return {m.group(1): m.group(2).strip() for m in token_pattern.finditer(body)}


def _resolve_token(name: str, tokens: dict[str, str], stack: set[str] | None = None) -> str | None:
    if stack is None:
        stack = set()
    if name in stack:
        return None
    raw = tokens.get(name)
    if raw is None:
        return None
    var_match = re.fullmatch(r"var\(--([a-zA-Z0-9_-]+)\)", raw.strip())
    if not var_match:
        return raw.strip()
    stack.add(name)
    return _resolve_token(var_match.group(1), tokens, stack)


def build_theme_stylesheet(tokens: dict[str, str]) -> str:
    fallback = {
        "bg": "#f7f7f8",
        "surface": "#ffffff",
        "fg": "#111111",
        "muted": "#666666",
        "border": "#d7d7d7",
        "accent": "#2f6feb",
        "accent_on": "#ffffff",
        "space_2": "8px",
        "space_4": "16px",
        "radius_sm": "6px",
        "font_body": "Segoe UI, Arial, sans-serif",
        "text_base": "14px",
    }
    values = {
        "bg": _resolve_token("bg", tokens) or fallback["bg"],
        "surface": _resolve_token("surface", tokens) or fallback["surface"],
        "fg": _resolve_token("fg", tokens) or fallback["fg"],
        "muted": _resolve_token("muted", tokens) or fallback["muted"],
        "border": _resolve_token("border", tokens) or fallback["border"],
        "accent": _resolve_token("accent", tokens) or fallback["accent"],
        "accent_on": _resolve_token("accent-on", tokens) or fallback["accent_on"],
        "space_2": _resolve_token("space-2", tokens) or fallback["space_2"],
        "space_4": _resolve_token("space-4", tokens) or fallback["space_4"],
        "radius_sm": _resolve_token("radius-sm", tokens) or fallback["radius_sm"],
        "font_body": _resolve_token("font-body", tokens) or fallback["font_body"],
        "text_base": _resolve_token("text-base", tokens) or fallback["text_base"],
    }
    return f"""
QWidget {{
  background-color: {values['bg']};
  color: {values['fg']};
  font-family: {values['font_body']};
  font-size: {values['text_base']};
}}
QMainWindow, QListWidget, QTreeWidget {{
  background-color: {values['surface']};
}}
QLineEdit, QSpinBox, QComboBox, QListWidget, QTreeWidget {{
  background-color: {values['surface']};
  border: 1px solid {values['border']};
  border-radius: {values['radius_sm']};
  padding: {values['space_2']};
}}
QPushButton {{
  background-color: {values['accent']};
  color: {values['accent_on']};
  border: 1px solid {values['border']};
  border-radius: {values['radius_sm']};
  padding: {values['space_2']} {values['space_4']};
}}
QLabel {{
  color: {values['muted']};
}}
"""


def _design_systems_root() -> Path:
    return Path(".test-tmp") / "open-design" / "design-systems"


def load_theme_stylesheet(preset: str) -> str:
    systems_root = _design_systems_root()
    token_file = systems_root / preset / "tokens.css"
    if token_file.exists():
        tokens = parse_design_tokens(token_file.read_text(encoding="utf-8"))
        return build_theme_stylesheet(tokens)
    return build_theme_stylesheet({})


class MainWindow(QMainWindow):
    def __init__(self, service: PhotoOrganizerService) -> None:
        super().__init__()
        self.service = service
        self.setWindowTitle("Photo Organizer v2 - MVP6 Shell")
        self.resize(1400, 900)
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._future: Future | None = None
        self._future_command = ""
        self._future_after = None
        self._worker_snapshot: dict[str, str] | None = None

        root_widget = QWidget()
        root_layout = QVBoxLayout(root_widget)
        self.setCentralWidget(root_widget)

        roots = self.service.get_roots()
        root_bar = QHBoxLayout()
        self.source_edit = QLineEdit(roots["source_root"])
        self.archive_edit = QLineEdit(roots["archive_root"])
        src_button = QPushButton("Source...")
        src_button.clicked.connect(self._choose_source)
        arc_button = QPushButton("Archive...")
        arc_button.clicked.connect(self._choose_archive)
        apply_button = QPushButton("Apply Roots")
        apply_button.clicked.connect(self._apply_roots)
        self.theme_combo = QComboBox()
        for label, slug in THEME_PRESETS:
            self.theme_combo.addItem(label, slug)
        current_theme = self.service.get_theme_preset(DEFAULT_THEME_PRESET)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        for idx in range(self.theme_combo.count()):
            if self.theme_combo.itemData(idx) == current_theme:
                self.theme_combo.setCurrentIndex(idx)
                break
        root_bar.addWidget(QLabel("Source"))
        root_bar.addWidget(self.source_edit, 1)
        root_bar.addWidget(src_button)
        root_bar.addWidget(QLabel("Archive"))
        root_bar.addWidget(self.archive_edit, 1)
        root_bar.addWidget(arc_button)
        root_bar.addWidget(QLabel("Theme"))
        root_bar.addWidget(self.theme_combo)
        root_bar.addWidget(apply_button)
        root_layout.addLayout(root_bar)

        action_bar = QHBoxLayout()
        self.scan_btn = QPushButton("1) Scan")
        self.scan_btn.clicked.connect(self._run_scan)
        self.analyze_btn = QPushButton("2) Analyze")
        self.analyze_btn.clicked.connect(self._run_analyze_bundle)
        self.plan_btn = QPushButton("3) Plan")
        self.plan_btn.clicked.connect(self._run_plan)
        self.dry_run_btn = QPushButton("4) Dry-Run")
        self.dry_run_btn.clicked.connect(self._run_dry_run)
        self.execute_btn = QPushButton("5) Execute")
        self.execute_btn.clicked.connect(self._run_execute)
        self.execute_btn.setEnabled(False)
        action_bar.addWidget(self.scan_btn)
        action_bar.addWidget(self.analyze_btn)
        action_bar.addWidget(self.plan_btn)
        action_bar.addWidget(self.dry_run_btn)
        action_bar.addWidget(self.execute_btn)
        self.advanced_combo = QComboBox()
        for label, action in ADVANCED_ACTIONS:
            self.advanced_combo.addItem(label, action)
        self.advanced_run_btn = QPushButton("Run Extra Action")
        self.advanced_run_btn.clicked.connect(self._run_advanced_action)
        action_bar.addWidget(QLabel("Advanced"))
        action_bar.addWidget(self.advanced_combo)
        action_bar.addWidget(self.advanced_run_btn)
        root_layout.addLayout(action_bar)

        panel_layout = QHBoxLayout()
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["All Folders"])
        self.tree.itemChanged.connect(self._on_tree_item_changed)
        self.tree.itemExpanded.connect(self._on_tree_item_expanded)
        self.included = QListWidget()
        self.excluded = QListWidget()
        panel_layout.addWidget(self.tree, 2)
        panel_layout.addWidget(self.included, 1)
        panel_layout.addWidget(self.excluded, 1)
        root_layout.addLayout(panel_layout, 3)

        page_bar = QHBoxLayout()
        self.page_spin = QSpinBox()
        self.page_spin.setMinimum(1)
        self.page_spin.setValue(1)
        self.page_size_spin = QSpinBox()
        self.page_size_spin.setMinimum(1)
        self.page_size_spin.setMaximum(100000)
        self.page_size_spin.setValue(DEFAULT_PAGE_SIZE)
        page_btn = QPushButton("Load Page")
        page_btn.clicked.connect(self._load_page)
        self.page_label = QLabel("rows=0 total=0")
        page_bar.addWidget(QLabel("Page"))
        page_bar.addWidget(self.page_spin)
        page_bar.addWidget(QLabel("Page Size"))
        page_bar.addWidget(self.page_size_spin)
        page_bar.addWidget(page_btn)
        page_bar.addWidget(self.page_label, 1)
        root_layout.addLayout(page_bar)

        self.status_label = QLabel("Idle")
        self.progress_label = QLabel("progress=idle")
        self.failure_label = QLabel("failure=-")
        self.resume_label = QLabel("resume=ready")
        root_layout.addWidget(self.status_label)
        root_layout.addWidget(self.progress_label)
        root_layout.addWidget(self.failure_label)
        root_layout.addWidget(self.resume_label)

        self._refresh_folder_panels()
        self._sync_execute_state()
        self._apply_theme(current_theme)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(120)
        self._poll_timer.timeout.connect(self._poll_future)

    def _choose_source(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select Source Root", self.source_edit.text())
        if path:
            self.source_edit.setText(path)

    def _choose_archive(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select Archive Root", self.archive_edit.text())
        if path:
            self.archive_edit.setText(path)

    def _apply_roots(self) -> None:
        self.service.set_roots(self.source_edit.text(), self.archive_edit.text())
        self.status_label.setText("Roots updated")

    def _record_result(self, command: str, result: dict) -> None:
        ok = bool(result.get("ok", False))
        summary = result.get("summary", {})
        errors = result.get("errors", [])
        self.status_label.setText(f"{command} ok={ok}")
        self.progress_label.setText(f"progress={command}")
        if ok:
            self.failure_label.setText("failure=-")
        else:
            self.failure_label.setText(f"failure={errors or summary}")
        state = self.service.workflow_state() if hasattr(self.service, "workflow_state") else {}
        self.resume_label.setText(f"resume={state.get('resume_state', 'ready')}")
        self._sync_execute_state()

    def _run_init(self) -> None:
        self._record_result("init", self.service.run_init())

    def _run_scan(self) -> None:
        if not self._can_use_worker_service():
            if hasattr(self.service, "run_scan_inventory"):
                self._record_result("scan-inventory", self.service.run_scan_inventory())
            else:
                self._record_result("scan", self.service.run_scan())
            self._after_scan()
            return
        self._start_background("scan", self._run_scan_background, after=self._after_scan)

    def _run_summarize(self) -> None:
        if not self._can_use_worker_service():
            self._record_result("summarize", self.service.run_summarize())
            return
        self._start_background("summarize", self._run_summarize_background)

    def _run_enrich_places(self) -> None:
        if not self._can_use_worker_service():
            self._record_result("enrich-places", self.service.run_enrich_places())
            return
        self._start_background("enrich-places", self._run_enrich_places_background)

    def _run_analyze_duplicates(self) -> None:
        if not self._can_use_worker_service():
            self._record_result("analyze-duplicates", self.service.run_analyze_duplicates())
            return
        self._start_background("analyze-duplicates", self._run_analyze_duplicates_background)

    def _run_audit_dates(self) -> None:
        if not self._can_use_worker_service():
            self._record_result("audit-dates", self.service.run_audit_dates())
            return
        self._start_background("audit-dates", self._run_audit_dates_background)

    def _run_analyze_bundle(self) -> None:
        if not self._can_use_worker_service():
            self._record_result("analyze", self._run_analyze_bundle_internal())
            return
        self._start_background("analyze", self._run_analyze_bundle_internal)

    def _can_use_worker_service(self) -> bool:
        return hasattr(self.service, "db_path") and hasattr(self.service, "get_roots")

    def _capture_worker_snapshot(self) -> dict[str, str] | None:
        if not self._can_use_worker_service():
            return None
        roots = self.service.get_roots()
        return {
            "db_path": str(self.service.db_path),
            "source_root": roots["source_root"],
            "archive_root": roots["archive_root"],
        }

    def _create_worker_service(self) -> PhotoOrganizerService | None:
        snapshot = self._worker_snapshot
        if snapshot is None:
            return None
        return PhotoOrganizerService(
            snapshot["db_path"],
            source_root=snapshot["source_root"],
            archive_root=snapshot["archive_root"],
        )

    def _start_background(self, command: str, fn, after=None) -> None:
        self._worker_snapshot = self._capture_worker_snapshot()
        if not hasattr(self, "_future"):
            self._future = None
        if not hasattr(self, "_executor"):
            result = fn()
            if not isinstance(result, dict):
                result = {"ok": False, "errors": [{"code": "invalid_result"}]}
            self._record_result(command, result)
            if callable(after):
                after()
            return
        if self._future and not self._future.done():
            self.failure_label.setText("failure=another task is already running")
            return
        self._future_command = command
        self._future_after = after
        self._set_busy(True, command)
        self._future = self._executor.submit(fn)
        self._poll_timer.start()

    def _poll_future(self) -> None:
        if not self._future:
            self._poll_timer.stop()
            return
        if not self._future.done():
            return
        self._poll_timer.stop()
        try:
            result = self._future.result()
            if not isinstance(result, dict):
                result = {"ok": False, "errors": [{"code": "invalid_result"}]}
        except Exception as exc:
            result = {"ok": False, "errors": [{"code": "background_task_error", "message": str(exc)}]}
        command = self._future_command
        after = self._future_after
        self._last_background_result = result
        self._future = None
        self._future_command = ""
        self._future_after = None
        self._worker_snapshot = None
        self._set_busy(False)
        self._record_result(command, result)
        if callable(after):
            after()

    

    def _run_scan_background(self) -> dict:
        if self._can_use_worker_service():
            roots = self._worker_snapshot or {}
            return self._run_cli_command(
                "scan-inventory",
                "--source",
                roots.get("source_root", r"D:\\"),
                "--archive-root",
                roots.get("archive_root", r"D:\\PICTURES"),
                "--db",
                roots.get("db_path", ".photos-data/photos.sqlite"),
            )
        return self.service.run_scan()

    def _run_summarize_background(self) -> dict:
        if self._can_use_worker_service():
            roots = self._worker_snapshot or {}
            return self._run_cli_command("summarize", "--db", roots.get("db_path", ".photos-data/photos.sqlite"))
        return self.service.run_summarize()

    def _run_enrich_places_background(self) -> dict:
        if self._can_use_worker_service():
            roots = self._worker_snapshot or {}
            return self._run_cli_command("enrich-places", "--db", roots.get("db_path", ".photos-data/photos.sqlite"))
        return self.service.run_enrich_places()

    def _run_analyze_duplicates_background(self) -> dict:
        if self._can_use_worker_service():
            roots = self._worker_snapshot or {}
            return self._run_cli_command("analyze-duplicates", "--db", roots.get("db_path", ".photos-data/photos.sqlite"))
        return self.service.run_analyze_duplicates()

    def _run_audit_dates_background(self) -> dict:
        if self._can_use_worker_service():
            roots = self._worker_snapshot or {}
            return self._run_cli_command("audit-dates", "--db", roots.get("db_path", ".photos-data/photos.sqlite"))
        return self.service.run_audit_dates()

    def _after_scan(self) -> None:
        if hasattr(self.service, "refresh_selection_model"):
            self.service.refresh_selection_model()
        self._refresh_folder_panels()

    def _run_analyze_bundle_internal(self) -> dict:
        if self._can_use_worker_service():
            roots = self._worker_snapshot or {}
            db = roots.get("db_path", ".photos-data/photos.sqlite")
            source = roots.get("source_root", r"D:\\")
            archive = roots.get("archive_root", r"D:\\PICTURES")
            failures: list[str] = []
            last_result: dict = {"ok": True, "summary": {}}
            for cmd in (
                ("scan", ["scan", "--source", source, "--archive-root", archive, "--db", db]),
                ("summarize", ["summarize", "--db", db]),
                ("enrich-places", ["enrich-places", "--db", db]),
                ("analyze-duplicates", ["analyze-duplicates", "--db", db]),
                ("audit-dates", ["audit-dates", "--db", db]),
            ):
                result = self._run_cli_command(*cmd[1])
                if not result.get("ok", False):
                    failures.append(cmd[0])
                last_result = result
            if failures:
                return {"ok": False, "errors": [{"code": "analyze_bundle_failed", "steps": failures}]}
            return last_result
        worker = self._create_worker_service()
        svc = worker if worker is not None else self.service
        steps = [
            ("scan", svc.run_scan),
            ("summarize", svc.run_summarize),
            ("enrich-places", svc.run_enrich_places),
            ("analyze-duplicates", svc.run_analyze_duplicates),
            ("audit-dates", svc.run_audit_dates),
        ]
        try:
            last_result: dict = {"ok": True, "summary": {}}
            failures: list[str] = []
            for command, fn in steps:
                result = fn()
                if not result.get("ok", False):
                    failures.append(command)
                last_result = result
            if failures:
                return {"ok": False, "errors": [{"code": "analyze_bundle_failed", "steps": failures}]}
            return last_result
        finally:
            if worker is not None:
                worker.close()

    def _run_plan(self) -> None:
        if not self._can_use_worker_service():
            self._record_result("plan", self.service.run_plan())
            return
        self._start_background("plan", self._run_plan_background)

    def _approve_execute(self) -> None:
        result = self.service.approve_latest_plan_execute()
        self._record_result("approve-execute", result)

    def _run_dry_run(self) -> None:
        if not self._can_use_worker_service():
            self._apply_dry_run_result(self.service.run_dry_run())
            return
        self._start_background("dry-run", self._run_dry_run_background, after=self._after_dry_run)

    def _run_plan_background(self) -> dict:
        if self._can_use_worker_service():
            roots = self._worker_snapshot or {}
            return self._run_cli_command(
                "plan",
                "--db",
                roots.get("db_path", ".photos-data/photos.sqlite"),
                "--archive-root",
                roots.get("archive_root", r"D:\\PICTURES"),
            )
        return self.service.run_plan()

    def _run_dry_run_background(self) -> dict:
        if self._can_use_worker_service():
            roots = self._worker_snapshot or {}
            return self._run_cli_command("dry-run", "--db", roots.get("db_path", ".photos-data/photos.sqlite"))
        return self.service.run_dry_run()

    def _run_cli_command(self, *args: str) -> dict:
        cmd = [sys.executable]
        env = os.environ.copy()
        if getattr(sys, "frozen", False):
            cmd.extend(["--cli", *args])
        else:
            cmd.extend(["-m", "photos.app", "--cli", *args])
            src_root = str(Path(__file__).resolve().parents[1])
            existing = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = src_root if not existing else f"{src_root}{os.pathsep}{existing}"
        cp = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        payload = cp.stdout.strip()
        if not payload:
            return {"ok": False, "errors": [{"code": "cli_no_output", "stderr": cp.stderr.strip()}]}
        try:
            out = json.loads(payload)
        except json.JSONDecodeError:
            return {"ok": False, "errors": [{"code": "cli_bad_json", "stdout": payload, "stderr": cp.stderr.strip()}]}
        return {
            "ok": bool(out.get("ok", False)),
            "summary": out.get("summary", {}),
            "errors": out.get("errors", []),
            "warnings": out.get("warnings", []),
        }

    def _after_dry_run(self) -> None:
        result = getattr(self, "_last_background_result", {})
        if not isinstance(result, dict) or "error_count" not in result:
            return
        self._apply_dry_run_result(result)

    def _apply_dry_run_result(self, result: dict) -> None:
        self.status_label.setText(f"Dry-run errors={result['error_count']}")
        self.progress_label.setText("progress=dry-run")
        if result.get("error_count", 0):
            self.failure_label.setText(f"failure={result.get('blocking_reasons', [])}")
        else:
            self.failure_label.setText("failure=-")
        state = self.service.workflow_state() if hasattr(self.service, "workflow_state") else {}
        self.resume_label.setText(f"resume={state.get('resume_state', 'ready')}")
        self._sync_execute_state()

    def _run_execute(self) -> None:
        result = self.service.run_execute(execute_approved=True)
        if result.get("ok", False):
            self._record_result("execute", result)
            return
        self.failure_label.setText(f"failure={result.get('errors', [])}")
        QMessageBox.warning(self, "Execute blocked", str(result.get("errors", [])))

    def _export_packets(self) -> None:
        out = QFileDialog.getExistingDirectory(self, "Export Packet Directory")
        if not out:
            return
        result = self.service.export_packets(out)
        self._record_result("export-folder-packets", result)

    def _import_review(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import Review JSON", "", "JSON (*.json)")
        if not path:
            return
        result = self.service.import_review(path)
        self._record_result("import-folder-review", result)

    def _run_advanced_action(self) -> None:
        action = str(self.advanced_combo.currentData())
        if not action:
            return
        if action == "init":
            self._run_init()
            return
        if action == "summarize":
            self._run_summarize()
            return
        if action == "enrich-places":
            self._run_enrich_places()
            return
        if action == "analyze-duplicates":
            self._run_analyze_duplicates()
            return
        if action == "audit-dates":
            self._run_audit_dates()
            return
        if action == "approve-execute":
            self._approve_execute()
            return
        if action == "export-folder-packets":
            self._export_packets()
            return
        if action == "import-folder-review":
            self._import_review()
            return

    def _set_busy(self, busy: bool, command: str = "") -> None:
        for button in (
            self.scan_btn,
            self.analyze_btn,
            self.plan_btn,
            self.dry_run_btn,
            self.execute_btn,
            self.advanced_run_btn,
        ):
            button.setEnabled(not busy if button is not self.execute_btn else button.isEnabled() and not busy)
        if busy:
            self.status_label.setText(f"{command} running...")
            self.progress_label.setText(f"progress={command}:running")
        else:
            self._sync_execute_state()


    def _load_page(self) -> None:
        result = self.service.page_media(
            page=self.page_spin.value(),
            page_size=self.page_size_spin.value(),
        )
        self.page_label.setText(f"rows={len(result['rows'])} total={result['total']}")

    def _sync_execute_state(self) -> None:
        allowed, reasons = self.service.can_execute()
        self.execute_btn.setEnabled(allowed)
        if not allowed:
            self.execute_btn.setToolTip(f"Execute blocked: {','.join(reasons)}")
        else:
            self.execute_btn.setToolTip("Latest dry-run passed and execute approval exists")

    def _refresh_folder_panels(self) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()
        self.included.clear()
        self.excluded.clear()

        nodes = self.service.selection.nodes
        children = self.service.selection.children
        self._tree_nodes = nodes
        self._tree_children = children
        top_level = [p for p, n in nodes.items() if not n.parent_path or n.parent_path not in nodes]
        for path in sorted(top_level):
            self.tree.addTopLevelItem(self._build_tree_item(path))

        panels = self.service.load_folder_panels()
        self.included.addItems(panels["included"])
        self.excluded.addItems(panels["excluded"])
        self.tree.blockSignals(False)

    def _build_tree_item(self, path: str) -> QTreeWidgetItem:
        node = self._tree_nodes[path]
        item = QTreeWidgetItem([path])
        item.setData(0, Qt.UserRole, path)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(0, self._qt_state(node.state))
        if self._tree_children.get(path):
            placeholder = QTreeWidgetItem(["..."])
            placeholder.setData(0, Qt.UserRole, "__placeholder__")
            item.addChild(placeholder)
        return item

    def _on_tree_item_expanded(self, item: QTreeWidgetItem) -> None:
        path = item.data(0, Qt.UserRole)
        if not path or path == "__placeholder__":
            return
        if item.childCount() == 1 and item.child(0).data(0, Qt.UserRole) == "__placeholder__":
            self.tree.blockSignals(True)
            item.takeChildren()
            for child_path in sorted(self._tree_children.get(str(path), [])):
                item.addChild(self._build_tree_item(child_path))
            self.tree.blockSignals(False)

    def _qt_state(self, state: int) -> Qt.CheckState:
        if state == 2:
            return Qt.Checked
        if state == 1:
            return Qt.PartiallyChecked
        return Qt.Unchecked

    def _on_tree_item_changed(self, item: QTreeWidgetItem, _column: int) -> None:
        path = item.data(0, Qt.UserRole)
        if not path:
            return
        checked = item.checkState(0) == Qt.Checked
        self.service.set_folder_checked(str(path), checked)
        self._refresh_folder_panels()

    def _on_theme_changed(self, _index: int) -> None:
        theme = str(self.theme_combo.currentData())
        self.service.set_theme_preset(theme)
        self._apply_theme(theme)

    def _apply_theme(self, preset: str) -> None:
        self.setStyleSheet(load_theme_stylesheet(preset))


def run_smoke(db_path: str | Path) -> int:
    service = PhotoOrganizerService(db_path)
    try:
        # Smoke path ensures service wiring can run without opening a window.
        summary = service.smoke()
        service.page_media(page=1, page_size=DEFAULT_PAGE_SIZE)
        print(json.dumps({"schema_version": 1, "ok": True, "command": "gui-smoke", "summary": summary}, ensure_ascii=True))
        return 0
    finally:
        service.close()


def _show_startup_error_dialog(message: str, title: str = "Photo Organizer v2") -> None:
    # In --noconsole builds, print() output is invisible. Show a native dialog for startup failures.
    try:
        ctypes.windll.user32.MessageBoxW(None, message, title, 0x10)
    except Exception:
        return


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="photos.app")
    parser.add_argument("--db", default=".photos-data/photos.sqlite")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if args.smoke:
        return run_smoke(db_path)

    if QApplication is None:
        _show_startup_error_dialog(
            "PySide6 is not available in this build environment.\n\n"
            "Install PySide6, rebuild the executable, and run again."
        )
        print(
            '{"schema_version":1,"ok":false,"command":"gui","errors":[{"code":"pyside6_missing"}]}'
        )
        return 2
    app = QApplication(sys.argv)
    service = PhotoOrganizerService(db_path)
    window = MainWindow(service)
    window.show()
    code = app.exec()
    service.close()
    return int(code)


if __name__ == "__main__":
    raise SystemExit(main())
