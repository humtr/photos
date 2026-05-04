from __future__ import annotations

import argparse
import json
from pathlib import Path

from .dry_run import run_sample_dry_run
from .env_check import main as env_check_main
from .database import connect
from .reports import write_management_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="photos")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("check-env", help="Report Python and external media-tool availability.")

    dry_run = sub.add_parser("dry-run", help="Run a non-destructive sample-folder pipeline.")
    dry_run.add_argument("root", help="Sample media folder to scan.")
    dry_run.add_argument("--db", default=".photos-data/photos.sqlite", help="SQLite database path.")
    dry_run.add_argument("--output", default=".photos-data/dry-run", help="Dry-run output folder.")
    dry_run.add_argument("--free-bytes", type=int, default=None, help="Override free-space value.")

    report = sub.add_parser("report", help="Write a file-management report from an existing DB.")
    report.add_argument("--db", default=".photos-data/photos.sqlite", help="SQLite database path.")
    report.add_argument("--output", default=".photos-data/report.json", help="Report JSON path.")
    report.add_argument("--top-folders", type=int, default=20, help="Folder summary limit.")

    sub.add_parser("gui", help="Launch the optional PySide6 desktop scaffold.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "check-env":
        return env_check_main([])

    if args.command == "dry-run":
        summary = run_sample_dry_run(
            Path(args.root),
            db_path=Path(args.db),
            output_dir=Path(args.output),
            free_bytes=args.free_bytes,
        )
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0

    if args.command == "report":
        if not Path(args.db).exists():
            parser.error(f"database does not exist: {args.db}")
        con = connect(Path(args.db))
        report = write_management_report(con, args.output, top_folders=args.top_folders)
        print(json.dumps({"status": "ok", "output": args.output, "review_queues": report["review_queues"]}, indent=2, sort_keys=True))
        return 0

    if args.command == "gui":
        from .gui import launch

        return launch()

    parser.print_help()
    return 0
