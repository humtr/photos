from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .env_check import main as env_check_main
from .services import PhotoOrganizerService, service_smoke

DEFAULT_DETAIL_PAGE_SIZE = 10_000
_LAST_COMMAND: str | None = None


def non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="photos")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("check-env", help="Report Python and external media-tool availability.")

    dry_run = sub.add_parser("dry-run", help="Run a non-destructive sample-folder pipeline.")
    dry_run.add_argument("root", help="Sample media folder to scan.")
    dry_run.add_argument("--db", default=".photos-data/photos.sqlite", help="SQLite database path.")
    dry_run.add_argument("--output", default=".photos-data/dry-run", help="Dry-run output folder.")
    dry_run.add_argument(
        "--free-bytes",
        type=non_negative_int,
        default=None,
        help="Override free-space value.",
    )

    analyze = sub.add_parser("analyze", help="Run a non-destructive analysis on a real media root.")
    analyze.add_argument("root", help="Media folder or drive root to scan.")
    analyze.add_argument("--db", default=".photos-data/photos.sqlite", help="SQLite database path.")
    analyze.add_argument("--output", default=".photos-data/analyze", help="Analysis output folder.")
    analyze.add_argument(
        "--skip-hash",
        action="store_true",
        help="Skip file hashing for a faster inventory pass.",
    )
    analyze.add_argument(
        "--top-folders",
        type=non_negative_int,
        default=50,
        help="Folder summary limit.",
    )
    analyze.add_argument(
        "--max-review-shortcuts",
        type=non_negative_int,
        default=250,
        help="Maximum .url shortcuts to write per review queue.",
    )
    analyze.add_argument(
        "--max-detail-items",
        type=non_negative_int,
        default=DEFAULT_DETAIL_PAGE_SIZE,
        help="Maximum detailed rows embedded in the main report.",
    )

    hash_cmd = sub.add_parser("hash", help="Hash queued files in a resumable batch.")
    hash_cmd.add_argument(
        "--db",
        default=".photos-data/photos.sqlite",
        help="SQLite database path.",
    )
    hash_cmd.add_argument(
        "--max-files",
        type=non_negative_int,
        default=None,
        help="Maximum files to hash.",
    )
    hash_cmd.add_argument(
        "--commit-interval",
        type=non_negative_int,
        default=100,
        help="Commit after this many hashed files.",
    )

    report = sub.add_parser("report", help="Write a file-management report from an existing DB.")
    report.add_argument("--db", default=".photos-data/photos.sqlite", help="SQLite database path.")
    report.add_argument("--output", default=".photos-data/report.json", help="Report JSON path.")
    report.add_argument(
        "--top-folders",
        type=non_negative_int,
        default=20,
        help="Folder summary limit.",
    )
    report.add_argument(
        "--max-detail-items",
        type=non_negative_int,
        default=DEFAULT_DETAIL_PAGE_SIZE,
        help="Maximum detailed rows embedded in the main report.",
    )

    report_page = sub.add_parser(
        "report-page",
        help="Write one paged detail section (10,000 rows default).",
    )
    report_page.add_argument("--db", default=".photos-data/photos.sqlite", help="SQLite database path.")
    report_page.add_argument("--output", required=True, help="Output JSON path.")
    report_page.add_argument(
        "--section",
        required=True,
        choices=("duplicates", "raw_pairs", "raw_without_jpg", "non_person_candidates"),
        help="Detail section to export as one page.",
    )
    report_page.add_argument("--page", type=non_negative_int, default=0, help="Zero-based page index.")
    report_page.add_argument(
        "--page-size",
        type=non_negative_int,
        default=DEFAULT_DETAIL_PAGE_SIZE,
        help="Rows per page (default 10000).",
    )

    review_export = sub.add_parser(
        "review-export",
        help="Write CSV queues and Windows .url shortcuts.",
    )
    review_export.add_argument(
        "--db",
        default=".photos-data/photos.sqlite",
        help="SQLite database path.",
    )
    review_export.add_argument(
        "--output",
        default=".photos-data/review_package",
        help="Review package folder.",
    )
    review_export.add_argument(
        "--max-shortcuts",
        type=non_negative_int,
        default=250,
        help="Maximum shortcuts per queue.",
    )

    classification = sub.add_parser(
        "import-classification",
        help="Import external person/non-person labels.",
    )
    classification.add_argument(
        "csv",
        help="CSV with path,label and optional confidence,model,note columns.",
    )
    classification.add_argument(
        "--db",
        default=".photos-data/photos.sqlite",
        help="SQLite database path.",
    )

    decisions = sub.add_parser(
        "import-decisions",
        help="Import keep/delete choices from a review CSV.",
    )
    decisions.add_argument("csv", help="Edited decisions_template.csv or compatible review CSV.")
    decisions.add_argument(
        "--db",
        default=".photos-data/photos.sqlite",
        help="SQLite database path.",
    )

    decision_manifest = sub.add_parser(
        "decision-manifest",
        help="Write a manifest from reviewed delete choices.",
    )
    decision_manifest.add_argument(
        "--db",
        default=".photos-data/photos.sqlite",
        help="SQLite database path.",
    )
    decision_manifest.add_argument(
        "--output",
        default=".photos-data/decision_manifest.json",
        help="Manifest path.",
    )

    service_smoke_cmd = sub.add_parser(
        "service-smoke",
        help="Run the service-boundary smoke check on a media root.",
    )
    service_smoke_cmd.add_argument("root", help="Sample or media folder to scan.")
    service_smoke_cmd.add_argument("--db", default=".photos-data/photos.sqlite", help="SQLite database path.")
    service_smoke_cmd.add_argument("--output", default=".photos-data/service-smoke", help="Smoke output folder.")

    plan_create = sub.add_parser(
        "plan-create",
        help="Create an approval-gated archive execution plan.",
    )
    plan_create.add_argument(
        "archive_root_positional",
        nargs="?",
        metavar="ARCHIVE_ROOT",
        help="Archive destination root (backward-compatible positional form).",
    )
    plan_create.add_argument("--db", default=".photos-data/photos.sqlite", help="SQLite database path.")
    plan_create.add_argument(
        "--archive-root",
        help="Archive destination root (recommended form).",
    )
    plan_create.add_argument(
        "--strategy",
        default="date_archive_v1",
        help="Archive planning strategy.",
    )
    plan_create.add_argument(
        "--event-threshold",
        type=non_negative_int,
        default=10,
        help="Minimum same-date item count treated as an event folder.",
    )

    plan_actions = sub.add_parser("plan-actions", help="List actions for an archive plan.")
    plan_actions.add_argument("plan_id", type=non_negative_int, help="Plan ID.")
    plan_actions.add_argument("--db", default=".photos-data/photos.sqlite", help="SQLite database path.")
    plan_actions.add_argument("--status", default=None, help="Optional action status filter.")
    plan_actions.add_argument("--limit", type=non_negative_int, default=200, help="Maximum rows.")
    plan_actions.add_argument("--offset", type=non_negative_int, default=0, help="Rows to skip.")

    plan_dry_run = sub.add_parser("plan-dry-run", help="Validate a plan without moving files.")
    plan_dry_run.add_argument("plan_id", type=non_negative_int, help="Plan ID.")
    plan_dry_run.add_argument("--db", default=".photos-data/photos.sqlite", help="SQLite database path.")

    plan_approve = sub.add_parser("plan-approve", help="Approve or reject a plan for execution.")
    plan_approve.add_argument("plan_id", type=non_negative_int, help="Plan ID.")
    plan_approve.add_argument("--db", default=".photos-data/photos.sqlite", help="SQLite database path.")
    plan_approve.add_argument("--note", default="", help="Approval note.")
    plan_approve.add_argument(
        "--reject",
        action="store_true",
        help="Record a rejection instead of approval.",
    )

    plan_execute = sub.add_parser("plan-execute", help="Execute an approved plan.")
    plan_execute.add_argument("plan_id", type=non_negative_int, help="Plan ID.")
    plan_execute.add_argument("--db", default=".photos-data/photos.sqlite", help="SQLite database path.")
    plan_execute.add_argument(
        "--yes",
        action="store_true",
        help="Confirm runtime execution. Required for file movement.",
    )
    plan_execute.add_argument(
        "--no-verify-hashes",
        action="store_true",
        help="Skip post-copy hash verification.",
    )

    batch_list = sub.add_parser("batch-list", help="List execution batches.")
    batch_list.add_argument("--db", default=".photos-data/photos.sqlite", help="SQLite database path.")
    batch_list.add_argument("--plan-id", type=non_negative_int, default=None, help="Optional plan ID filter.")
    batch_list.add_argument("--limit", type=non_negative_int, default=100, help="Maximum rows.")
    batch_list.add_argument("--offset", type=non_negative_int, default=0, help="Rows to skip.")

    batch_items = sub.add_parser("batch-items", help="List execution batch items.")
    batch_items.add_argument("batch_id", type=non_negative_int, help="Batch ID.")
    batch_items.add_argument("--db", default=".photos-data/photos.sqlite", help="SQLite database path.")
    batch_items.add_argument("--limit", type=non_negative_int, default=500, help="Maximum rows.")
    batch_items.add_argument("--offset", type=non_negative_int, default=0, help="Rows to skip.")

    batch_manifest_validate = sub.add_parser(
        "batch-manifest-validate",
        help="Validate the latest manifest for a batch.",
    )
    batch_manifest_validate.add_argument("batch_id", type=non_negative_int, help="Batch ID.")
    batch_manifest_validate.add_argument("--db", default=".photos-data/photos.sqlite", help="SQLite database path.")
    batch_manifest_validate.add_argument(
        "--verify-files",
        action="store_true",
        help="Also verify completed destination files on disk.",
    )

    batch_reconcile = sub.add_parser("batch-reconcile", help="Reconcile a partial execution batch.")
    batch_reconcile.add_argument("batch_id", type=non_negative_int, help="Batch ID.")
    batch_reconcile.add_argument("--db", default=".photos-data/photos.sqlite", help="SQLite database path.")

    batch_resume = sub.add_parser("batch-resume", help="Resume retryable items from a batch.")
    batch_resume.add_argument("batch_id", type=non_negative_int, help="Batch ID.")
    batch_resume.add_argument("--db", default=".photos-data/photos.sqlite", help="SQLite database path.")
    batch_resume.add_argument(
        "--yes",
        action="store_true",
        help="Confirm runtime resume. Required for file movement.",
    )
    batch_resume.add_argument(
        "--no-verify-hashes",
        action="store_true",
        help="Skip post-copy hash verification.",
    )

    batch_rollback = sub.add_parser("batch-rollback", help="Rollback a completed execution batch.")
    batch_rollback.add_argument("batch_id", type=non_negative_int, help="Batch ID.")
    batch_rollback.add_argument("--db", default=".photos-data/photos.sqlite", help="SQLite database path.")
    batch_rollback.add_argument(
        "--yes",
        action="store_true",
        help="Confirm runtime rollback. Required for file movement.",
    )
    batch_rollback.add_argument(
        "--no-verify-hashes",
        action="store_true",
        help="Skip rollback hash verification.",
    )

    integrity_check = sub.add_parser("integrity-check", help="Run service integrity checks.")
    integrity_check.add_argument("--db", default=".photos-data/photos.sqlite", help="SQLite database path.")

    sub.add_parser("gui", help="Launch the root Tkinter desktop app.")
    return parser


