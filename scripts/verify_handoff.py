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
        "src/photos/review.py",
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
        manifest_path = Path(summary["manifest_path"])
        if not manifest_path.exists():
            raise AssertionError(f"Manifest was not written: {manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
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
        report_path = Path(summary["management_report_path"])
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
        review_package = Path(summary["review_package_path"])
        if not (review_package / "decisions_template.csv").exists():
            raise AssertionError("Review package decision template was not written.")
        if not (review_package / "queues" / "exact_duplicates.csv").exists():
            raise AssertionError("Review package duplicate queue was not written.")
        return summary


def main() -> int:
    assert_required_files()

    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    run_command([sys.executable, "-m", "unittest", "discover", "-s", "tests"], env=env)

    environment = check_environment()
    summary = verify_sample_dry_run()
    report = {
        "status": "ok",
        "environment": environment,
        "sample_dry_run": summary,
        "windows_only_gaps": [
            "real PySide6 rendering and performance",
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
