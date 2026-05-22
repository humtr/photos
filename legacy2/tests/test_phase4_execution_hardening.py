from __future__ import annotations

from pathlib import Path
import shutil
import uuid
import unittest
from unittest import mock

from photos.approvals import approve_plan_execute
import photos.execution as execution_module
from photos.execution import dry_run, execute_plan
from photos.planning import build_plan
from photos.store import Store
from photos.utils import json_dumps


def _setup(tmp_path: Path) -> tuple[Store, int, Path, Path, Path, Path]:
    db_path = tmp_path / "photos.sqlite"
    source_root = tmp_path / "source"
    archive_root = tmp_path / "archive"
    manifest_dir = tmp_path / ".photos-data" / "manifests"
    reports_dir = tmp_path / ".photos-data" / "reports"
    source_root.mkdir()
    archive_root.mkdir()
    media = source_root / "album" / "img1.jpg"
    media.parent.mkdir(parents=True)
    media.write_bytes(b"photo-1")
    store = Store(db_path)
    store.init_schema()
    scan_root_id = store.add_scan_root(str(source_root), str(archive_root))
    store.add_media_file(scan_root_id, media)
    return store, scan_root_id, source_root, archive_root, manifest_dir, reports_dir


class TestPhase4ExecutionHardening(unittest.TestCase):
    def _workdir(self) -> Path:
        root = Path.cwd() / ".test-tmp" / f"phase4-{uuid.uuid4().hex}"
        root.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        return root

    def test_approved_metadata_suggestion_plans_metadata_override_transfer_action(self) -> None:
        tmp_path = self._workdir()
        store, scan_root_id, source_root, archive_root, _, _ = _setup(tmp_path)
        try:
            source_file = source_root / "album" / "img1.jpg"
            store.conn.execute(
                """
                INSERT INTO metadata_edit_suggestions(target_type,target_path,proposed_value,source,status,reason_json)
                VALUES(?,?,?,?,?,?)
                """,
                ("media_file", str(source_file), "2020-05-04", "test", "approved", "{}"),
            )
            store.conn.commit()

            plan_id = build_plan(store, scan_root_id)

            action = store.list_plan_actions(plan_id)[0]
            self.assertEqual(str(action["action_type"]), "metadata_override")
            self.assertEqual(Path(str(action["destination_path"])), archive_root / "2020-05-04" / "img1.jpg")
            self.assertEqual(str(action["source_path"]), str(source_file))
        finally:
            store.close()

    def test_metadata_write_candidate_is_not_executable(self) -> None:
        tmp_path = self._workdir()
        store, scan_root_id, source_root, archive_root, _, _ = _setup(tmp_path)
        try:
            plan_id = store.create_plan(scan_root_id, "test", str(archive_root), {"total_actions": 1})
            source_file = source_root / "album" / "img1.jpg"
            destination = archive_root / "album" / "img1.jpg"
            store.insert_plan_actions(
                [
                    (
                        plan_id,
                        str(source_file),
                        str(destination),
                        "metadata_write_candidate",
                        source_file.stat().st_size,
                        source_file.stat().st_mtime_ns,
                        "pending",
                        json_dumps({"reason": "metadata_write_candidate"}),
                    )
                ]
            )
            approve_plan_execute(store, plan_id)

            result = dry_run(store, plan_id)

            self.assertTrue(result.execute_allowed)
            self.assertEqual(result.batch_summaries[0]["action_count"], 0)
        finally:
            store.close()

    def test_dry_run_blocks_path_length(self) -> None:
        tmp_path = self._workdir()
        store, scan_root_id, _, _, _, _ = _setup(tmp_path)
        try:
            plan_id = build_plan(store, scan_root_id)
            approve_plan_execute(store, plan_id)
            action = store.list_plan_actions(plan_id)[0]
            long_destination = Path(str(action["destination_path"]) + ("x" * 280))
            store.conn.execute("UPDATE plan_actions SET destination_path=? WHERE id=?", (str(long_destination), int(action["id"])))
            store.conn.commit()

            result = dry_run(store, plan_id)

            self.assertFalse(result.execute_allowed)
            self.assertTrue(any(reason.startswith("path_too_long:") for reason in result.blocking_reasons))
        finally:
            store.close()

    def test_dry_run_blocks_reparse_risk(self) -> None:
        tmp_path = self._workdir()
        store, scan_root_id, _, _, _, _ = _setup(tmp_path)
        try:
            plan_id = build_plan(store, scan_root_id)
            approve_plan_execute(store, plan_id)

            with mock.patch("photos.execution._has_reparse_risk", return_value=True):
                result = dry_run(store, plan_id)

            self.assertFalse(result.execute_allowed)
            self.assertIn("reparse_point_risk", result.blocking_reasons)
        finally:
            store.close()

    def test_execute_revalidates_path_length_before_transfer(self) -> None:
        tmp_path = self._workdir()
        store, scan_root_id, source_root, _, manifest_dir, reports_dir = _setup(tmp_path)
        try:
            plan_id = build_plan(store, scan_root_id)
            approve_plan_execute(store, plan_id)
            dry = dry_run(store, plan_id)
            self.assertTrue(dry.execute_allowed)
            source_file = source_root / "album" / "img1.jpg"

            with mock.patch("photos.execution.dry_run", return_value=dry), mock.patch(
                "photos.execution._is_path_too_long", return_value=True
            ):
                result = execute_plan(store, plan_id, True, manifest_dir=manifest_dir, reports_dir=reports_dir)

            self.assertEqual(result.held_count, 1)
            self.assertEqual(result.committed_count, 0)
            self.assertTrue(source_file.exists())
        finally:
            store.close()

    def test_cross_volume_copy_verifies_and_leaves_source_intact(self) -> None:
        tmp_path = self._workdir()
        store, scan_root_id, source_root, archive_root, manifest_dir, reports_dir = _setup(tmp_path)
        try:
            plan_id = build_plan(store, scan_root_id)
            approve_plan_execute(store, plan_id)
            source_file = source_root / "album" / "img1.jpg"

            def _volume(path: Path) -> str:
                return "src" if "source" in str(path) else "dst"

            with mock.patch("photos.execution.get_volume_identity", side_effect=_volume), mock.patch(
                "photos.execution.is_same_volume", return_value=False
            ):
                result = execute_plan(store, plan_id, True, manifest_dir=manifest_dir, reports_dir=reports_dir)

            self.assertEqual(result.transfer_method, "copy_verify_cleanup")
            self.assertEqual(result.committed_count, 1)
            self.assertTrue(source_file.exists())
            self.assertTrue((archive_root / "album" / "img1.jpg").exists())
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