def print_json(payload: dict) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _stderr_progress(payload: dict) -> None:
    print(json.dumps({"status": "progress", **payload}, sort_keys=True), file=sys.stderr)


def service_exit_code(result: dict, *, occurred_key: str | None = None) -> int:
    print_json(result)
    if not result.get("ok"):
        return 1
    if occurred_key is not None and not result.get("data", {}).get(occurred_key):
        return 1
    return 0


def service_data(result: dict) -> dict | None:
    if result.get("ok"):
        return result["data"]
    print_json(result)
    return None


def _interrupt_next_safe_action(command: str | None) -> str:
    return {
        "analyze": "analyze",
        "dry-run": "sample_dry_run",
        "hash": "hash_missing",
        "service-smoke": "service_smoke",
        "batch-reconcile": "reconcile_batch",
        "plan-execute": "execute_plan",
        "batch-resume": "resume_batch",
        "batch-rollback": "rollback_batch",
    }.get(command or "", "inspect_errors")


def interrupted_result(command: str | None) -> dict:
    return {
        "ok": False,
        "command": command or "unknown",
        "data": {},
        "errors": ["Interrupted by user"],
        "warnings": [
            "Operation interrupted; inspect the recorded batch state and resume if appropriate.",
        ],
        "next_safe_action": _interrupt_next_safe_action(command),
    }


