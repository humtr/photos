from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path


class TestMVP1Scan(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(".test-tmp/test_mvp1").resolve()
        if self.root.exists():
            shutil.rmtree(self.root)
        (self.root / "sample-drive" / "2024-01-trip").mkdir(parents=True, exist_ok=True)
        (self.root / "sample-drive" / ".thumbnail").mkdir(parents=True, exist_ok=True)
        (self.root / "archive").mkdir(parents=True, exist_ok=True)
        (self.root / "sample-drive" / "2024-01-trip" / "IMG_0001.JPG").write_bytes(b"a" * 100)
        (self.root / "sample-drive" / "2024-01-trip" / "IMG_0002.JPG").write_bytes(b"b" * 120)
        (self.root / "sample-drive" / ".thumbnail" / "thumb_1.jpg").write_bytes(b"c" * 50)
        self.db = self.root / "photos.sqlite"

    def _run(self, *args: str) -> tuple[int, dict]:
        cmd = [sys.executable, "-m", "photos", *args]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path("src").resolve())
        p = subprocess.run(cmd, capture_output=True, text=True, check=False, env=env)
        data = json.loads(p.stdout)
        return p.returncode, data

    def test_scan_and_summarize_and_missing_state(self) -> None:
        rc, data = self._run("init", "--db", str(self.db))
        self.assertEqual(rc, 0)
        self.assertTrue(data["ok"])

        rc, data = self._run(
            "scan",
            "--source",
            str(self.root / "sample-drive"),
            "--archive-root",
            str(self.root / "archive"),
            "--db",
            str(self.db),
        )
        self.assertEqual(rc, 0)
        self.assertTrue(data["ok"])
        self.assertEqual(data["summary"]["file_count"], 3)

        rc, data = self._run("summarize", "--db", str(self.db))
        self.assertEqual(rc, 0)
        self.assertTrue(data["ok"])
        self.assertGreaterEqual(data["summary"]["folder_count"], 2)
        self.assertEqual(data["summary"]["file_count"], 3)
        self.assertIn(".jpg", data["summary"]["extension_counts"])
        self.assertIn("cache_thumbnail", data["summary"]["attention_flag_counts"])

        (self.root / "sample-drive" / "2024-01-trip" / "IMG_0002.JPG").unlink()
        rc, data = self._run(
            "scan",
            "--source",
            str(self.root / "sample-drive"),
            "--archive-root",
            str(self.root / "archive"),
            "--db",
            str(self.db),
        )
        self.assertEqual(rc, 0)
        self.assertTrue(data["ok"])

        rc, data = self._run("summarize", "--db", str(self.db))
        self.assertEqual(rc, 0)
        self.assertEqual(data["summary"]["file_count"], 2)


if __name__ == "__main__":
    unittest.main()
