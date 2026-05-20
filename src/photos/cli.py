from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .approvals import approve_plan_execute
from .duplicates import analyze_duplicates
from .execution import dry_run, execute_plan
from .folder_packets import export_folder_packets
from .llm_review import import_review
from .metadata_audit import audit_dates
from .place import enrich_places
from .planning import build_plan
from .reports import summarize
from .scan import run_scan
from .schemas import Message, envelope, utc_now_iso
from .status import status_summary
from .store import Store, connect, get_or_create_scan_root, init_db, latest_scan_root


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

    audit_p = sub.add_parser("audit-dates")
    audit_p.add_argument("--db", default=".photos-data/photos.sqlite")

    exp_p = sub.add_parser("export-folder-packets")
    exp_p.add_argument("--db", default=".photos-data/photos.sqlite")
    exp_p.add_argument("--output", default=".photos-data/folder-packets")
    exp_p.add_argument("--gps-mode", choices=["none", "summary", "raw"], default="summary")

    imp_p = sub.add_parser("import-folder-review")
    imp_p.add_argument("--db", default=".photos-data/photos.sqlite")
    imp_p.add_argument("--input", required=True)

    plan_p = sub.add_parser("plan")
    plan_p.add_argument("--db", default=".photos-data/photos.sqlite")
    plan_p.add_argument("--archive-root", required=True)
    plan_p.add_argument("--strategy", default="hybrid")

    dry_p = sub.add_parser("dry-run")
    dry_p.add_argument("--db", default=".photos-data/photos.sqlite")
    dry_p.add_argument("--plan", default="latest")
    dry_p.add_argument("--reserve-bytes", type=int, default=0)
    dry_p.add_argument("--approve-execute", action="store_true")

    exec_p = sub.add_parser("execute")
    exec_p.add_argument("--db", default=".photos-data/photos.sqlite")
    exec_p.add_argument("--plan", default="latest")
    exec_p.add_argument("--execute-approved", action="store_true")
    exec_p.add_argument("--manifest-dir", default=".photos-data/manifests")
    exec_p.add_argument("--reports-dir", default=".photos-data/reports")
    exec_p.add_argument("--reserve-bytes", type=int, default=0)

    status_p = sub.add_parser("status")
    status_p.add_argument("--db", default=".photos-data/photos.sqlite")
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
        elif args.command == "audit-dates":
            root = latest_scan_root(conn)
            if not root:
                raise RuntimeError("no active scan root; run scan first")
            root_id = int(root["id"])
            summary = audit_dates(conn, root_id)
        elif args.command == "export-folder-packets":
            root = latest_scan_root(conn)
            if not root:
                raise RuntimeError("no active scan root; run scan first")
            root_id = int(root["id"])
            res = export_folder_packets(conn, root_id, Path(args.output), args.gps_mode)
            summary = {"packet_count": res["packet_count"]}
            artifacts.append({"type": "folder_packet_index", "path": res["index_path"], "sha256": res["index_sha256"]})
        elif args.command == "import-folder-review":
            root = latest_scan_root(conn)
            if not root:
                raise RuntimeError("no active scan root; run scan first")
            root_id = int(root["id"])
            source_root = Path(str(root["source_root"]))
            summary = import_review(conn, root_id, Path(args.input), source_root)
            if summary.get("rejected", 0):
                ok = False
                for e in summary.get("errors", []):
                    errors.append(
                        Message(
                            e.get("code", "import_error"),
                            e.get("message", "import error"),
                            phase=e.get("phase"),
                            path=e.get("path"),
                            recoverable=e.get("recoverable"),
                        )
                    )
        elif args.command == "plan":
            root = latest_scan_root(conn)
            if not root:
                raise RuntimeError("no active scan root; run scan first")
            root_id = int(root["id"])
            conn.execute("UPDATE scan_roots SET archive_root=? WHERE id=?", (str(args.archive_root), root_id))
            conn.commit()
            store = Store(db_path)
            try:
                plan_id = build_plan(store, root_id, strategy=args.strategy)
            finally:
                store.close()
            summary = {"plan_id": plan_id, "strategy": args.strategy}
        elif args.command == "dry-run":
            store = Store(db_path)
            try:
                if args.plan == "latest":
                    plan_id = store.latest_plan_id()
                else:
                    plan_id = int(args.plan)
                if args.approve_execute:
                    approve_plan_execute(store, plan_id, note="cli --approve-execute")
                result = dry_run(store, plan_id, reserve_bytes=args.reserve_bytes)
            finally:
                store.close()
            summary = result.to_dict()
            if not result.execute_allowed:
                ok = False
                errors.append(
                    Message(
                        "dry_run_blocked",
                        "dry-run blocked execution",
                        phase="dry-run",
                        recoverable=True,
                    )
                )
        elif args.command == "execute":
            store = Store(db_path)
            try:
                if args.plan == "latest":
                    plan_id = store.latest_plan_id()
                else:
                    plan_id = int(args.plan)
                result = execute_plan(
                    store,
                    plan_id=plan_id,
                    execute_approved_flag=bool(args.execute_approved),
                    manifest_dir=Path(args.manifest_dir),
                    reports_dir=Path(args.reports_dir),
                    reserve_bytes=args.reserve_bytes,
                )
            finally:
                store.close()
            summary = result.to_dict()
        elif args.command == "status":
            store = Store(db_path)
            try:
                summary = status_summary(store)
            finally:
                store.close()
    except Exception as exc:
        ok = False
        errors.append(Message("command_failed", str(exc), phase=args.command, recoverable=False))

    out = envelope(args.command, str(db_path), started_at, ok=ok, summary=summary, artifacts=artifacts, warnings=warnings, errors=errors)
    json.dump(out, sys.stdout, ensure_ascii=True)
    sys.stdout.write("\n")
    return 0 if ok else 1