def _main(argv: list[str] | None = None) -> int:
    global _LAST_COMMAND
    parser = build_parser()
    args = parser.parse_args(argv)
    _LAST_COMMAND = args.command

    if args.command == "check-env":
        return env_check_main([])

    if args.command == "dry-run":
        if not Path(args.root).expanduser().exists():
            parser.error(f"root does not exist: {args.root}")
        with PhotoOrganizerService(Path(args.db)) as service:
            data = service_data(
                service.sample_dry_run(
                    Path(args.root),
                    output_dir=Path(args.output),
                    free_bytes=args.free_bytes,
                    progress_callback=_stderr_progress,
                )
            )
        if data is None:
            return 1
        summary = data
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0

    if args.command == "analyze":
        if not Path(args.root).expanduser().exists():
            parser.error(f"root does not exist: {args.root}")
        with PhotoOrganizerService(Path(args.db)) as service:
            data = service_data(
                service.analyze(
                    Path(args.root),
                    output_dir=Path(args.output),
                    hash_files=not args.skip_hash,
                    top_folders=args.top_folders,
                    max_review_shortcuts=args.max_review_shortcuts,
                    max_detail_items=args.max_detail_items,
                    run_name="analysis",
                    progress_callback=_stderr_progress,
                )
            )
        if data is None:
            return 1
        summary = dict(data)
        summary.pop("folder_count", None)
        summary.pop("duplicate_candidates", None)
        summary.pop("date_audit", None)
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0

    if args.command == "hash":
        if not Path(args.db).exists():
            parser.error(f"database does not exist: {args.db}")
        with PhotoOrganizerService(Path(args.db)) as service:
            data = service_data(
                service.hash_missing(
                    max_files=args.max_files,
                    commit_interval=args.commit_interval,
                    progress_callback=_stderr_progress,
                )
            )
        if data is None:
            return 1
        print(
            json.dumps(
                {
                    "status": "ok",
                    "hashed": data["hashed"],
                    "backlog_before": data["backlog_before"],
                    "backlog_after": data["backlog_after"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.command == "report":
        if not Path(args.db).exists():
            parser.error(f"database does not exist: {args.db}")
        with PhotoOrganizerService(Path(args.db)) as service:
            data = service_data(
                service.write_management_report(
                    args.output,
                    top_folders=args.top_folders,
                    max_detail_items=args.max_detail_items,
                )
            )
        if data is None:
            return 1
        print(
            json.dumps(
                {
                    "status": "ok",
                    "output": args.output,
                    "review_queues": data["review_queues"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.command == "report-page":
        if not Path(args.db).exists():
            parser.error(f"database does not exist: {args.db}")
        with PhotoOrganizerService(Path(args.db)) as service:
            data = service_data(
                service.write_management_report_page(
                    args.output,
                    section=args.section,
                    page=args.page,
                    page_size=args.page_size,
                )
            )
        if data is None:
            return 1
        print(json.dumps({"status": "ok", "output": args.output, "total_pages": data["total_pages"]}, indent=2, sort_keys=True))
        return 0

    if args.command == "review-export":
        if not Path(args.db).exists():
            parser.error(f"database does not exist: {args.db}")
        with PhotoOrganizerService(Path(args.db)) as service:
            data = service_data(
                service.export_review_package(
                    args.output,
                    max_shortcuts_per_queue=args.max_shortcuts,
                )
            )
        if data is None:
            return 1
        print(json.dumps(data, indent=2, sort_keys=True))
        return 0

    if args.command == "import-classification":
        if not Path(args.db).exists():
            parser.error(f"database does not exist: {args.db}")
        if not Path(args.csv).exists():
            parser.error(f"classification CSV does not exist: {args.csv}")
        with PhotoOrganizerService(Path(args.db)) as service:
            data = service_data(service.import_classification_csv(args.csv))
        if data is None:
            return 1
        print(json.dumps({"status": "ok", "imported": data["imported"]}, indent=2, sort_keys=True))
        return 0

    if args.command == "import-decisions":
        if not Path(args.db).exists():
            parser.error(f"database does not exist: {args.db}")
        if not Path(args.csv).exists():
            parser.error(f"decision CSV does not exist: {args.csv}")
        with PhotoOrganizerService(Path(args.db)) as service:
            data = service_data(service.import_review_decisions(args.csv))
        if data is None:
            return 1
        print(json.dumps({"status": "ok", "imported": data["imported"]}, indent=2, sort_keys=True))
        return 0

    if args.command == "decision-manifest":
        if not Path(args.db).exists():
            parser.error(f"database does not exist: {args.db}")
        with PhotoOrganizerService(Path(args.db)) as service:
            data = service_data(service.write_decision_manifest(args.output))
        if data is None:
            return 1
        print(
            json.dumps(
                {
                    "status": "ok",
                    "output": args.output,
                    "candidate_count": data["candidate_count"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.command == "service-smoke":
        result = service_smoke(
            Path(args.root),
            db_path=Path(args.db),
            output_dir=Path(args.output),
            progress_callback=_stderr_progress,
        )
        return service_exit_code(result)

    if args.command == "plan-create":
        archive_root = args.archive_root
        if archive_root is None:
            archive_root = args.archive_root_positional
        elif (
            args.archive_root_positional is not None
            and Path(archive_root) != Path(args.archive_root_positional)
        ):
            parser.error("plan-create archive roots differ; provide only one archive root")
        if archive_root is None:
            parser.error("plan-create requires --archive-root ARCHIVE_ROOT (or positional ARCHIVE_ROOT)")
        with PhotoOrganizerService(Path(args.db)) as service:
            result = service.create_archive_plan(
                Path(archive_root),
                strategy=args.strategy,
                event_threshold=args.event_threshold,
            )
        return service_exit_code(result)

    if args.command == "plan-actions":
        with PhotoOrganizerService(Path(args.db)) as service:
            result = service.list_plan_actions(
                args.plan_id,
                status=args.status,
                limit=args.limit,
                offset=args.offset,
            )
        return service_exit_code(result)

    if args.command == "plan-dry-run":
        with PhotoOrganizerService(Path(args.db)) as service:
            result = service.dry_run_plan(args.plan_id, progress_callback=_stderr_progress)
        return service_exit_code(result)

    if args.command == "plan-approve":
        with PhotoOrganizerService(Path(args.db)) as service:
            result = service.approve_plan(
                args.plan_id,
                approved=not args.reject,
                note=args.note,
            )
        return service_exit_code(result)

    if args.command == "plan-execute":
        with PhotoOrganizerService(Path(args.db)) as service:
            result = service.execute_plan(
                args.plan_id,
                execute_approved=args.yes,
                verify_hashes=not args.no_verify_hashes,
                progress_callback=_stderr_progress,
            )
        return service_exit_code(result, occurred_key="executed")

    if args.command == "batch-list":
        with PhotoOrganizerService(Path(args.db)) as service:
            result = service.list_execution_batches(
                plan_id=args.plan_id,
                limit=args.limit,
                offset=args.offset,
            )
        return service_exit_code(result)

    if args.command == "batch-items":
        with PhotoOrganizerService(Path(args.db)) as service:
            result = service.list_batch_items(
                args.batch_id,
                limit=args.limit,
                offset=args.offset,
            )
        return service_exit_code(result)

    if args.command == "batch-manifest-validate":
        with PhotoOrganizerService(Path(args.db)) as service:
            result = service.validate_batch_manifest(
                args.batch_id,
                verify_files=args.verify_files,
            )
        return service_exit_code(result)

    if args.command == "batch-reconcile":
        with PhotoOrganizerService(Path(args.db)) as service:
            result = service.reconcile_batch(args.batch_id, progress_callback=_stderr_progress)
        return service_exit_code(result)

    if args.command == "batch-resume":
        with PhotoOrganizerService(Path(args.db)) as service:
            result = service.resume_batch(
                args.batch_id,
                execute_approved=args.yes,
                verify_hashes=not args.no_verify_hashes,
                progress_callback=_stderr_progress,
            )
        return service_exit_code(result, occurred_key="resumed")

    if args.command == "batch-rollback":
        with PhotoOrganizerService(Path(args.db)) as service:
            result = service.rollback_batch(
                args.batch_id,
                execute_approved=args.yes,
                verify_hashes=not args.no_verify_hashes,
                progress_callback=_stderr_progress,
            )
        return service_exit_code(result, occurred_key="rolled_back")

    if args.command == "integrity-check":
        with PhotoOrganizerService(Path(args.db)) as service:
            result = service.integrity_check()
        return service_exit_code(result)

    if args.command == "gui":
        from .gui import launch

        try:
            return launch()
        except RuntimeError as exc:
            parser.error(str(exc))

    parser.print_help()
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except KeyboardInterrupt:
        print_json(interrupted_result(_LAST_COMMAND))
        return 130
