from __future__ import annotations

import json
import os
import sqlite3
import sys
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TEST_TMP_ROOT = ROOT / ".test-tmp" / "phase5-gui"
TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from photos.schemas import DryRunResult  # noqa: E402
from photos.gui import MainWindow  # noqa: E402
from photos.services import PhotoOrganizerService  # noqa: E402
from photos.store import Store, get_or_create_scan_root, now_ts  # noqa: E402


def new_db_path() -> Path:
    return TEST_TMP_ROOT / f"{uuid.uuid4().hex}.sqlite"


class TestPhase5ServiceWorkflow(unittest.TestCase):
    def test_service_methods_delegate_to_real_workflow_modules(self) -> None:
        db = new_db_path()
        service = PhotoOrganizerService(db, source_root=str(TEST_TMP_ROOT), archive_root=str(TEST_TMP_ROOT / "archive"))
        try:
            get_or_create_scan_root(service.store.conn, str(TEST_TMP_ROOT), str(TEST_TMP_ROOT / "archive"), now_ts())
            with mock.patch("photos.services.run_scan", return_value=SimpleNamespace(scan_run_id=7, folder_count=2, file_count=3, error_count=0)) as scan, \
                mock.patch("photos.services.summarize", return_value={"file_count": 3}) as summarize, \
                mock.patch("photos.services.enrich_places", return_value={"folders_with_place": 1}) as places, \
                mock.patch("photos.services.analyze_duplicates", return_value={"candidate_count": 1}) as dupes, \
                mock.patch("photos.services.audit_dates", return_value={"issue_count": 1}) as audit, \
                mock.patch("photos.services.export_folder_packets", return_value={"packet_count": 1, "index_path": str(TEST_TMP_ROOT / "index.json"), "index_sha256": "sha"}) as export, \
                mock.patch("photos.services.import_folder_review", return_value={"imported": 1, "rejected": 0, "errors": []}) as import_review, \
                mock.patch("photos.services.build_plan", return_value=42) as plan, \
                mock.patch("photos.services.dry_run", return_value=DryRunResult(plan_id=42, error_count=0, execute_allowed=True)) as dry, \
                mock.patch("photos.services.execute_plan", return_value=SimpleNamespace(to_dict=lambda: {"batch_id": 9}, next_safe_action="complete")) as execute, \
                mock.patch.object(service, "_latest_plan_id", return_value=42):
                self.assertTrue(service.run_scan()["ok"])
                self.assertTrue(service.run_summarize()["ok"])
                self.assertTrue(service.run_enrich_places()["ok"])
                self.assertTrue(service.run_analyze_duplicates()["ok"])
                self.assertTrue(service.run_audit_dates()["ok"])
                self.assertTrue(service.export_packets(TEST_TMP_ROOT / "packets")["ok"])
                self.assertTrue(service.import_review(TEST_TMP_ROOT / "review.json")["ok"])
                self.assertTrue(service.run_plan()["ok"])
                service.store.store.add_approval("execute", "plan", 42, True, "test")
                self.assertTrue(service.run_dry_run()["execute_allowed"])
                self.assertTrue(service.run_execute(execute_approved=True)["ok"])

            for fn in (scan, summarize, places, dupes, audit, export, import_review, plan, dry, execute):
                self.assertTrue(fn.called, fn)
        finally:
            service.close()
            db.unlink(missing_ok=True)

    def test_execute_gating_requires_passing_dry_run_and_approval(self) -> None:
        db = new_db_path()
        service = PhotoOrganizerService(db)
        try:
            store = Store(db)
            try:
                store.init_schema()
                root_id = store.add_scan_root(str(TEST_TMP_ROOT), str(TEST_TMP_ROOT / "archive"))
                plan_id = store.create_plan(root_id, "hybrid", str(TEST_TMP_ROOT / "archive"), {})
            finally:
                store.close()

            allowed, reasons = service.can_execute()
            self.assertFalse(allowed)
            self.assertIn("dry_run_not_run", reasons)

            service.store.conn.execute(
                """
                INSERT INTO dry_run_reports(error_count, execute_allowed, blocking_reasons_json, summary_json, created_at)
                VALUES(0, 1, '[]', ?, datetime('now'))
                """,
                (json.dumps({"plan_id": plan_id, "execute_allowed": True}),),
            )
            service.store.conn.commit()
            allowed, reasons = service.can_execute()
            self.assertFalse(allowed)
            self.assertIn("missing_execute_approval", reasons)

            service.approve_latest_plan_execute()
            allowed, reasons = service.can_execute()
            self.assertTrue(allowed, reasons)
        finally:
            service.close()
            db.unlink(missing_ok=True)

    def test_populated_db_smoke_and_bounded_large_page(self) -> None:
        db = new_db_path()
        service = PhotoOrganizerService(db)
        try:
            rows = ((f"/bulk/{i}.jpg", "/bulk", f"{i}.jpg", i + 1, i) for i in range(20_000))
            service.store.conn.executemany(
                """
                INSERT INTO media_files(path, folder_path, name, size_bytes, mtime_ns, existence_state, scan_root_id)
                VALUES(?, ?, ?, ?, ?, 'seen', 1)
                """,
                rows,
            )
            service.store.conn.commit()
            page = service.page_media(page=2, page_size=500)
            self.assertEqual(500, len(page["rows"]))
            self.assertEqual(20_000, page["total"])
        finally:
            service.close()
            db.unlink(missing_ok=True)


