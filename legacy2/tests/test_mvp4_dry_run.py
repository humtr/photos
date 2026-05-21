from __future__ import annotations

from pathlib import Path
import shutil
import uuid
import unittest
from unittest.mock import patch

from photos.approvals import approve_plan_execute
from photos.execution import dry_run
from photos.planning import build_plan
from photos.store import Store


def _setup_store(tmp_path: Path) -> tuple[Store, int, Path, Path]:
    db_path = tmp_path / "photos.sqlite"
    source_root = tmp_path / "source"
    archive_root = tmp_path / "archive"
    source_root.mkdir()
    archive_root.mkdir()
    media = source_root / "trip" / "a.jpg"
    media.parent.mkdir(parents=True)
    media.write_bytes(b"abc")
    store = Store(db_path)
    store.init_schema()
    scan_root_id = store.add_scan_root(str(source_root), str(archive_root))
    store.add_media_file(scan_root_id, media)
    return store, scan_root_id, source_root, archive_root


class TestMvp4DryRun(unittest.TestCase):
    def _workdir(self) -> Path:
        p = Path.cwd() / ".test-tmp" / f"photos-test-{uuid.uuid4().hex}"
        p.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(p, ignore_errors=True))
        return p

    def test_dry_run_blocks_without_approval(self) -> None:
        tmp_path = self._workdir()
        store, scan_root_id, _, _ = _setup_store(tmp_path)
        try:
            plan_id = build_plan(store, scan_root_id)
            result = dry_run(store, plan_id)
            self.assertGreaterEqual(result.error_count, 1)
            self.assertFalse(result.execute_allowed)
            self.assertIn("missing_execute_approval", result.blocking_reasons)
        finally:
            store.close()


    def test_dry_run_blocks_on_destination_collision(self) -> None:
        tmp_path = self._workdir()
        store, scan_root_id, _, archive_root = _setup_store(tmp_path)
        try:
            plan_id = build_plan(store, scan_root_id)
            approve_plan_execute(store, plan_id)
            (archive_root / "trip").mkdir(parents=True, exist_ok=True)
            (archive_root / "trip" / "a.jpg").write_bytes(b"already-there")
            result = dry_run(store, plan_id)
            self.assertFalse(result.execute_allowed)
            self.assertTrue(any(x.startswith("destination_exists:") for x in result.blocking_reasons))
        finally:
            store.close()


    def test_dry_run_cross_volume_capacity_validation(self) -> None:
        tmp_path = self._workdir()
        store, scan_root_id, _, _ = _setup_store(tmp_path)
        try:
            plan_id = build_plan(store, scan_root_id)
            approve_plan_execute(store, plan_id)
            with patch("photos.execution.get_volume_identity", lambda p: "src" if "source" in str(p) else "dst"):
                with patch("photos.execution.free_space_bytes", lambda p: 0):
                    result = dry_run(store, plan_id, reserve_bytes=1)
            self.assertEqual(result.transfer_method, "copy_verify_cleanup")
            self.assertFalse(result.execute_allowed)
            self.assertIn("insufficient_capacity_for_copy_verify_cleanup", result.blocking_reasons)
            self.assertEqual(len(result.capacity_checks), 1)
        finally:
            store.close()
