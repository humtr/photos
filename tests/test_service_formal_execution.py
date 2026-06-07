from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from photos.services import PhotoOrganizerService


def write_file(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


class ServiceFormalExecutionTests(unittest.TestCase):
    def make_sample_media(self, root: Path) -> list[Path]:
        files = [
            root / "2020-trip" / "20200101_IMG_0001.ARW",
            root / "2020-trip" / "20200101_IMG_0001.JPG",
            root / "conflict-2022" / "20190101_conflict.JPG",
            root / "dupes" / "dup_a.JPG",
            root / "other" / "dup_b.JPG",
            root / "video" / "clip.MP4",
        ]
        payloads = [b"raw-one", b"jpg-one", b"date-conflict", b"duplicate-content", b"duplicate-content", b"video-bytes"]
        for path, payload in zip(files, payloads, strict=True):
            write_file(path, payload)
        return files

    def test_approval_gated_execution_manifest_and_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            media = base / "media"
            originals = self.make_sample_media(media)
            archive = base / "archive"

            with PhotoOrganizerService(base / "photos.sqlite") as service:
                scan = service.scan_inventory(media, hash_files=True)
                self.assertTrue(scan["ok"], scan)

                plan = service.create_archive_plan(archive)
                self.assertTrue(plan["ok"], plan)
                plan_id = plan["data"]["plan_id"]
                actions = service.list_plan_actions(plan_id)
                self.assertTrue(actions["ok"], actions)
                self.assertEqual(actions["data"]["total"], len(originals))
                destinations = [Path(row["destination_path"]) for row in actions["data"]["rows"]]

                denied = service.execute_plan(plan_id, execute_approved=True)
                self.assertTrue(denied["ok"], denied)
                self.assertFalse(denied["data"]["executed"])
                self.assertIn("missing_execute_approval", denied["data"]["blocking_reasons"])

                approval = service.approve_plan(plan_id, approved=True, note="unit test approval")
                self.assertTrue(approval["ok"], approval)
                gate = service.can_execute(plan_id)
                self.assertTrue(gate["ok"], gate)
                self.assertTrue(gate["data"]["can_execute"], gate)

                held = service.execute_plan(plan_id, execute_approved=False)
                self.assertTrue(held["ok"], held)
                self.assertFalse(held["data"]["executed"])
                self.assertIn("runtime_execute_confirmation_missing", held["data"]["blocking_reasons"])

                executed = service.execute_plan(plan_id, execute_approved=True)
                self.assertTrue(executed["ok"], executed)
                self.assertTrue(executed["data"]["executed"], executed)
                self.assertEqual(executed["data"]["completed_count"], len(originals))
                manifest_path = Path(executed["data"]["manifest_path"])
                self.assertTrue(manifest_path.exists())
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                self.assertEqual(manifest["schema_version"], "formal-execution-manifest-v1")
                self.assertTrue(manifest["safety"]["source_removed_only_after_verified_copy"])

                self.assertTrue(all(not path.exists() for path in originals))
                self.assertTrue(all(path.exists() for path in destinations))
                after_execute_page = service.list_media(page=1, page_size=20)
                self.assertTrue(after_execute_page["ok"], after_execute_page)
                active_paths = {row["path"] for row in after_execute_page["data"]["rows"]}
                self.assertTrue(all(str(path) in active_paths for path in destinations))

                batches = service.list_execution_batches(plan_id=plan_id)
                self.assertTrue(batches["ok"], batches)
                self.assertGreaterEqual(batches["data"]["total"], 1)
                batch_id = executed["data"]["batch_id"]
                items = service.list_batch_items(batch_id)
                self.assertTrue(items["ok"], items)
                self.assertEqual(items["data"]["total"], len(originals))

                rollback_held = service.rollback_batch(batch_id, execute_approved=False)
                self.assertTrue(rollback_held["ok"], rollback_held)
                self.assertFalse(rollback_held["data"]["rolled_back"])
                self.assertIn("runtime_rollback_confirmation_missing", rollback_held["data"]["blocking_reasons"])

                rollback = service.rollback_batch(batch_id, execute_approved=True)
                self.assertTrue(rollback["ok"], rollback)
                self.assertTrue(rollback["data"]["rolled_back"], rollback)
                self.assertTrue(Path(rollback["data"]["manifest_path"]).exists())
                self.assertTrue(all(path.exists() for path in originals))
                self.assertTrue(all(not path.exists() for path in destinations))


if __name__ == "__main__":
    unittest.main()