class TestPhase5MainWindowHandlersWithoutQt(unittest.TestCase):
    def test_handlers_call_required_service_actions_without_qt_runtime(self) -> None:
        class FakeLabel:
            def __init__(self) -> None:
                self.text = ""

            def setText(self, text: str) -> None:
                self.text = text

        class FakeButton:
            def __init__(self) -> None:
                self.enabled = False
                self.tooltip = ""

            def setEnabled(self, value: bool) -> None:
                self.enabled = bool(value)

            def setToolTip(self, value: str) -> None:
                self.tooltip = value

        class FakeService:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def can_execute(self) -> tuple[bool, list[str]]:
                return True, []

            def workflow_state(self) -> dict[str, str]:
                return {"resume_state": "ready"}

            def run_init(self) -> dict:
                self.calls.append("init")
                return {"ok": True, "summary": {}}

            def run_scan(self) -> dict:
                self.calls.append("scan")
                return {"ok": True, "summary": {}}

            def run_summarize(self) -> dict:
                self.calls.append("summarize")
                return {"ok": True, "summary": {}}

            def run_enrich_places(self) -> dict:
                self.calls.append("enrich-places")
                return {"ok": True, "summary": {}}

            def run_analyze_duplicates(self) -> dict:
                self.calls.append("analyze-duplicates")
                return {"ok": True, "summary": {}}

            def run_audit_dates(self) -> dict:
                self.calls.append("audit-dates")
                return {"ok": True, "summary": {}}

            def run_plan(self) -> dict:
                self.calls.append("plan")
                return {"ok": True, "summary": {}}

            def approve_latest_plan_execute(self) -> dict:
                self.calls.append("approve")
                return {"ok": True, "summary": {}}

            def run_dry_run(self) -> dict:
                self.calls.append("dry-run")
                return {"ok": True, "error_count": 0, "execute_allowed": True, "blocking_reasons": []}

            def run_execute(self, execute_approved: bool) -> dict:
                self.calls.append(f"execute:{execute_approved}")
                return {"ok": True, "summary": {}}

            def export_packets(self, output_dir: str) -> dict:
                self.calls.append(f"export:{output_dir}")
                return {"ok": True, "summary": {}, "path": output_dir}

            def import_review(self, input_path: str) -> dict:
                self.calls.append(f"import:{input_path}")
                return {"ok": True, "summary": {}}

        fake = FakeService()
        window = object.__new__(MainWindow)
        window.service = fake
        window.status_label = FakeLabel()
        window.progress_label = FakeLabel()
        window.failure_label = FakeLabel()
        window.resume_label = FakeLabel()
        window.execute_btn = FakeButton()
        window._refresh_folder_panels = lambda: None

        window._run_init()
        window._run_scan()
        window._run_summarize()
        window._run_enrich_places()
        window._run_analyze_duplicates()
        window._run_audit_dates()
        window._run_plan()
        window._approve_execute()
        window._run_dry_run()
        window._run_execute()
        fake_dialog = SimpleNamespace(
            getExistingDirectory=mock.Mock(return_value=str(TEST_TMP_ROOT / "packets")),
            getOpenFileName=mock.Mock(return_value=(str(TEST_TMP_ROOT / "review.json"), "")),
        )
        with mock.patch("photos.gui.QFileDialog", fake_dialog):
            window._export_packets()
            window._import_review()

        self.assertEqual(
            [
                "init",
                "scan",
                "summarize",
                "enrich-places",
                "analyze-duplicates",
                "audit-dates",
                "plan",
                "approve",
                "dry-run",
                "execute:True",
                f"export:{TEST_TMP_ROOT / 'packets'}",
                f"import:{TEST_TMP_ROOT / 'review.json'}",
            ],
            fake.calls,
        )
        self.assertTrue(window.execute_btn.enabled)
        self.assertEqual("failure=-", window.failure_label.text)


