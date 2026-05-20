from __future__ import annotations

import csv
import json
import sqlite3
import sys
import os
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from photos.classification import import_classification_csv
from photos.database import (
    connect,
    init_db,
    recover_interrupted_runs,
    record_classification_result,
    record_review_decision,
    record_scan_error,
    start_run,
)
from photos.dry_run import run_media_analysis, run_sample_dry_run
from photos.hashing import compute_missing_hashes, duplicate_groups, hash_backlog
from photos.pairing import raw_jpg_pairs
from photos.planning import (
    build_archive_plans,
    build_raw_to_jpg_plans,
    estimate_required_extra_bytes,
    storage_budget_status,
)
from photos.reports import build_management_report, write_management_report
from photos.review import (
    _windows_or_posix_file_uri,
    export_review_package,
    import_review_decisions,
    write_decision_manifest,
)
from photos.scanner import scan_media


def write_file(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


class CorePipelineTests(unittest.TestCase):
    def make_sample_media(self, root: Path) -> None:
        write_file(root / "trip" / "IMG_0001.ARW", b"raw-one")
        write_file(root / "trip" / "IMG_0001.JPG", b"jpg-one")
        write_file(root / "trip" / "IMG_0002.RAF", b"raw-two-without-jpg")
        write_file(root / "trip" / "dup_a.JPG", b"duplicate-content")
        write_file(root / "other" / "dup_b.JPG", b"duplicate-content")
        write_file(root / "video" / "clip.MP4", b"video-bytes")
        write_file(root / "screen" / "Screenshot_001.PNG", b"screen")

    def test_scan_hash_pair_plan_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            media = base / "media"
            self.make_sample_media(media)
            with closing(connect(base / "photos.sqlite")) as con:
                self.assertEqual(scan_media(con, media), 7)
                self.assertEqual(compute_missing_hashes(con), 7)
                self.assertEqual(len(duplicate_groups(con)), 1)

                pairs = raw_jpg_pairs(con)
                self.assertEqual(len(pairs), 1)
                self.assertTrue(pairs[0].raw_path.endswith("IMG_0001.ARW"))
                self.assertTrue(pairs[0].jpg_path.endswith("IMG_0001.JPG"))

                archive_plans = build_archive_plans(con)
                raw_plans = build_raw_to_jpg_plans(con)
                self.assertEqual(len(archive_plans), 7)
                self.assertTrue(
                    all(plan["planned_path"].startswith("archive/") for plan in archive_plans)
                )
                self.assertEqual(
                    {plan["action"] for plan in raw_plans},
                    {"validate_existing_jpg", "convert_raw_to_jpg_on_windows"},
                )

                required = estimate_required_extra_bytes(con)
                self.assertGreater(required, 0)
                enough = storage_budget_status(
                    free_bytes=200 * 1024**3, required_extra_bytes=required
                )
                low = storage_budget_status(free_bytes=50 * 1024**3, required_extra_bytes=required)
                self.assertTrue(enough.can_run)
                self.assertFalse(low.can_run)

                record_review_decision(
                    con, "pair:IMG_0001", pairs[0].raw_path, "keep_raw", "astronomy"
                )
                decision = con.execute(
                    "SELECT decision, note FROM review_decisions WHERE group_key = ?",
                    ("pair:IMG_0001",),
                ).fetchone()
                assert isinstance(decision, sqlite3.Row)
                self.assertEqual(decision["decision"], "keep_raw")
                self.assertEqual(decision["note"], "astronomy")

    def test_dry_run_is_non_destructive_and_records_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            media = base / "media"
            self.make_sample_media(media)

            summary = run_sample_dry_run(
                media,
                db_path=base / "photos.sqlite",
                output_dir=base / "out",
                free_bytes=200 * 1024**3,
            )

            self.assertEqual(summary["scanned"], 7)
            self.assertEqual(summary["duplicate_groups"], 1)
            self.assertEqual(summary["raw_jpg_pairs"], 1)
            self.assertTrue(summary["can_run_batch"])
            manifest = json.loads(Path(summary["manifest_path"]).read_text(encoding="utf-8"))
            report = json.loads(Path(summary["management_report_path"]).read_text(encoding="utf-8"))
            self.assertFalse(manifest["destructive_action_performed"])
            self.assertTrue(manifest["requires_explicit_approval_before_delete"])
            self.assertFalse(report["safety"]["destructive_action_performed"])
            self.assertEqual(report["review_queues"]["exact_duplicate_groups"], 1)
            self.assertEqual(report["review_queues"]["raw_jpg_pairs"], 1)
            self.assertEqual(report["review_queues"]["raw_without_jpg"], 1)
            self.assertEqual(report["review_queues"]["non_person_candidates"], 1)
            self.assertEqual(report["review_queues"]["videos"], 1)
            reasons = {candidate["reason"] for candidate in manifest["candidates"]}
            self.assertIn("exact_duplicate", reasons)
            self.assertIn("raw_reduction_candidate", reasons)
            self.assertTrue((media / "trip" / "IMG_0002.RAF").exists())
            self.assertTrue((base / "out" / "review_package" / "decisions_template.csv").exists())

    def test_interrupted_run_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with closing(connect(Path(tmp) / "photos.sqlite")) as con:
                run_id = start_run(con, "test")
                self.assertIsInstance(run_id, int)
                self.assertEqual(recover_interrupted_runs(con), 1)
                row = con.execute(
                    "SELECT status FROM pipeline_runs WHERE id = ?", (run_id,)
                ).fetchone()
                assert isinstance(row, sqlite3.Row)
                self.assertEqual(row["status"], "interrupted")

    def test_management_report_surfaces_file_review_queues(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            media = base / "media"
            self.make_sample_media(media)
            with closing(connect(base / "photos.sqlite")) as con:
                scan_media(con, media)
                compute_missing_hashes(con)
                build_archive_plans(con)
                build_raw_to_jpg_plans(con)

                report = build_management_report(con, top_folders=2)
                self.assertEqual(report["inventory"]["total_files"], 7)
                self.assertGreaterEqual(len(report["inventory"]["by_type"]), 4)
                self.assertEqual(report["review_queues"]["exact_duplicate_groups"], 1)
                self.assertEqual(report["review_queues"]["raw_jpg_pairs"], 1)
                self.assertEqual(report["review_queues"]["raw_without_jpg"], 1)
                self.assertEqual(report["review_queues"]["non_person_candidates"], 1)
                self.assertEqual(report["review_queues"]["videos"], 1)
                self.assertEqual(report["planned_operations"]["planned_path_conflicts"], [])
                self.assertEqual(report["scan_health"]["hash_backlog"]["count"], 0)

                output = base / "report.json"
                write_management_report(con, output, top_folders=2)
                self.assertTrue(output.exists())

    def test_analysis_review_package_and_decision_manifest_support_cleanup_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            media = base / "media"
            self.make_sample_media(media)

            summary = run_media_analysis(
                media,
                db_path=base / "photos.sqlite",
                output_dir=base / "analysis",
                free_bytes=200 * 1024**3,
                max_review_shortcuts=5,
            )
            self.assertEqual(summary["review_queues"]["exact_duplicate_groups"], 1)
            self.assertEqual(summary["review_queues"]["raw_jpg_pairs"], 1)
            self.assertEqual(summary["review_queues"]["raw_without_jpg"], 1)
            self.assertEqual(summary["review_queues"]["non_person_candidates"], 1)
            self.assertEqual(summary["review_queues"]["videos"], 1)
            self.assertFalse(summary["review_package"]["destructive_action_performed"])

            with closing(connect(base / "photos.sqlite")) as con:
                screen_path = str(media / "screen" / "Screenshot_001.PNG")
                record_classification_result(
                    con,
                    path=screen_path,
                    label="non_person",
                    confidence=0.98,
                    model="test-model",
                )
                review_summary = export_review_package(
                    con, base / "review", max_shortcuts_per_queue=5
                )
                self.assertEqual(review_summary["queue_counts"]["non_person_candidates"], 1)
                self.assertTrue((base / "review" / "queues" / "exact_duplicates.csv").exists())
                self.assertTrue((base / "review" / "shortcuts" / "videos").exists())

                decisions_path = base / "review" / "decisions_template.csv"
                with decisions_path.open(newline="", encoding="utf-8") as handle:
                    rows = list(csv.DictReader(handle))
                self.assertGreater(len(rows), 0)
                rows[0]["decision"] = "delete"
                with decisions_path.open("w", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
                    writer.writeheader()
                    writer.writerows(rows)

                self.assertEqual(import_review_decisions(con, decisions_path), 1)
                manifest = write_decision_manifest(con, base / "decision_manifest.json")
                self.assertEqual(manifest["candidate_count"], 1)
                self.assertFalse(manifest["destructive_action_performed"])

    def test_rescan_marks_missing_files_and_invalidates_changed_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            media = base / "media"
            write_file(media / "a.JPG", b"same")
            write_file(media / "b.JPG", b"same")
            with closing(connect(base / "photos.sqlite")) as con:
                scan_media(con, media)
                compute_missing_hashes(con)
                self.assertEqual(len(duplicate_groups(con)), 1)

                (media / "b.JPG").unlink()
                write_file(media / "a.JPG", b"changed-content")
                scan_media(con, media)
                row = con.execute("SELECT sha256 FROM media_files WHERE name = 'a.JPG'").fetchone()
                self.assertIsNone(row["sha256"])
                self.assertEqual(len(duplicate_groups(con)), 0)
                missing = con.execute(
                    "SELECT exists_on_disk FROM media_files WHERE name = 'b.JPG'"
                ).fetchone()
                self.assertEqual(missing["exists_on_disk"], 0)

                self.assertEqual(compute_missing_hashes(con, max_files=1, commit_interval=1), 1)
                self.assertEqual(build_management_report(con)["inventory"]["total_files"], 1)

    def test_review_manifest_ignores_paths_outside_managed_media(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            with closing(connect(base / "photos.sqlite")) as con:
                decisions_path = base / "decisions.csv"
                decisions_path.write_text(
                    "queue,item_key,path,decision,note\n"
                    "manual,g,C:\\Windows\\System32\\drivers\\etc\\hosts,delete,manual\n",
                    encoding="utf-8",
                )

                self.assertEqual(import_review_decisions(con, decisions_path), 1)
                manifest = write_decision_manifest(con, base / "manifest.json")
                self.assertEqual(manifest["candidate_count"], 0)

    def test_windows_file_urls_keep_drive_colon_and_unc_host(self) -> None:
        self.assertEqual(
            _windows_or_posix_file_uri(r"D:\Photos\A B.jpg"),
            "file:///D:/Photos/A%20B.jpg",
        )
        self.assertEqual(
            _windows_or_posix_file_uri(r"\\server\share\A B.jpg"),
            "file://server/share/A%20B.jpg",
        )

    def test_scan_records_directory_errors_and_continues(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            media = base / "media"
            write_file(media / "ok" / "keep.JPG", b"image")
            write_file(media / "blocked" / "skip.JPG", b"blocked")

            real_scandir = os.scandir

            def flaky_scandir(path: str | os.PathLike[str]):
                if Path(path) == media / "blocked":
                    raise PermissionError("blocked for test")
                return real_scandir(path)

            with closing(connect(base / "photos.sqlite")) as con:
                self.assertEqual(scan_media(con, media), 2)

                with patch("photos.scanner.os.scandir", side_effect=flaky_scandir):
                    self.assertEqual(scan_media(con, media), 1)

                blocked_row = con.execute(
                    "SELECT exists_on_disk FROM media_files WHERE path = ?",
                    (str(media / "blocked" / "skip.JPG"),),
                ).fetchone()
                self.assertEqual(blocked_row["exists_on_disk"], 1)

                report = build_management_report(con)
                self.assertEqual(report["inventory"]["total_files"], 2)
                self.assertEqual(
                    report["scan_health"]["scan_errors"], [{"phase": "scan", "count": 1}]
                )
                self.assertEqual(len(report["scan_health"]["recent_scan_errors"]), 1)
                self.assertIn("blocked", report["scan_health"]["recent_scan_errors"][0]["path"])

    def test_hashing_runs_in_bounded_resumable_batches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            media = base / "media"
            for index in range(5):
                write_file(media / f"{index}.JPG", f"file-{index}".encode())

            with closing(connect(base / "photos.sqlite")) as con:
                self.assertEqual(scan_media(con, media), 5)
                self.assertEqual(compute_missing_hashes(con, max_files=2, batch_size=2), 2)
                self.assertEqual(hash_backlog(con)["count"], 3)
                self.assertEqual(compute_missing_hashes(con, max_files=2, batch_size=2), 2)
                self.assertEqual(hash_backlog(con)["count"], 1)
                self.assertEqual(compute_missing_hashes(con, batch_size=2), 1)
                self.assertEqual(hash_backlog(con)["count"], 0)

    def test_hashing_marks_files_that_disappear_during_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            media = base / "media"
            target = media / "gone.JPG"
            write_file(target, b"gone")

            with closing(connect(base / "photos.sqlite")) as con:
                scan_media(con, media)

                def disappearing_hash(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
                    Path(path).unlink()
                    raise FileNotFoundError(path)

                with patch("photos.hashing.sha256_file", side_effect=disappearing_hash):
                    self.assertEqual(compute_missing_hashes(con), 0)

                row = con.execute(
                    "SELECT exists_on_disk FROM media_files WHERE path = ?", (str(target),)
                ).fetchone()
                self.assertEqual(row["exists_on_disk"], 0)
                report = build_management_report(con)
                self.assertEqual(
                    report["scan_health"]["scan_errors"], [{"phase": "hash", "count": 1}]
                )

    def test_planning_batches_commit_once_per_plan_type(self) -> None:
        class CountingConnection(sqlite3.Connection):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.commit_calls = 0

            def commit(self) -> None:
                self.commit_calls += 1
                super().commit()

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            media = base / "media"
            self.make_sample_media(media)

            con = sqlite3.connect(base / "photos.sqlite", factory=CountingConnection)
            con.row_factory = sqlite3.Row
            try:
                init_db(con)
                scan_media(con, media)

                before = con.commit_calls
                self.assertEqual(len(build_archive_plans(con)), 7)
                self.assertEqual(con.commit_calls - before, 1)

                before = con.commit_calls
                self.assertEqual(len(build_raw_to_jpg_plans(con)), 2)
                self.assertEqual(con.commit_calls - before, 1)
            finally:
                con.close()

    def test_management_report_includes_recent_scan_error_details(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            with closing(connect(base / "photos.sqlite")) as con:
                record_scan_error(
                    con,
                    root=str(base),
                    path=str(base / "unreadable.JPG"),
                    phase="scan",
                    error="PermissionError('denied')",
                )
                con.commit()

                report = build_management_report(con)
                self.assertEqual(
                    report["scan_health"]["scan_errors"], [{"phase": "scan", "count": 1}]
                )
                recent = report["scan_health"]["recent_scan_errors"]
                self.assertEqual(len(recent), 1)
                self.assertEqual(recent[0]["phase"], "scan")
                self.assertIn("unreadable.JPG", recent[0]["path"])

    def test_latest_scan_run_is_separated_from_historical_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            media = base / "media"
            write_file(media / "ok" / "keep.JPG", b"image")
            write_file(media / "blocked" / "skip.JPG", b"blocked")

            real_scandir = os.scandir

            def flaky_scandir(path: str | os.PathLike[str]):
                if Path(path) == media / "blocked":
                    raise PermissionError("blocked for test")
                return real_scandir(path)

            with closing(connect(base / "photos.sqlite")) as con:
                with patch("photos.scanner.os.scandir", side_effect=flaky_scandir):
                    self.assertEqual(scan_media(con, media), 1)
                partial = build_management_report(con)["scan_health"]
                self.assertEqual(partial["current_run"]["status"], "completed_with_errors")
                self.assertTrue(partial["current_run"]["missing_marking_skipped"])
                self.assertEqual(partial["current_run"]["scan_errors"], [{"phase": "scan", "count": 1}])

                self.assertEqual(scan_media(con, media), 2)
                clean = build_management_report(con)["scan_health"]
                self.assertEqual(clean["current_run"]["status"], "completed")
                self.assertFalse(clean["current_run"]["missing_marking_skipped"])
                self.assertEqual(clean["current_run"]["scan_errors"], [])
                self.assertEqual(clean["historical_scan_errors"], [{"phase": "scan", "count": 1}])

    def test_import_review_decisions_rejects_invalid_values_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            decisions_path = base / "decisions.csv"
            decisions_path.write_text(
                "queue,item_key,path,decision,note\n"
                "manual,g,one.JPG,delete,ok\n"
                "manual,g,two.JPG,deleet,typo\n",
                encoding="utf-8",
            )
            with closing(connect(base / "photos.sqlite")) as con:
                with self.assertRaises(ValueError):
                    import_review_decisions(con, decisions_path)
                count = con.execute("SELECT COUNT(*) AS count FROM review_decisions").fetchone()
                self.assertEqual(count["count"], 0)

    def test_classification_import_commits_once_after_validation(self) -> None:
        class CountingConnection(sqlite3.Connection):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.commit_calls = 0

            def commit(self) -> None:
                self.commit_calls += 1
                super().commit()

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            csv_path = base / "classification.csv"
            csv_path.write_text(
                "path,label,confidence,model,note\n"
                "a.JPG,non_person,0.9,test,screen\n"
                "b.JPG,person,0.8,test,portrait\n",
                encoding="utf-8",
            )
            con = sqlite3.connect(base / "photos.sqlite", factory=CountingConnection)
            con.row_factory = sqlite3.Row
            try:
                init_db(con)
                before = con.commit_calls
                self.assertEqual(import_classification_csv(con, csv_path), 2)
                self.assertEqual(con.commit_calls - before, 1)
                count = con.execute("SELECT COUNT(*) AS count FROM classification_results").fetchone()
                self.assertEqual(count["count"], 2)
            finally:
                con.close()

if __name__ == "__main__":
    unittest.main()
