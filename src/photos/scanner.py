from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from collections.abc import Callable, Iterator
from typing import Any

from .database import mark_missing_media_files, record_scan_error, upsert_media_file, utc_now
from .models import MediaRecord, is_supported_media, media_type_for_path

FILE_ATTRIBUTE_REPARSE_POINT = 0x0400
PROGRESS_FRAME_INTERVAL = 1000


def _is_reparse_dir(entry: os.DirEntry[str]) -> bool:
    if os.name != "nt":
        return False
    try:
        st = entry.stat(follow_symlinks=False)
    except OSError:
        return False
    file_attrs = getattr(st, "st_file_attributes", 0)
    return bool(file_attrs & FILE_ATTRIBUTE_REPARSE_POINT)


def _iter_media_candidates(
    root_path: Path,
) -> Iterator[tuple[Path, os.stat_result | None, OSError | None]]:
    stack = [root_path]
    while stack:
        directory = stack.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    path = Path(entry.path)
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            if _is_reparse_dir(entry):
                                continue
                            stack.append(path)
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        if not is_supported_media(path):
                            continue
                        yield path, entry.stat(follow_symlinks=False), None
                    except OSError as exc:
                        yield path, None, exc
        except OSError as exc:
            yield Path(directory), None, exc


def _emit_progress(progress_callback: Callable[[dict[str, Any]], None] | None, payload: dict[str, Any]) -> None:
    if progress_callback is None:
        return
    try:
        progress_callback(payload)
    except Exception:
        pass


def _should_emit_progress(processed: int) -> bool:
    if processed <= 0:
        return False
    if processed == 1:
        return True
    return processed % PROGRESS_FRAME_INTERVAL == 0


def scan_media(
    con: sqlite3.Connection,
    root: str | Path,
    *,
    commit_interval: int = 1000,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> int:
    root_path = Path(root).expanduser().resolve()
    if not root_path.exists():
        raise FileNotFoundError(root_path)
    if not root_path.is_dir():
        raise NotADirectoryError(root_path)

    count = 0
    processed = 0
    scan_started_at = utc_now()
    scan_error_count = 0
    pending_writes = 0
    _emit_progress(
        progress_callback,
        {
            "operation": "scan_media",
            "phase": "starting",
            "root": str(root_path),
            "scanned": 0,
            "scan_errors": 0,
        },
    )
    for path, stat, error in _iter_media_candidates(root_path):
        processed += 1
        if error is not None:
            scan_error_count += 1
            record_scan_error(
                con,
                root=str(root_path),
                path=str(path),
                phase="scan",
                error=repr(error),
            )
            pending_writes += 1
            if commit_interval > 0 and pending_writes >= commit_interval:
                con.commit()
                pending_writes = 0
            if _should_emit_progress(processed):
                _emit_progress(
                    progress_callback,
                    {
                        "operation": "scan_media",
                        "phase": "scanning",
                        "root": str(root_path),
                        "scanned": count,
                        "scan_errors": scan_error_count,
                        "status": "error",
                        "current_path": str(path),
                    },
                )
            continue
        if stat is None:
            continue
        rel_path = path.relative_to(root_path).as_posix()
        parent_key = path.parent.relative_to(root_path).as_posix().lower()
        record = MediaRecord(
            root=str(root_path),
            path=str(path),
            rel_path=rel_path,
            parent_key=parent_key,
            name=path.name,
            stem_key=path.stem.lower(),
            suffix=path.suffix.lower(),
            media_type=media_type_for_path(path),
            size_bytes=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
        )
        upsert_media_file(con, record, seen_at=scan_started_at)
        count += 1
        pending_writes += 1
        if _should_emit_progress(processed):
            _emit_progress(
                progress_callback,
                {
                    "operation": "scan_media",
                    "phase": "scanning",
                    "root": str(root_path),
                    "scanned": count,
                    "scan_errors": scan_error_count,
                    "status": "recorded",
                    "current_path": str(path),
                },
            )
        if commit_interval > 0 and pending_writes >= commit_interval:
            con.commit()
            pending_writes = 0
    if scan_error_count == 0:
        mark_missing_media_files(con, root=str(root_path), scan_started_at=scan_started_at)
    con.commit()
    _emit_progress(
        progress_callback,
        {
            "operation": "scan_media",
            "phase": "completed",
            "root": str(root_path),
            "scanned": count,
            "scan_errors": scan_error_count,
        },
    )
    return count
