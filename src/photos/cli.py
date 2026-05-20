from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .duplicates import analyze_duplicates
from .place import enrich_places
from .reports import summarize
from .scan import run_scan
from .schemas import Message, envelope, utc_now_iso
from .store import connect, get_or_create_scan_root, init_db, latest_scan_root


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="photos")
    sub = p.add_subparsers(dest="command", required=True)

    init_p = sub.add_parser("init")
    init_p.add_argument("--db", default=".photos-data/photos.sqlite")

    scan_p = sub.add_parser("scan")
    scan_p.add_argument("--source", default=r"D:\\")
    scan_p.add_argument("--archive-root", default=r"D:\\PICTURES")
    scan_p.add_argument("--db", default=".photos-data/photos.sqlite")

    sum_p = sub.add_parser("summarize")
    sum_p.add_argument("--db", default=".photos-data/photos.sqlite")

    place_p = sub.add_parser("enrich-places")
    place_p.add_argument("--db", default=".photos-data/photos.sqlite")
    place_p.add_argument("--gps-mode", choices=["none", "summary", "raw"], default="summary")

    dup_p = sub.add_parser("analyze-duplicates")
    dup_p.add_argument("--db", default=".photos-data/photos.sqlite")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    started_at = utc_now_iso()
    db_path = Path(args.db)
    warnings: list[Message] = []
    errors: list[Message] = []
    summary: dict = {}
    artifacts: list[dict] = []
    ok = True

    try:
        conn = connect(db_path)
        init_db(conn)
        if args.command == "init":
            summary = {"initialized": True}
        elif args.command == "scan":
            source = Path(args.source)
            archive_root = Path(args.archive_root)
            root_id = get_or_create_scan_root(conn, str(source), str(archive_root), started_at)
            result = run_scan(conn, root_id, source)
            summary = {
                "scan_run_id": result.scan_run_id,
                "folder_count": result.folder_count,
                "file_count": result.file_count,
                "error_count": result.error_count,
            }
            if result.error_count:
                warnings.append(Message("scan_errors", f"{result.error_count} scan errors captured", phase="scan"))
        elif args.command == "summarize":
            root = latest_scan_root(conn)
            if not root:
                raise RuntimeError("no active scan root; run scan first")
            root_id = int(root["id"])
            summary = summarize(conn, root_id)
        elif args.command == "enrich-places":
            root = latest_scan_root(conn)
            if not root:
                raise RuntimeError("no active scan root; run scan first")
            root_id = int(root["id"])
            summary = enrich_places(conn, root_id, args.gps_mode)
        elif args.command == "analyze-duplicates":
            root = latest_scan_root(conn)
            if not root:
                raise RuntimeError("no active scan root; run scan first")
            root_id = int(root["id"])
            summary = analyze_duplicates(conn, root_id)
    except Exception as exc:
        ok = False
        errors.append(Message("command_failed", str(exc), phase=args.command, recoverable=False))

    out = envelope(args.command, str(db_path), started_at, ok=ok, summary=summary, artifacts=artifacts, warnings=warnings, errors=errors)
    json.dump(out, sys.stdout, ensure_ascii=True)
    sys.stdout.write("\n")
    return 0 if ok else 1
