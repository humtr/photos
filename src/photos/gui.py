from __future__ import annotations

import argparse
import json
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
    QMainWindow = object
    QMessageBox = object
    QPushButton = object
    QSpinBox = object
    QTreeWidget = object
    QTreeWidgetItem = object
    QVBoxLayout = object
    QWidget = object


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
        root_bar.addWidget(QLabel("Source"))
        root_bar.addWidget(self.source_edit, 1)
        root_bar.addWidget(src_button)
        root_bar.addWidget(QLabel("Archive"))
        root_bar.addWidget(self.archive_edit, 1)
        root_bar.addWidget(arc_button)
        root_bar.addWidget(apply_button)
        root_layout.addLayout(root_bar)

        action_bar = QHBoxLayout()
        self.plan_btn = QPushButton("Plan")
        self.plan_btn.clicked.connect(self._run_plan)
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
        action_bar.addWidget(self.plan_btn)
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
        root_layout.addWidget(self.status_label)
        root_layout.addWidget(self.progress_label)

        self._refresh_folder_panels()
        self._sync_execute_state()

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

    def _run_plan(self) -> None:
        result = self.service.run_plan()
        self.status_label.setText(f"Plan ok={result['ok']}")
        self.progress_label.setText("progress=planned")

    def _run_dry_run(self) -> None:
        result = self.service.run_dry_run()
        self.status_label.setText(f"Dry-run errors={result['error_count']}")
        self.progress_label.setText("progress=dry-run")
        self._sync_execute_state()

    def _run_execute(self) -> None:
        result = self.service.run_execute(execute_approved=True)
        if result.get("ok", False):
            self.status_label.setText("Execute scaffold completed")
            return
        QMessageBox.warning(self, "Execute blocked", str(result.get("errors", [])))

    def _export_packets(self) -> None:
        out = QFileDialog.getExistingDirectory(self, "Export Packet Directory")
        if not out:
            return
        result = self.service.export_packets(out)
        self.status_label.setText(f"Packet exported: {result.get('path', '-')}")

    def _import_review(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import Review JSON", "", "JSON (*.json)")
        if not path:
            return
        result = self.service.import_review(path)
        self.status_label.setText(f"Review import ok={result.get('ok', False)}")

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
            self.status_label.setText(f"Execute blocked: {','.join(reasons)}")

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
