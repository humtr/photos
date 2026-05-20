from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import unittest
from pathlib import Path


class TestMVP3Packets(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(".test-tmp/test_mvp3").resolve()
        if self.root.exists():
            shutil.rmtree(self.root)
        (self.root / "sample-drive" / "2024-03-SEOUL").mkdir(parents=True, exist_ok=True)
        (self.root / "archive").mkdir(parents=True, exist_ok=True)
        (self.root / "packets").mkdir(parents=True, exist_ok=True)
        (self.root / "sample-drive" / "2024-03-SEOUL" / "IMG_1001.JPG").write_bytes(b"a" * 120)
        (self.root / "sample-drive" / "2024-03-SEOUL" / "IMG_1002.JPG").write_bytes(b"b" * 140)
        self.db = self.root / "photos.sqlite"

    def _run(self, *args: str) -> tuple[int, dict]:
        cmd = [sys.executable, "-m", "photos", *args]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path("src").resolve())
        p = subprocess.run(cmd, capture_output=True, text=True, check=False, env=env)
        return p.returncode, json.loads(p.stdout)

    def test_packet_export_and_review_import_validation(self) -> None:
        self._run("init", "--db", str(self.db))
        self._run(
            "scan",
            "--source",
            str(self.root / "sample-drive"),
            "--archive-root",
            str(self.root / "archive"),
            "--db",
            str(self.db),
        )
        self._run("analyze-duplicates", "--db", str(self.db))
        self._run("audit-dates", "--db", str(self.db))
        rc, data = self._run("export-folder-packets", "--db", str(self.db), "--output", str(self.root / "packets"), "--gps-mode", "summary")
        self.assertEqual(rc, 0)
        self.assertTrue(data["ok"])
        self.assertGreaterEqual(data["summary"]["packet_count"], 1)
        self.assertTrue(data["artifacts"])

        valid = {
            "schema_version": 1,
            "review_type": "folder_semantic_review",
            "created_at": "2026-01-01T00:00:00Z",
            "source_packet_sha256": "x",
            "items": [
                {
                    "target_type": "folder",
                    "target_path": "2024-03-SEOUL",
                    "proposal_type": "folder_rename",
                    "confidence": 0.8,
                    "proposal": {"new_name": "2024-03-SEOUL-TRIP"},
                    "evidence": {"reason": "structure"},
                    "requires_user_approval": True,
                }
            ],
        }
        invalid = {
            "schema_version": 1,
            "review_type": "folder_semantic_review",
            "created_at": "2026-01-01T00:00:00Z",
            "source_packet_sha256": "x",
            "items": [
                {
                    "target_type": "folder",
                    "target_path": "Z:/outside",
                    "proposal_type": "folder_rename",
                    "confidence": 0.8,
                    "proposal": {"new_name": "bad"},
                    "evidence": {"reason": "bad"},
                    "requires_user_approval": True,
                }
            ],
        }
        valid_path = self.root / "valid_review.json"
        invalid_path = self.root / "invalid_review.json"
        valid_path.write_text(json.dumps(valid), encoding="utf-8")
        invalid_path.write_text(json.dumps(invalid), encoding="utf-8")

        rc, data = self._run("import-folder-review", "--db", str(self.db), "--input", str(valid_path))
        self.assertEqual(rc, 0)
        self.assertTrue(data["ok"])

        conn = sqlite3.connect(self.db)
        status = conn.execute("SELECT status FROM llm_review_items ORDER BY id DESC LIMIT 1").fetchone()[0]
        self.assertEqual(status, "pending_approval")

        rc, data = self._run("import-folder-review", "--db", str(self.db), "--input", str(invalid_path))
        self.assertNotEqual(rc, 0)
        self.assertFalse(data["ok"])
        self.assertTrue(data["errors"])


if __name__ == "__main__":
    unittest.main()
