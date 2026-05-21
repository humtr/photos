from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import unittest
from pathlib import Path


class TestMVP2Duplicates(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(".test-tmp/test_mvp2").resolve()
        if self.root.exists():
            shutil.rmtree(self.root)
        (self.root / "sample-drive" / "A").mkdir(parents=True, exist_ok=True)
        (self.root / "sample-drive" / "B").mkdir(parents=True, exist_ok=True)
        (self.root / "sample-drive" / "C").mkdir(parents=True, exist_ok=True)
        (self.root / "archive").mkdir(parents=True, exist_ok=True)
        (self.root / "sample-drive" / "A" / "IMG_0001.JPG").write_bytes(b"a" * 1000)
        (self.root / "sample-drive" / "B" / "IMG_0001.JPG").write_bytes(b"b" * 200)
        (self.root / "sample-drive" / "A" / "IMG_9000.JPG").write_bytes(b"x" * 777)
        (self.root / "sample-drive" / "B" / "IMG_9000.JPG").write_bytes(b"x" * 777)
        (self.root / "sample-drive" / "C" / "IMG_9000.JPG").write_bytes(b"x" * 777)
        (self.root / "sample-drive" / "A" / "PAIR_1.JPG").write_bytes(b"p" * 111)
        (self.root / "sample-drive" / "B" / "PAIR_1.JPG").write_bytes(b"p" * 111)
        (self.root / "sample-drive" / "A" / "PAIR_2.JPG").write_bytes(b"q" * 222)
        (self.root / "sample-drive" / "B" / "PAIR_2.JPG").write_bytes(b"q" * 222)
        (self.root / "sample-drive" / "A" / "PAIR_3.JPG").write_bytes(b"r" * 333)
        (self.root / "sample-drive" / "B" / "PAIR_3.JPG").write_bytes(b"r" * 333)
        self.db = self.root / "photos.sqlite"

    def _run(self, *args: str) -> tuple[int, dict]:
        cmd = [sys.executable, "-m", "photos", *args]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path("src").resolve())
        p = subprocess.run(cmd, capture_output=True, text=True, check=False, env=env)
        return p.returncode, json.loads(p.stdout)

    def test_duplicate_classification(self) -> None:
        rc, _ = self._run("init", "--db", str(self.db))
        self.assertEqual(rc, 0)
        rc, _ = self._run(
            "scan",
            "--source",
            str(self.root / "sample-drive"),
            "--archive-root",
            str(self.root / "archive"),
            "--db",
            str(self.db),
        )
        self.assertEqual(rc, 0)
        rc, data = self._run("analyze-duplicates", "--db", str(self.db))
        self.assertEqual(rc, 0)
        self.assertTrue(data["ok"])
        self.assertGreater(data["summary"]["candidate_count"], 0)

        conn = sqlite3.connect(self.db)
        try:
            rows = conn.execute("SELECT candidate_type, evidence_json FROM duplicate_candidates").fetchall()
        finally:
            conn.close()
        kinds = {r[0] for r in rows}
        self.assertIn("same_name_collision", kinds)
        self.assertIn("transferred_derivative", kinds)
        self.assertIn("folder_pair_burst", kinds)
        for _, evidence_json in rows:
            json.loads(evidence_json)


if __name__ == "__main__":
    unittest.main()
