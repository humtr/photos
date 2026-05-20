from __future__ import annotations

import argparse
import json
from contextlib import closing
from pathlib import Path

from .classification import import_classification_csv
from .database import connect
from .dry_run import run_media_analysis, run_sample_dry_run
from .env_check import main as env_check_main
from .hashing import compute_missing_hashes, hash_backlog
from .reports import write_management_report
from .review import export_review_package, import_review_decisions, write_decision_manifest


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

    sub.add_parser("gui", help="Launch the optional PySide6 desktop scaffold.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "check-env":
        return env_check_main([])

    if args.command == "dry-run":
        if not Path(args.root).expanduser().exists():
            parser.error(f"root does not exist: {args.root}")
        summary = run_sample_dry_run(
            Path(args.root),
            db_path=Path(args.db),
            output_dir=Path(args.output),
            free_bytes=args.free_bytes,
        )
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0

    if args.command == "analyze":
        if not Path(args.root).expanduser().exists():
            parser.error(f"root does not exist: {args.root}")
        summary = run_media_analysis(
            Path(args.root),
            db_path=Path(args.db),
            output_dir=Path(args.output),
            hash_files=not args.skip_hash,
            top_folders=args.top_folders,
            max_review_shortcuts=args.max_review_shortcuts,
            run_name="analysis",
        )
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0

    if args.command == "hash":
        if not Path(args.db).exists():
            parser.error(f"database does not exist: {args.db}")
        with closing(connect(Path(args.db))) as con:
            before = hash_backlog(con)
            hashed = compute_missing_hashes(
                con,
                max_files=args.max_files,
                commit_interval=args.commit_interval,
            )
            after = hash_backlog(con)
        print(
            json.dumps(
                {
                    "status": "ok",
                    "hashed": hashed,
                    "backlog_before": before,
                    "backlog_after": after,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.command == "report":
        if not Path(args.db).exists():
            parser.error(f"database does not exist: {args.db}")
        with closing(connect(Path(args.db))) as con:
            report = write_management_report(con, args.output, top_folders=args.top_folders)
        print(
            json.dumps(
                {
                    "status": "ok",
                    "output": args.output,
                    "review_queues": report["review_queues"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.command == "review-export":
        if not Path(args.db).exists():
            parser.error(f"database does not exist: {args.db}")
        with closing(connect(Path(args.db))) as con:
            summary = export_review_package(
                con,
                args.output,
                max_shortcuts_per_queue=args.max_shortcuts,
            )
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0

    if args.command == "import-classification":
        if not Path(args.db).exists():
            parser.error(f"database does not exist: {args.db}")
        if not Path(args.csv).exists():
            parser.error(f"classification CSV does not exist: {args.csv}")
        with closing(connect(Path(args.db))) as con:
            imported = import_classification_csv(con, args.csv)
        print(json.dumps({"status": "ok", "imported": imported}, indent=2, sort_keys=True))
        return 0

    if args.command == "import-decisions":
        if not Path(args.db).exists():
            parser.error(f"database does not exist: {args.db}")
        if not Path(args.csv).exists():
            parser.error(f"decision CSV does not exist: {args.csv}")
        with closing(connect(Path(args.db))) as con:
            imported = import_review_decisions(con, args.csv)
        print(json.dumps({"status": "ok", "imported": imported}, indent=2, sort_keys=True))
        return 0

    if args.command == "decision-manifest":
        if not Path(args.db).exists():
            parser.error(f"database does not exist: {args.db}")
        with closing(connect(Path(args.db))) as con:
            manifest = write_decision_manifest(con, args.output)
        print(
            json.dumps(
                {
                    "status": "ok",
                    "output": args.output,
                    "candidate_count": manifest["candidate_count"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.command == "gui":
        from .gui import launch

        try:
            return launch()
        except RuntimeError as exc:
            parser.error(str(exc))

    parser.print_help()
    return 0
