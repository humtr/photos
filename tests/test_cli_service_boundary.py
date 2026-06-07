from __future__ import annotations

import ast
import contextlib
import csv
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from photos.cli import main


CLI = Path(__file__).resolve().parents[1] / "src" / "photos" / "cli.py"
FORBIDDEN_MODULES = {
    "classification",
    "database",
    "dry_run",
    "execution",
    "hashing",
    "reports",
    "review",
    "scanner",
}


class CliServiceBoundaryTests(unittest.TestCase):
    def run_cli(self, argv: list[str]) -> tuple[int, dict]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(argv)
        return code, json.loads(output.getvalue())

    def test_cli_has_no_forbidden_backend_imports_or_calls(self) -> None:
        tree = ast.parse(CLI.read_text(encoding="utf-8"))
        imported_modules = {
            node.module.rsplit(".", 1)[-1]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        self.assertTrue(FORBIDDEN_MODULES.isdisjoint(imported_modules))

        direct_backend_calls = {
            "connect",
            "compute_missing_hashes",
            "export_review_package",
            "hash_backlog",
            "import_classification_csv",
            "import_review_decisions",
            "run_media_analysis",
            "run_sample_dry_run",
            "write_decision_manifest",
            "write_management_report",
            "write_management_report_page",
        }
        calls = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertTrue(direct_backend_calls.isdisjoint(calls))

    def test_representative_commands_work_through_service(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            media = base / "media"
            media.mkdir()
            (media / "sample.JPG").write_bytes(b"sample")
            db = base / "photos.sqlite"

            code, dry_run = self.run_cli(
                ["dry-run", str(media), "--db", str(db), "--output", str(base / "dry-run")]
            )
            self.assertEqual(code, 0)
            self.assertEqual(dry_run["scanned"], 1)

            page_path = base / "page.json"
            code, report_page = self.run_cli(
                [
                    "report-page",
                    "--db",
                    str(db),
                    "--output",
                    str(page_path),
                    "--section",
                    "raw_without_jpg",
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(report_page["output"], str(page_path))
            self.assertTrue(page_path.exists())

            review_dir = base / "review"
            code, review = self.run_cli(
                ["review-export", "--db", str(db), "--output", str(review_dir), "--max-shortcuts", "0"]
            )
            self.assertEqual(code, 0)
            self.assertEqual(review["output_dir"], str(review_dir))
            self.assertFalse(review["destructive_action_performed"])

            code, hashed = self.run_cli(["hash", "--db", str(db), "--max-files", "0"])
            self.assertEqual(code, 0)
            self.assertEqual(hashed["status"], "ok")

            report_path = base / "report.json"
            code, report = self.run_cli(["report", "--db", str(db), "--output", str(report_path)])
            self.assertEqual(code, 0)
            self.assertEqual(report["output"], str(report_path))

            classification_path = base / "classification.csv"
            with classification_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["path", "label"])
                writer.writeheader()
                writer.writerow({"path": str(media / "sample.JPG"), "label": "person"})
            code, classification = self.run_cli(
                ["import-classification", str(classification_path), "--db", str(db)]
            )
            self.assertEqual(code, 0)
            self.assertEqual(classification["imported"], 1)

            decisions_path = base / "decisions.csv"
            with decisions_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["item_key", "path", "decision", "note"])
                writer.writeheader()
                writer.writerow(
                    {
                        "item_key": "manual",
                        "path": str(media / "sample.JPG"),
                        "decision": "delete",
                        "note": "",
                    }
                )
            code, decisions = self.run_cli(["import-decisions", str(decisions_path), "--db", str(db)])
            self.assertEqual(code, 0)
            self.assertEqual(decisions["imported"], 1)

            manifest_path = base / "decision-manifest.json"
            code, manifest = self.run_cli(
                ["decision-manifest", "--db", str(db), "--output", str(manifest_path)]
            )
            self.assertEqual(code, 0)
            self.assertEqual(manifest["candidate_count"], 1)

    def test_help_and_check_env_do_not_create_default_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous = Path.cwd()
            os.chdir(tmp)
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaisesRegex(SystemExit, "0"):
                        main(["--help"])
                    with self.assertRaisesRegex(SystemExit, "0"):
                        main(["report-page", "--help"])
                self.assertEqual(main(["check-env"]), 0)
                self.assertFalse(Path(".photos-data").exists())
            finally:
                os.chdir(previous)

    def test_long_running_cli_interrupts_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db = base / "photos.sqlite"
            db.touch()

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                with patch("photos.cli.PhotoOrganizerService.hash_missing", side_effect=KeyboardInterrupt):
                    code = main(["hash", "--db", str(db), "--max-files", "1"])

            self.assertEqual(code, 130)
            payload = json.loads(output.getvalue())
            self.assertFalse(payload["ok"], payload)
            self.assertEqual(payload["command"], "hash", payload)
            self.assertEqual(payload["next_safe_action"], "hash_missing", payload)
            self.assertIn("Interrupted by user", payload["errors"][0], payload)

    def test_batch_resume_interrupts_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db = base / "photos.sqlite"
            db.touch()

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                with patch("photos.cli.PhotoOrganizerService.resume_batch", side_effect=KeyboardInterrupt):
                    code = main(["batch-resume", "7", "--db", str(db), "--yes"])

            self.assertEqual(code, 130)
            payload = json.loads(output.getvalue())
            self.assertFalse(payload["ok"], payload)
            self.assertEqual(payload["command"], "batch-resume", payload)
            self.assertEqual(payload["next_safe_action"], "resume_batch", payload)
            self.assertIn("Interrupted by user", payload["errors"][0], payload)

    def test_plan_execute_interrupts_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db = base / "photos.sqlite"
            db.touch()

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                with patch("photos.cli.PhotoOrganizerService.execute_plan", side_effect=KeyboardInterrupt):
                    code = main(["plan-execute", "9", "--db", str(db), "--yes"])

            self.assertEqual(code, 130)
            payload = json.loads(output.getvalue())
            self.assertFalse(payload["ok"], payload)
            self.assertEqual(payload["command"], "plan-execute", payload)
            self.assertEqual(payload["next_safe_action"], "execute_plan", payload)
            self.assertIn("Interrupted by user", payload["errors"][0], payload)

    def test_analyze_interrupts_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            media = base / "media"
            media.mkdir()
            (media / "sample.JPG").write_bytes(b"sample")
            db = base / "photos.sqlite"

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                with patch("photos.cli.PhotoOrganizerService.analyze", side_effect=KeyboardInterrupt):
                    code = main(
                        [
                            "analyze",
                            str(media),
                            "--db",
                            str(db),
                            "--output",
                            str(base / "analyze"),
                        ]
                    )

            self.assertEqual(code, 130)
            payload = json.loads(output.getvalue())
            self.assertFalse(payload["ok"], payload)
            self.assertEqual(payload["command"], "analyze", payload)
            self.assertEqual(payload["next_safe_action"], "analyze", payload)
            self.assertIn("Interrupted by user", payload["errors"][0], payload)

    def test_dry_run_interrupts_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            media = base / "media"
            media.mkdir()
            (media / "sample.JPG").write_bytes(b"sample")
            db = base / "photos.sqlite"

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                with patch("photos.cli.PhotoOrganizerService.sample_dry_run", side_effect=KeyboardInterrupt):
                    code = main(
                        [
                            "dry-run",
                            str(media),
                            "--db",
                            str(db),
                            "--output",
                            str(base / "dry-run"),
                        ]
                    )

            self.assertEqual(code, 130)
            payload = json.loads(output.getvalue())
            self.assertFalse(payload["ok"], payload)
            self.assertEqual(payload["command"], "dry-run", payload)
            self.assertEqual(payload["next_safe_action"], "sample_dry_run", payload)
            self.assertIn("Interrupted by user", payload["errors"][0], payload)

    def test_service_smoke_interrupts_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            media = base / "media"
            media.mkdir()
            (media / "sample.JPG").write_bytes(b"sample")
            db = base / "photos.sqlite"

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                with patch("photos.cli.service_smoke", side_effect=KeyboardInterrupt):
                    code = main(
                        [
                            "service-smoke",
                            str(media),
                            "--db",
                            str(db),
                            "--output",
                            str(base / "service-smoke"),
                        ]
                    )

            self.assertEqual(code, 130)
            payload = json.loads(output.getvalue())
            self.assertFalse(payload["ok"], payload)
            self.assertEqual(payload["command"], "service-smoke", payload)
            self.assertEqual(payload["next_safe_action"], "service_smoke", payload)
            self.assertIn("Interrupted by user", payload["errors"][0], payload)

    def test_batch_reconcile_interrupts_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db = base / "photos.sqlite"
            db.touch()

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                with patch("photos.cli.PhotoOrganizerService.reconcile_batch", side_effect=KeyboardInterrupt):
                    code = main(["batch-reconcile", "5", "--db", str(db)])

            self.assertEqual(code, 130)
            payload = json.loads(output.getvalue())
            self.assertFalse(payload["ok"], payload)
            self.assertEqual(payload["command"], "batch-reconcile", payload)
            self.assertEqual(payload["next_safe_action"], "reconcile_batch", payload)
            self.assertIn("Interrupted by user", payload["errors"][0], payload)

    def test_plan_execute_emits_progress_to_stderr(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db = base / "photos.sqlite"
            db.touch()

            stdout = io.StringIO()
            stderr = io.StringIO()

            def fake_execute_plan(self, plan_id: int, **kwargs):
                callback = kwargs.get("progress_callback")
                if callback is not None:
                    callback(
                        {
                            "operation": "execute_plan",
                            "phase": "executing",
                            "total": 4,
                            "completed": 1,
                            "failed": 0,
                        }
                    )
                return {"ok": True, "data": {"executed": True}, "errors": [], "warnings": []}

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                with patch("photos.cli.PhotoOrganizerService.execute_plan", new=fake_execute_plan):
                    code = main(["plan-execute", "9", "--db", str(db), "--yes"])

            self.assertEqual(code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertTrue(payload["data"]["executed"], payload)
            progress_lines = [line for line in stderr.getvalue().splitlines() if line.strip()]
            self.assertGreaterEqual(len(progress_lines), 1, progress_lines)
            progress = json.loads(progress_lines[0])
            self.assertEqual(progress["status"], "progress", progress)
            self.assertEqual(progress["operation"], "execute_plan", progress)
            self.assertEqual(progress["phase"], "executing", progress)

    def test_analyze_emits_progress_to_stderr(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            media = base / "media"
            media.mkdir()
            (media / "sample.JPG").write_bytes(b"sample")
            db = base / "photos.sqlite"

            stdout = io.StringIO()
            stderr = io.StringIO()

            def fake_analyze(self, root, **kwargs):
                callback = kwargs.get("progress_callback")
                if callback is not None:
                    callback(
                        {
                            "operation": "analysis",
                            "phase": "completed",
                            "scanned": 1,
                            "hashed": 1,
                            "can_run_batch": True,
                        }
                    )
                return {"ok": True, "data": {"scanned": 1}, "errors": [], "warnings": []}

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                with patch("photos.cli.PhotoOrganizerService.analyze", new=fake_analyze):
                    code = main(
                        [
                            "analyze",
                            str(media),
                            "--db",
                            str(db),
                            "--output",
                            str(base / "analysis"),
                        ]
                    )

            self.assertEqual(code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["scanned"], 1, payload)
            progress_lines = [line for line in stderr.getvalue().splitlines() if line.strip()]
            self.assertGreaterEqual(len(progress_lines), 1, progress_lines)
            progress = json.loads(progress_lines[0])
            self.assertEqual(progress["status"], "progress", progress)
            self.assertEqual(progress["operation"], "analysis", progress)
            self.assertEqual(progress["phase"], "completed", progress)

    def test_dry_run_emits_progress_to_stderr(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            media = base / "media"
            media.mkdir()
            (media / "sample.JPG").write_bytes(b"sample")
            db = base / "photos.sqlite"

            stdout = io.StringIO()
            stderr = io.StringIO()

            def fake_sample_dry_run(self, root, **kwargs):
                callback = kwargs.get("progress_callback")
                if callback is not None:
                    for phase in ("starting", "scanned", "hashed", "planned", "budget_checked", "manifest_written", "report_written", "review_package_written", "completed"):
                        payload = {
                            "operation": "sample_dry_run",
                            "phase": phase,
                            "scanned": 1,
                            "hashed": 1,
                            "can_run_batch": True,
                        }
                        callback(payload)
                return {"ok": True, "data": {"scanned": 1}, "errors": [], "warnings": []}

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                with patch("photos.cli.PhotoOrganizerService.sample_dry_run", new=fake_sample_dry_run):
                    code = main(
                        [
                            "dry-run",
                            str(media),
                            "--db",
                            str(db),
                            "--output",
                            str(base / "dry-run"),
                        ]
                    )

            self.assertEqual(code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["scanned"], 1, payload)
            progress_lines = [line for line in stderr.getvalue().splitlines() if line.strip()]
            self.assertGreaterEqual(len(progress_lines), 1, progress_lines)
            progress = json.loads(progress_lines[0])
            self.assertEqual(progress["status"], "progress", progress)
            self.assertEqual(progress["operation"], "sample_dry_run", progress)
            self.assertEqual(progress["phase"], "starting", progress)

    def test_plan_dry_run_emits_progress_to_stderr(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db = base / "photos.sqlite"

            stdout = io.StringIO()
            stderr = io.StringIO()

            def fake_dry_run_plan(self, plan_id, **kwargs):
                callback = kwargs.get("progress_callback")
                if callback is not None:
                    for phase in ("starting", "validating", "completed"):
                        callback(
                            {
                                "operation": "dry_run_plan",
                                "phase": phase,
                                "action_count": 1,
                                "estimated_bytes": 1,
                                "execute_allowed": True,
                            }
                        )
                return {
                    "ok": True,
                    "data": {"action_count": 1, "execute_allowed": True},
                    "errors": [],
                    "warnings": [],
                }

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                with patch("photos.cli.PhotoOrganizerService.dry_run_plan", new=fake_dry_run_plan):
                    code = main(["plan-dry-run", "9", "--db", str(db)])

            self.assertEqual(code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertTrue(payload["data"]["execute_allowed"], payload)
            progress_lines = [line for line in stderr.getvalue().splitlines() if line.strip()]
            self.assertGreaterEqual(len(progress_lines), 1, progress_lines)
            progress = json.loads(progress_lines[0])
            self.assertEqual(progress["status"], "progress", progress)
            self.assertEqual(progress["operation"], "dry_run_plan", progress)
            self.assertEqual(progress["phase"], "starting", progress)


if __name__ == "__main__":
    unittest.main()
