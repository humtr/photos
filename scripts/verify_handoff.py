from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from photos.dry_run import run_sample_dry_run
from photos.env_check import check_environment
from photos.services import service_smoke


def run_command(args: list[str], *, env: dict[str, str] | None = None) -> None:
    print("+ " + " ".join(args))
    subprocess.run(args, cwd=ROOT, env=env, check=True)


def assert_required_files() -> None:
    required = [
        "README.md",
        "docs/windows_handoff.md",
        "scripts/setup_windows.ps1",
        "scripts/run_windows.ps1",
        "scripts/check_environment.ps1",
        "scripts/verify_windows.ps1",
        "src/photos/classification.py",
        "src/photos/cli.py",
        "src/photos/contracts.py",
        "src/photos/execution.py",
        "src/photos/review.py",
        "src/photos/services.py",
        "src/photos/store.py",
        "tests/test_core.py",
    ]
    missing = [path for path in required if not (ROOT / path).exists()]
    if missing:
        raise AssertionError(f"Missing handoff files: {missing}")


def verify_sample_dry_run() -> dict:
    sample = ROOT / "tests" / "fixtures" / "sample_media"
    if not sample.exists():
        raise AssertionError(f"Missing sample fixture: {sample}")

    with tempfile.TemporaryDirectory(prefix="photos-handoff-") as tmp:
        tmp_path = Path(tmp)
        summary = run_sample_dry_run(
            sample,
            db_path=tmp_path / "verify.sqlite",
            output_dir=tmp_path / "dry-run",
            free_bytes=200 * 1024**3,
        )
        output_dir = tmp_path / "dry-run"
        candidate_manifest_path = output_dir / "candidate_manifest.json"
        if Path(summary["candidate_manifest_path"]) != candidate_manifest_path:
            raise AssertionError("Summary candidate_manifest_path does not match the dry-run artifact.")
        if Path(summary["manifest_path"]) != candidate_manifest_path:
            raise AssertionError("Summary manifest_path no longer points at candidate_manifest.json.")
        if not candidate_manifest_path.exists():
            raise AssertionError(f"Candidate manifest was not written: {candidate_manifest_path}")
        manifest = json.loads(candidate_manifest_path.read_text(encoding="utf-8"))
        legacy_manifest_path = Path(summary["legacy_deletion_manifest_path"])
        if legacy_manifest_path != output_dir / "deletion_manifest.json":
            raise AssertionError("Summary legacy_deletion_manifest_path does not match the legacy artifact.")
        if not legacy_manifest_path.exists():
            raise AssertionError(f"Legacy deletion manifest was not written: {legacy_manifest_path}")
        legacy_manifest = json.loads(legacy_manifest_path.read_text(encoding="utf-8"))
        if legacy_manifest != manifest:
            raise AssertionError("Legacy deletion manifest does not preserve candidate manifest content.")
        if manifest["destructive_action_performed"]:
            raise AssertionError("Dry run reported destructive action.")
        if not manifest["requires_explicit_approval_before_delete"]:
            raise AssertionError("Manifest does not require explicit approval.")
        if summary["scanned"] < 7:
            raise AssertionError(f"Unexpected scanned count: {summary['scanned']}")
        if summary["duplicate_groups"] < 1:
            raise AssertionError("Expected at least one duplicate group.")
        if summary["raw_jpg_pairs"] < 1:
            raise AssertionError("Expected at least one RAW/JPG pair.")
        report_path = output_dir / "management_report.json"
        if Path(summary["management_report_path"]) != report_path:
            raise AssertionError("Summary management_report_path does not match management_report.json.")
        if not report_path.exists():
            raise AssertionError(f"Management report was not written: {report_path}")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if report["safety"]["destructive_action_performed"]:
            raise AssertionError("Management report claims a destructive action.")
        if report["review_queues"]["raw_without_jpg"] < 1:
            raise AssertionError("Expected at least one RAW-without-JPG review queue item.")
        if report["review_queues"]["non_person_candidates"] < 1:
            raise AssertionError("Expected at least one non-person candidate review queue item.")
        if report["review_queues"]["videos"] < 1:
            raise AssertionError("Expected at least one video review queue item.")
        if report["scan_health"]["hash_backlog"]["count"] != 0:
            raise AssertionError("Expected no hash backlog after the sample dry run.")
        review_package = Path(summary["review_package_path"])
        if not (review_package / "decisions_template.csv").exists():
            raise AssertionError("Review package decision template was not written.")
        for queue_name in (
            "exact_duplicates",
            "raw_jpg_pairs",
            "raw_without_jpg",
            "non_person_candidates",
            "videos",
        ):
            if not (review_package / "queues" / f"{queue_name}.csv").exists():
                raise AssertionError(f"Review package queue was not written: {queue_name}")
        return summary


def verify_service_smoke() -> dict:
    sample = ROOT / "tests" / "fixtures" / "sample_media"
    if not sample.exists():
        raise AssertionError(f"Missing sample fixture: {sample}")

    with tempfile.TemporaryDirectory(prefix="photos-service-smoke-") as tmp:
        tmp_path = Path(tmp)
        result = service_smoke(
            sample,
            db_path=tmp_path / "service.sqlite",
            output_dir=tmp_path / "service-smoke",
        )
        if not result["ok"]:
            raise AssertionError(f"Service smoke failed: {result}")
        if result["next_safe_action"] != "service_ready":
            raise AssertionError(f"Unexpected service smoke next action: {result['next_safe_action']}")
        if result["data"]["analyze"]["review_package"]["destructive_action_performed"]:
            raise AssertionError("Service smoke review package reported destructive action.")
        return result


def main() -> int:
    assert_required_files()

    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    run_command([sys.executable, "-m", "unittest", "discover", "-s", "tests"], env=env)

    environment = check_environment()
    summary = verify_sample_dry_run()
    service_result = verify_service_smoke()
    report = {
        "status": "ok",
        "environment": environment,
        "sample_dry_run": summary,
        "service_smoke": service_result,
        "windows_only_gaps": [
            "real root Tkinter GUI rendering and performance",
            "Windows drive permissions and long paths",
            "external media-tool installation differences",
            "real RAW conversion quality",
            "large-drive throughput",
            "automatic classification quality",
        ],
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
