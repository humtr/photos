from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TEST_TMP_ROOT = ROOT / ".test-tmp" / "mvp6-gui"
TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from photos.services import FolderSelectionModel, PhotoOrganizerService  # noqa: E402
from photos.store import PhotoStore  # noqa: E402


def new_db_path() -> Path:
    return TEST_TMP_ROOT / f"{uuid.uuid4().hex}.sqlite"


class TestMVP6GuiShell(unittest.TestCase):
    @staticmethod
    def _close_sqlite_conn(conn: sqlite3.Connection | None) -> None:
        if conn is None:
            return
        try:
            conn.close()
        except sqlite3.Error:
            pass

    def test_tristate_partial_and_propagation(self) -> None:
        model = FolderSelectionModel(
            [
                {"path": "A", "parent_path": None},
                {"path": "A/1", "parent_path": "A"},
                {"path": "A/2", "parent_path": "A"},
            ]
        )
        model.set_state("A/1", True)
        self.assertIn("A", model.partial_paths())
        self.assertIn("A/1", model.included_paths())
        self.assertIn("A/2", model.excluded_paths())

    def test_execute_disabled_when_dry_run_has_errors(self) -> None:
        db = new_db_path()
        service = PhotoOrganizerService(db)
        try:
            dry = service.run_dry_run()
            self.assertGreater(dry["error_count"], 0)
            allowed, reasons = service.can_execute()
            self.assertFalse(allowed)
            self.assertIn("no_selected_folders", reasons)
        finally:
            self._close_sqlite_conn(service.store.conn)
            service.close()
            db.unlink(missing_ok=True)

    def test_paginated_query_uses_limit_offset(self) -> None:
        db = new_db_path()
        store = PhotoStore(db)
        conn2: sqlite3.Connection | None = None
        try:
            store.init_schema()
            for idx in range(120):
                store.conn.execute(
                    """
                    INSERT INTO media_files(path, folder_path, name, size_bytes, mtime_ns, existence_state, scan_root_id)
                    VALUES(?, ?, ?, ?, ?, 'seen', 1)
                    """,
                    (
                        f"/f/{idx}.jpg",
                        "/f",
                        f"{idx}.jpg",
                        100 + idx,
                        idx,
                    ),
                )
            store.conn.commit()

            statements: list[str] = []
            conn2 = sqlite3.connect(db)
            conn2.row_factory = sqlite3.Row
            conn2.set_trace_callback(statements.append)
            store.conn.close()
            store.conn = conn2

            rows, total = store.fetch_media_page(page=2, page_size=25)
            self.assertEqual(25, len(rows))
            self.assertEqual(120, total)
            sql = "\n".join(statements).upper()
            self.assertIn("LIMIT", sql)
            self.assertIn("OFFSET", sql)
            self.assertNotIn("SELECT * FROM MEDIA_FILES", sql)
        finally:
            self._close_sqlite_conn(store.conn)
            store.close()
            self._close_sqlite_conn(conn2)
            db.unlink(missing_ok=True)

    def test_gui_smoke_mode(self) -> None:
        db = new_db_path()
        cmd = [sys.executable, "-m", "photos.gui", "--db", str(db), "--smoke"]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(SRC)
        cp = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, env=env, check=False)
        try:
            self.assertEqual(0, cp.returncode, cp.stderr)
            payload = json.loads(cp.stdout.strip())
            self.assertEqual(1, payload["schema_version"])
            self.assertTrue(payload["ok"])
            self.assertEqual("gui-smoke", payload["command"])
        finally:
            db.unlink(missing_ok=True)

    def test_synthetic_large_db_page_intent(self) -> None:
        # Lightweight synthetic path to prove paged access shape without full preload.
        db = new_db_path()
        service = PhotoOrganizerService(db)
        try:
            rows = (
                (f"/bulk/{i}.jpg", "/bulk", f"{i}.jpg", i + 10, i)
                for i in range(20_000)
            )
            service.store.conn.executemany(
                """
                INSERT INTO media_files(path, folder_path, name, size_bytes, mtime_ns, existence_state, scan_root_id)
                VALUES(?, ?, ?, ?, ?, 'seen', 1)
                """,
                rows,
            )
            service.store.conn.commit()
            page = service.page_media(page=1, page_size=10_000)
            self.assertEqual(10_000, len(page["rows"]))
            self.assertEqual(20_000, page["total"])
        finally:
            self._close_sqlite_conn(service.store.conn)
            service.close()
            db.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
