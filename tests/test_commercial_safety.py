from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import photos.execution as execution
from photos.services import PhotoOrganizerService


def write_file(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


class CommercialSafetyTests(unittest.TestCase):
    def make_media(self, root: Path, count: int = 4) -> list[Path]:
        files: list[Path] = []
        for idx in range(count):
            path = root / "camera" / f"2020010{idx}_IMG_{idx:04d}.JPG"
            write_file(path, f"payload-{idx}".encode())
            files.append(path)
        return files

    def test_archive_root_inside_source_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            media = base / "media"
            self.make_media(media, count=2)
            archive_inside_media = media / "archive"
            with PhotoOrganizerService(base / "photos.sqlite") as service:
                self.assertTrue(service.scan_inventory(media, hash_files=True)["ok"])
                plan = service.create_archive_plan(archive_inside_media)
                self.assertTrue(plan["ok"], plan)
                service.approve_plan(plan["data"]["plan_id"], approved=True)
                gate = service.can_execute(plan["data"]["plan_id"])
                self.assertTrue(gate["ok"], gate)
                self.assertFalse(gate["data"]["can_execute"])
                self.assertIn(
                    "archive_root_inside_active_source_root",
                    gate["data"]["blocking_reasons"],
                )

    def test_manifest_validation_integrity_and_operation_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            media = base / "media"
            self.make_media(media, count=3)
            archive = base / "archive"
            with PhotoOrganizerService(base / "photos.sqlite") as service:
                self.assertTrue(service.scan_inventory(media, hash_files=True)["ok"])
                plan = service.create_archive_plan(archive)
                plan_id = plan["data"]["plan_id"]
                service.approve_plan(plan_id, approved=True)

                # Simulate another process already mutating the library.
                service.con.execute(
                    """
                    INSERT INTO operation_locks(lock_name, owner, acquired_at, details_json)
                    VALUES('filesystem-mutation', 'unit-test-owner', 'now', '{}')
                    """
                )
                service.con.commit()
                locked = service.execute_plan(plan_id, execute_approved=True)
                self.assertFalse(locked["ok"], locked)
                service.con.execute("DELETE FROM operation_locks WHERE lock_name = 'filesystem-mutation'")
                service.con.commit()

                executed = service.execute_plan(plan_id, execute_approved=True)
                self.assertTrue(executed["ok"], executed)
                self.assertTrue(executed["data"]["executed"], executed)
                self.assertTrue(executed["data"]["database_backup"]["created"])
                self.assertTrue(Path(executed["data"]["database_backup"]["path"]).exists())

                manifest = service.validate_batch_manifest(
                    executed["data"]["batch_id"],
                    verify_files=True,
                )
                self.assertTrue(manifest["ok"], manifest)
                self.assertTrue(manifest["data"]["valid"], manifest)

                integrity = service.integrity_check()
                self.assertTrue(integrity["ok"], integrity)
                self.assertEqual(integrity["data"]["status"], "ok")

    def test_partial_failure_can_be_reconciled_and_resumed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            media = base / "media"
            originals = self.make_media(media, count=4)
            archive = base / "archive"
            original_copy = execution._copy_verify_replace
            call_count = {"count": 0}

            def flaky_once(**kwargs):
                call_count["count"] += 1
                if call_count["count"] == 2:
                    raise OSError("simulated transient copy failure")
                return original_copy(**kwargs)

            with PhotoOrganizerService(base / "photos.sqlite") as service:
                self.assertTrue(service.scan_inventory(media, hash_files=True)["ok"])
                plan = service.create_archive_plan(archive)
                plan_id = plan["data"]["plan_id"]
                service.approve_plan(plan_id, approved=True)

                with patch("photos.execution._copy_verify_replace", side_effect=flaky_once):
                    partial = service.execute_plan(plan_id, execute_approved=True)
                self.assertTrue(partial["ok"], partial)
                self.assertEqual(partial["data"]["failed_count"], 1)
                self.assertGreaterEqual(partial["data"]["completed_count"], 1)

                batch_id = partial["data"]["batch_id"]
                reconciled = service.reconcile_batch(batch_id)
                self.assertTrue(reconciled["ok"], reconciled)
                self.assertTrue(reconciled["data"]["reconciled"], reconciled)
                self.assertGreaterEqual(reconciled["data"]["retryable_count"], 1)

                held = service.resume_batch(batch_id, execute_approved=False)
                self.assertTrue(held["ok"], held)
                self.assertFalse(held["data"]["resumed"])

                resumed = service.resume_batch(batch_id, execute_approved=True)
                self.assertTrue(resumed["ok"], resumed)
                self.assertTrue(resumed["data"]["resumed"], resumed)
                self.assertTrue(all(not path.exists() for path in originals))
                final_manifest = service.validate_batch_manifest(
                    resumed["data"]["execution"]["batch_id"],
                    verify_files=True,
                )
                self.assertTrue(final_manifest["data"]["valid"], final_manifest)


if __name__ == "__main__":
    unittest.main()
