from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from .services import PhotoOrganizerService
from .store import DEFAULT_PAGE_SIZE

try:
    from PySide6.QtCore import Qt
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
        self.init_btn = QPushButton("Init")
        self.init_btn.clicked.connect(self._run_init)
        self.scan_btn = QPushButton("Scan")
        self.scan_btn.clicked.connect(self._run_scan)
        self.summary_btn = QPushButton("Summarize")
        self.summary_btn.clicked.connect(self._run_summarize)
        self.places_btn = QPushButton("Enrich Places")
        self.places_btn.clicked.connect(self._run_enrich_places)
        self.duplicates_btn = QPushButton("Analyze Duplicates")
        self.duplicates_btn.clicked.connect(self._run_analyze_duplicates)
        self.audit_btn = QPushButton("Audit Dates")
        self.audit_btn.clicked.connect(self._run_audit_dates)
        self.plan_btn = QPushButton("Plan")
        self.plan_btn.clicked.connect(self._run_plan)
        self.approve_execute_btn = QPushButton("Approve Execute")
        self.approve_execute_btn.clicked.connect(self._approve_execute)
        self.dry_run_btn = QPushButton("Dry-Run")
        self.dry_run_btn.clicked.connect(self._run_dry_run)
        self.execute_btn = QPushButton("Execute")
        self.execute_btn.clicked.connect(self._run_execute)
        self.execute_btn.setEnabled(False)
        self.export_btn = QPushButton("Export Packets")
        self.export_btn.clicked.connect(self._export_packets)
        self.import_btn = QPushButton("Import Review")
        self.import_btn.clicked.connect(self._import_review)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.resume_btn = QPushButton("Resume")
        self.resume_btn.setEnabled(False)
        action_bar.addWidget(self.init_btn)
        action_bar.addWidget(self.scan_btn)
        action_bar.addWidget(self.summary_btn)
        action_bar.addWidget(self.places_btn)
        action_bar.addWidget(self.duplicates_btn)
        action_bar.addWidget(self.audit_btn)
        action_bar.addWidget(self.plan_btn)
        action_bar.addWidget(self.approve_execute_btn)
        action_bar.addWidget(self.dry_run_btn)
        action_bar.addWidget(self.execute_btn)
        action_bar.addWidget(self.export_btn)
        action_bar.addWidget(self.import_btn)
        action_bar.addWidget(self.cancel_btn)
        action_bar.addWidget(self.resume_btn)
        root_layout.addLayout(action_bar)

        panel_layout = QHBoxLayout()
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["All Folders"])
        self.tree.itemChanged.connect(self._on_tree_item_changed)
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
        result = self.service.run_scan()
        self._record_result("scan", result)
        self._refresh_folder_panels()

    def _run_summarize(self) -> None:
        self._record_result("summarize", self.service.run_summarize())

    def _run_enrich_places(self) -> None:
        self._record_result("enrich-places", self.service.run_enrich_places())

    def _run_analyze_duplicates(self) -> None:
        self._record_result("analyze-duplicates", self.service.run_analyze_duplicates())

    def _run_audit_dates(self) -> None:
        self._record_result("audit-dates", self.service.run_audit_dates())

    def _run_plan(self) -> None:
        result = self.service.run_plan()
        self._record_result("plan", result)

    def _approve_execute(self) -> None:
        result = self.service.approve_latest_plan_execute()
        self._record_result("approve-execute", result)

    def _run_dry_run(self) -> None:
        result = self.service.run_dry_run()
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
        items: dict[str, QTreeWidgetItem] = {}
        roots: list[str] = []
        for path, node in nodes.items():
            item = QTreeWidgetItem([path])
            item.setData(0, Qt.UserRole, path)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, self._qt_state(node.state))
            items[path] = item
            if node.parent_path and node.parent_path in nodes:
                items.setdefault(node.parent_path, QTreeWidgetItem([node.parent_path]))
                roots.append(path)
            else:
                roots.append(path)

        for parent_path, child_paths in children.items():
            parent_item = items[parent_path]
            for child in child_paths:
                parent_item.addChild(items[child])

        top_level = [p for p, n in nodes.items() if not n.parent_path or n.parent_path not in nodes]
        for path in sorted(top_level):
            self.tree.addTopLevelItem(items[path])

        panels = self.service.load_folder_panels()
        self.included.addItems(panels["included"])
        self.excluded.addItems(panels["excluded"])
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
