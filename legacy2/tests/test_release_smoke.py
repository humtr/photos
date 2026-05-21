from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TEST_TMP_ROOT = ROOT / ".test-tmp" / "release-smoke"
TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)


def new_db_path() -> Path:
    return TEST_TMP_ROOT / f"{uuid.uuid4().hex}.sqlite"


class TestReleaseSmoke(unittest.TestCase):
    def test_photos_app_smoke_mode(self) -> None:
        db = new_db_path()
        cmd = [sys.executable, "-m", "photos.app", "--db", str(db), "--smoke"]
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

    def test_packaged_script_entrypoint_smoke_mode(self) -> None:
        db = new_db_path()
        cmd = [sys.executable, str(SRC / "photos" / "app.py"), "--db", str(db), "--smoke"]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(SRC)
        cp = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, env=env, check=False)
        try:
            self.assertEqual(0, cp.returncode, cp.stderr)
            payload = json.loads(cp.stdout.strip())
            self.assertTrue(payload["ok"])
            self.assertEqual("gui-smoke", payload["command"])
        finally:
            db.unlink(missing_ok=True)

    def test_package_script_references_gui_entrypoint_and_compile_preflight(self) -> None:
        script = (ROOT / "scripts" / "package_windows.ps1").read_text(encoding="utf-8")
        self.assertIn('[string]$Entry = "src/photos/app.py"', script)
        self.assertIn('Get-ChildItem -Path "src/photos" -Filter "*.py" -File', script)
        self.assertIn("Sort-Object FullName", script)
        self.assertIn("python -m py_compile", script)

    def test_run_gui_script_uses_photos_app_module(self) -> None:
        script = (ROOT / "scripts" / "run_gui.ps1").read_text(encoding="utf-8")
        self.assertIn("python -m photos.app --db $Db", script)


if __name__ == "__main__":
    unittest.main()
