from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from photos.services import PhotoOrganizerService
from photos.dry_run import run_media_analysis


def write_file(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


class ServiceProgressTests(unittest.TestCase):
    def test_run_media_analysis_reports_progress(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            media = base / "media"
            write_file(media / "one.JPG", b"one")
            write_file(media / "two.JPG", b"two")

            events: list[dict[str, object]] = []
            summary = run_media_analysis(
                media,
                db_path=base / "photos.sqlite",
                output_dir=base / "analysis",
                free_bytes=200 * 1024**3,
                progress_callback=events.append,
            )

            self.assertEqual(summary["scanned"], 2, summary)
            self.assertGreaterEqual(len(events), 5, events)
            analysis_events = [event for event in events if event["operation"] == "analysis"]
            self.assertEqual(
                [event["phase"] for event in analysis_events],
                [
                    "starting",
                    "scanned",
                    "hashed",
                    "planned",
                    "budget_checked",
                    "manifest_written",
                    "report_written",
                    "review_package_written",
                    "completed",
                ],
                analysis_events,
            )
            self.assertEqual(analysis_events[-1]["scanned"], 2, analysis_events)

    def test_hash_missing_reports_progress(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            media = base / "media"
            write_file(media / "one.JPG", b"one")
            write_file(media / "two.JPG", b"two")

            events: list[dict[str, object]] = []
            with PhotoOrganizerService(base / "photos.sqlite") as service:
                scan = service.scan_inventory(media, hash_files=False)
                self.assertTrue(scan["ok"], scan)
                result = service.hash_missing(progress_callback=events.append)
                self.assertTrue(result["ok"], result)

            self.assertGreaterEqual(len(events), 3, events)
            self.assertEqual(events[0]["phase"], "starting", events)
            self.assertEqual(events[-1]["phase"], "completed", events)
            self.assertEqual(events[-1]["updated"], 2, events)
            self.assertEqual(events[-1]["attempted"], 2, events)

    def test_execute_plan_reports_progress(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            media = base / "media"
            write_file(media / "one.JPG", b"one")
            write_file(media / "two.JPG", b"two")
            archive = base / "archive"

            events: list[dict[str, object]] = []
            with PhotoOrganizerService(base / "photos.sqlite") as service:
                scan = service.scan_inventory(media, hash_files=True)
                self.assertTrue(scan["ok"], scan)
                plan = service.create_archive_plan(archive)
                self.assertTrue(plan["ok"], plan)
                service.approve_plan(plan["data"]["plan_id"], approved=True, note="progress test")
                result = service.execute_plan(
                    plan["data"]["plan_id"],
                    execute_approved=True,
                    progress_callback=events.append,
                )
                self.assertTrue(result["ok"], result)
                self.assertTrue(result["data"]["executed"], result)

            self.assertGreaterEqual(len(events), 3, events)
            self.assertEqual(events[0]["phase"], "starting", events)
            self.assertEqual(events[-1]["phase"], "completed", events)
            self.assertEqual(events[-1]["completed"], 2, events)
            self.assertEqual(events[-1]["failed"], 0, events)

    def test_plan_dry_run_reports_progress(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            media = base / "media"
            write_file(media / "one.JPG", b"one")
            write_file(media / "two.JPG", b"two")
            archive = base / "archive"

            events: list[dict[str, object]] = []
            with PhotoOrganizerService(base / "photos.sqlite") as service:
                scan = service.scan_inventory(media, hash_files=True)
                self.assertTrue(scan["ok"], scan)
                plan = service.create_archive_plan(archive)
                self.assertTrue(plan["ok"], plan)
                service.approve_plan(plan["data"]["plan_id"], approved=True, note="progress test")
                result = service.dry_run_plan(plan["data"]["plan_id"], progress_callback=events.append)
                self.assertTrue(result["ok"], result)

            phases = [event["phase"] for event in events]
            self.assertEqual(phases, ["starting", "validating", "completed"], events)
            self.assertEqual(events[-1]["action_count"], 2, events)
            self.assertTrue(events[-1]["execute_allowed"], events)

    def test_reconcile_and_rollback_report_progress(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            media = base / "media"
            write_file(media / "one.JPG", b"one")
            write_file(media / "two.JPG", b"two")
            archive = base / "archive"

            reconcile_events: list[dict[str, object]] = []
            rollback_events: list[dict[str, object]] = []
            with PhotoOrganizerService(base / "photos.sqlite") as service:
                scan = service.scan_inventory(media, hash_files=True)
                self.assertTrue(scan["ok"], scan)
                plan = service.create_archive_plan(archive)
                self.assertTrue(plan["ok"], plan)
                service.approve_plan(plan["data"]["plan_id"], approved=True, note="progress test")
                executed = service.execute_plan(plan["data"]["plan_id"], execute_approved=True)
                self.assertTrue(executed["ok"], executed)
                batch_id = executed["data"]["batch_id"]

                reconciled = service.reconcile_batch(batch_id, progress_callback=reconcile_events.append)
                self.assertTrue(reconciled["ok"], reconciled)
                self.assertTrue(reconciled["data"]["reconciled"], reconciled)

                rolled_back = service.rollback_batch(
                    batch_id,
                    execute_approved=True,
                    progress_callback=rollback_events.append,
                )
                self.assertTrue(rolled_back["ok"], rolled_back)
                self.assertTrue(rolled_back["data"]["rolled_back"], rolled_back)

            self.assertGreaterEqual(len(reconcile_events), 2, reconcile_events)
            self.assertEqual(reconcile_events[0]["phase"], "starting", reconcile_events)
            self.assertEqual(reconcile_events[-1]["phase"], "completed", reconcile_events)
            self.assertGreaterEqual(len(rollback_events), 2, rollback_events)
            self.assertEqual(rollback_events[0]["phase"], "starting", rollback_events)
            self.assertEqual(rollback_events[-1]["phase"], "completed", rollback_events)


if __name__ == "__main__":
    unittest.main()
