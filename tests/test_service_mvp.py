from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from photos.services import PhotoOrganizerService, service_smoke


def write_file(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


class ServiceMvpTests(unittest.TestCase):
    def make_sample_media(self, root: Path) -> None:
        write_file(root / "2020-trip" / "20200101_IMG_0001.ARW", b"raw-one")
        write_file(root / "2020-trip" / "20200101_IMG_0001.JPG", b"jpg-one")
        write_file(root / "conflict-2022" / "20190101_conflict.JPG", b"date-conflict")
        write_file(root / "dupes" / "dup_a.JPG", b"duplicate-content")
        write_file(root / "other" / "dup_b.JPG", b"duplicate-content")
        write_file(root / "video" / "clip.MP4", b"video-bytes")

    def test_service_boundary_scan_page_candidates_and_approval_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            media = base / "media"
            self.make_sample_media(media)
            archive = base / "archive"

            with PhotoOrganizerService(base / "photos.sqlite") as service:
                scan = service.scan_inventory(media, hash_files=True)
                self.assertTrue(scan["ok"], scan)
                self.assertEqual(scan["data"]["scanned"], 6)
                self.assertGreaterEqual(scan["data"]["folder_count"], 1)

                page = service.list_media(page=1, page_size=3)
                self.assertTrue(page["ok"], page)
                self.assertEqual(page["data"]["page"], 1)
                self.assertEqual(page["data"]["page_size"], 3)
                self.assertEqual(page["data"]["total"], 6)
                self.assertTrue(page["data"]["has_next"])

                dup_refresh = service.refresh_duplicate_candidates()
                self.assertTrue(dup_refresh["ok"], dup_refresh)
                self.assertGreaterEqual(dup_refresh["data"]["candidate_count"], 1)
                duplicates = service.list_duplicate_candidates()
                self.assertTrue(duplicates["ok"], duplicates)
                self.assertGreaterEqual(duplicates["data"]["total"], 1)

                date_refresh = service.refresh_date_audit()
                self.assertTrue(date_refresh["ok"], date_refresh)
                self.assertGreaterEqual(date_refresh["data"]["group_count"], 1)
                audits = service.list_date_audits()
                self.assertTrue(audits["ok"], audits)
                self.assertGreaterEqual(audits["data"]["total"], 1)

                plan = service.create_archive_plan(archive)
                self.assertTrue(plan["ok"], plan)
                self.assertEqual(plan["data"]["action_count"], 6)
                dry = service.dry_run_plan(plan["data"]["plan_id"])
                self.assertTrue(dry["ok"], dry)
                self.assertFalse(dry["data"]["destructive_action_performed"])
                self.assertIn("missing_execute_approval", dry["warnings"])

                gate = service.can_execute(plan["data"]["plan_id"])
                self.assertTrue(gate["ok"], gate)
                self.assertFalse(gate["data"]["can_execute"])
                self.assertIn("missing_execute_approval", gate["data"]["blocking_reasons"])

                approval = service.approve_plan(plan["data"]["plan_id"], approved=True, note="smoke approval")
                self.assertTrue(approval["ok"], approval)
                approved_gate = service.can_execute(plan["data"]["plan_id"])
                self.assertTrue(approved_gate["ok"], approved_gate)
                self.assertTrue(approved_gate["data"]["can_execute"], approved_gate)

    def test_service_smoke_returns_handoff_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            media = base / "media"
            self.make_sample_media(media)
            result = service_smoke(
                media,
                db_path=base / "photos.sqlite",
                output_dir=base / "out",
            )
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["next_safe_action"], "service_ready")
            self.assertFalse(
                result["data"]["analyze"]["review_package"]["destructive_action_performed"]
            )


if __name__ == "__main__":
    unittest.main()
