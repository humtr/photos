from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import photos.execution as execution
from photos.database import utc_now
from photos.services import PhotoOrganizerService


class BoundedExecutionTests(unittest.TestCase):
    def test_progress_cadence_helper_is_bounded(self) -> None:
        self.assertTrue(execution._should_emit_progress(1, 5000))
        self.assertFalse(execution._should_emit_progress(999, 5000))
        self.assertTrue(execution._should_emit_progress(1000, 5000))
        self.assertTrue(execution._should_emit_progress(5000, 5000))

    def test_public_plan_creation_pages_thousands_and_bounds_dry_run_samples(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            media = base / "media"
            archive = base / "archive"
            for index in range(2005):
                path = media / f"folder-{index:04d}" / "same.JPG"
                path.parent.mkdir(parents=True)
                path.write_bytes(b"x")

            with PhotoOrganizerService(base / "photos.sqlite") as service:
                scanned = service.scan_inventory(media, hash_files=False)
                self.assertTrue(scanned["ok"], scanned)
                plan = service.create_archive_plan(archive)
                self.assertTrue(plan["ok"], plan)
                plan_id = plan["data"]["plan_id"]
                self.assertEqual(plan["data"]["action_count"], 2005)

                first_page = service.list_plan_actions(plan_id, limit=25)
                last_page = service.list_plan_actions(plan_id, limit=25, offset=2000)
                self.assertEqual(first_page["data"]["total"], 2005)
                self.assertEqual(len(first_page["data"]["rows"]), 25)
                self.assertEqual(len(last_page["data"]["rows"]), 5)
                destinations = {
                    row["destination_path"]
                    for row in service.con.execute(
                        "SELECT destination_path FROM plan_actions WHERE plan_id = ?",
                        (plan_id,),
                    )
                }
                self.assertEqual(len(destinations), 2005)

                service.approve_plan(plan_id, approved=True)
                gate = service.can_execute(plan_id)
                self.assertTrue(gate["ok"], gate)
                self.assertTrue(gate["data"]["can_execute"], gate)
                self.assertEqual(gate["data"]["dry_run"]["action_count"], 2005)
                self.assertEqual(len(gate["data"]["dry_run"]["samples"]), 20)

    def test_streamed_manifest_is_parseable_for_thousands_of_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            archive = base / "archive"
            archive.mkdir()
            with PhotoOrganizerService(base / "photos.sqlite") as service:
                con = service.con
                plan_cur = con.execute(
                    """
                    INSERT INTO organize_plans(strategy, archive_root, status, created_at, summary_json)
                    VALUES('bounded-test', ?, 'executed', ?, '{}')
                    """,
                    (str(archive), utc_now()),
                )
                plan_id = int(plan_cur.lastrowid)
                batch_cur = con.execute(
                    """
                    INSERT INTO execution_batches(
                        plan_id, transfer_method, estimated_bytes, status,
                        started_at, finished_at, summary_json
                    )
                    VALUES(?, 'copy_verify_unlink', 2505, 'completed', ?, ?, '{}')
                    """,
                    (plan_id, utc_now(), utc_now()),
                )
                batch_id = int(batch_cur.lastrowid)
                for index in range(2505):
                    action_cur = con.execute(
                        """
                        INSERT INTO plan_actions(
                            plan_id, source_path, destination_path, action_type,
                            expected_size, expected_mtime_ns, status, reason_json
                        )
                        VALUES(?, ?, ?, 'move_after_approval', 1, 1, 'completed', '{}')
                        """,
                        (plan_id, f"/source/{index}", str(archive / f"{index}.jpg")),
                    )
                    action_id = int(action_cur.lastrowid)
                    item_cur = con.execute(
                        """
                        INSERT INTO batch_items(
                            batch_id, plan_action_id, source_path, destination_path, status
                        )
                        VALUES(?, ?, ?, ?, 'completed')
                        """,
                        (batch_id, action_id, f"/source/{index}", str(archive / f"{index}.jpg")),
                    )
                    con.execute(
                        """
                        INSERT INTO transfer_verifications(
                            batch_item_id, destination_size, destination_mtime_ns,
                            verification_status, verified_at, details_json
                        )
                        VALUES(?, 1, 1, 'verified', ?, '{}')
                        """,
                        (int(item_cur.lastrowid), utc_now()),
                    )
                con.commit()

                result = execution._write_batch_manifest(con, batch_id)
                self.assertEqual(result["item_count"], 2505)
                self.assertEqual(result["total_bytes"], 2505)
                manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
                self.assertEqual(manifest["item_count"], 2505)
                self.assertEqual(len(manifest["items"]), 2505)
                self.assertEqual(manifest["items"][0]["plan_action_id"], 1)
                self.assertEqual(len(manifest["items"][-1]["verifications"]), 1)
                self.assertTrue(service.validate_batch_manifest(batch_id)["data"]["valid"])


if __name__ == "__main__":
    unittest.main()