@unittest.skipUnless(os.environ.get("PHOTOS_SKIP_QT") != "1", "Qt tests disabled")
class TestPhase5MainWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            from PySide6.QtWidgets import QApplication
            from photos.gui import MainWindow
        except Exception as exc:  # pragma: no cover - depends on optional PySide6
            raise unittest.SkipTest(f"PySide6 unavailable: {exc}") from exc
        cls.QApplication = QApplication
        cls.MainWindow = MainWindow
        cls.app = QApplication.instance() or QApplication([])

    def test_buttons_call_service_actions(self) -> None:
        class FakeService:
            def __init__(self) -> None:
                self.calls: list[str] = []
                self.selection = SimpleNamespace(nodes={}, children={})

            def get_roots(self) -> dict[str, str]:
                return {"source_root": "S", "archive_root": "A"}

            def get_theme_preset(self, default: str = "default") -> str:
                return default

            def set_theme_preset(self, theme: str) -> None:
                self.calls.append(f"theme:{theme}")

            def can_execute(self) -> tuple[bool, list[str]]:
                return False, ["dry_run_not_run"]

            def workflow_state(self) -> dict[str, str]:
                return {"resume_state": "ready"}

            def load_folder_panels(self) -> dict[str, list[str]]:
                return {"all": [], "included": [], "excluded": [], "partial": []}

            def run_init(self) -> dict:
                self.calls.append("init")
                return {"ok": True, "summary": {}}

            def run_scan(self) -> dict:
                self.calls.append("scan")
                return {"ok": True, "summary": {}}

            def run_summarize(self) -> dict:
                self.calls.append("summarize")
                return {"ok": True, "summary": {}}

            def run_enrich_places(self) -> dict:
                self.calls.append("enrich-places")
                return {"ok": True, "summary": {}}

            def run_analyze_duplicates(self) -> dict:
                self.calls.append("analyze-duplicates")
                return {"ok": True, "summary": {}}

            def run_audit_dates(self) -> dict:
                self.calls.append("audit-dates")
                return {"ok": True, "summary": {}}

            def run_plan(self) -> dict:
                self.calls.append("plan")
                return {"ok": True, "summary": {}}

            def approve_latest_plan_execute(self) -> dict:
                self.calls.append("approve")
                return {"ok": True, "summary": {}}

            def run_dry_run(self) -> dict:
                self.calls.append("dry-run")
                return {"ok": True, "error_count": 0, "execute_allowed": True, "blocking_reasons": []}

            def run_execute(self, execute_approved: bool) -> dict:
                self.calls.append(f"execute:{execute_approved}")
                return {"ok": True, "summary": {}}

            def export_packets(self, output_dir: str) -> dict:
                self.calls.append(f"export:{output_dir}")
                return {"ok": True, "summary": {}, "path": output_dir}

            def import_review(self, input_path: str) -> dict:
                self.calls.append(f"import:{input_path}")
                return {"ok": True, "summary": {}}

        fake = FakeService()
        window = self.MainWindow(fake)
        try:
            window.init_btn.click()
            window.scan_btn.click()
            window.summary_btn.click()
            window.places_btn.click()
            window.duplicates_btn.click()
            window.audit_btn.click()
            window.plan_btn.click()
            window.approve_execute_btn.click()
            window.dry_run_btn.click()
            window.execute_btn.setEnabled(True)
            window.execute_btn.click()
            with mock.patch("photos.gui.QFileDialog.getExistingDirectory", return_value=str(TEST_TMP_ROOT / "packets")):
                window.export_btn.click()
            with mock.patch("photos.gui.QFileDialog.getOpenFileName", return_value=(str(TEST_TMP_ROOT / "review.json"), "")):
                window.import_btn.click()
            self.assertEqual(
                [
                    "init",
                    "scan",
                    "summarize",
                    "enrich-places",
                    "analyze-duplicates",
                    "audit-dates",
                    "plan",
                    "approve",
                    "dry-run",
                    "execute:True",
                    f"export:{TEST_TMP_ROOT / 'packets'}",
                    f"import:{TEST_TMP_ROOT / 'review.json'}",
                ],
                fake.calls,
            )
        finally:
            window.close()

    def test_tree_expand_collapse_does_not_toggle_selection(self) -> None:
        from photos.services import FolderSelectionModel

        db = new_db_path()
        service = PhotoOrganizerService(db)
        try:
            service.selection = FolderSelectionModel(
                [
                    {"path": "A", "parent_path": None},
                    {"path": "A/1", "parent_path": "A"},
                ]
            )
            window = self.MainWindow(service)
            try:
                before = service.selection.included_paths()
                item = window.tree.topLevelItem(0)
                window.tree.expandItem(item)
                window.tree.collapseItem(item)
                after = service.selection.included_paths()
                self.assertEqual(before, after)
            finally:
                window.close()
        finally:
            service.close()
            db.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
