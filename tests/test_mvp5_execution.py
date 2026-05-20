from __future__ import annotations

import json
from pathlib import Path
import shutil
import uuid
import unittest

from photos.approvals import approve_plan_execute
from photos.execution import execute_plan
from photos.planning import build_plan
from photos.store import Store


def _setup(tmp_path: Path) -> tuple[Store, int, Path, Path, Path, Path]:
    db_path = tmp_path / "photos.sqlite"
    source_root = tmp_path / "source"
    archive_root = tmp_path / "archive"
    manifest_dir = tmp_path / ".photos-data" / "manifests"
    reports_dir = tmp_path / ".photos-data" / "reports"
    source_root.mkdir()
    archive_root.mkdir()
    f = source_root / "album" / "img1.jpg"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"photo-1")
    store = Store(db_path)
    store.init_schema()
    scan_root_id = store.add_scan_root(str(source_root), str(archive_root))
    store.add_media_file(scan_root_id, f)
    return store, scan_root_id, source_root, archive_root, manifest_dir, reports_dir


class TestMvp5Execution(unittest.TestCase):
    def _workdir(self) -> Path:
        p = Path.cwd() / ".test-tmp" / f"photos-test-{uuid.uuid4().hex}"
        p.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(p, ignore_errors=True))
        return p

    def test_execute_requires_gate_flag(self) -> None:
        tmp_path = self._workdir()
        store, scan_root_id, _, _, manifest_dir, reports_dir = _setup(tmp_path)
        try:
            plan_id = build_plan(store, scan_root_id)
            approve_plan_execute(store, plan_id)
            with self.assertRaises(ValueError) as exc:
                execute_plan(store, plan_id, False, manifest_dir=manifest_dir, reports_dir=reports_dir)
            self.assertIn("--execute-approved", str(exc.exception))
        finally:
            store.close()


    def test_same_volume_execute_writes_manifest_and_moves(self) -> None:
        tmp_path = self._workdir()
        store, scan_root_id, source_root, archive_root, manifest_dir, reports_dir = _setup(tmp_path)
        try:
            plan_id = build_plan(store, scan_root_id)
            approve_plan_execute(store, plan_id)
            source_file = source_root / "album" / "img1.jpg"
            result = execute_plan(store, plan_id, True, manifest_dir=manifest_dir, reports_dir=reports_dir)
            self.assertEqual(result.failed_count, 0)
            self.assertEqual(result.held_count, 0)
            self.assertEqual(result.committed_count, 1)
            self.assertFalse(source_file.exists())
            moved_path = archive_root / "album" / "img1.jpg"
            self.assertTrue(moved_path.exists())
            manifest_path = Path(result.manifest_path)
            self.assertTrue(manifest_path.exists())
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], 1)
            self.assertEqual(payload["batch_id"], result.batch_id)
            self.assertEqual(len(payload["items"]), 1)
            rollback_path = reports_dir / f"batch_{result.batch_id}.rollback.json"
            self.assertTrue(rollback_path.exists())
        finally:
            store.close()


    def test_execute_blocks_when_source_changes_before_run(self) -> None:
        tmp_path = self._workdir()
        store, scan_root_id, source_root, _, manifest_dir, reports_dir = _setup(tmp_path)
        try:
            plan_id = build_plan(store, scan_root_id)
            approve_plan_execute(store, plan_id)
            source_file = source_root / "album" / "img1.jpg"
            source_file.write_bytes(b"changed")
            with self.assertRaises(ValueError) as exc:
                execute_plan(store, plan_id, True, manifest_dir=manifest_dir, reports_dir=reports_dir)
            self.assertIn("dry-run blocked execution", str(exc.exception))
            self.assertTrue(source_file.exists())
        finally:
            store.close()
