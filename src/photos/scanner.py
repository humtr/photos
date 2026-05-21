from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Iterator

from .database import mark_missing_media_files, record_scan_error, upsert_media_file, utc_now
from .models import MediaRecord, is_supported_media, media_type_for_path

FILE_ATTRIBUTE_REPARSE_POINT = 0x0400


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


def scan_media(con: sqlite3.Connection, root: str | Path) -> int:
    root_path = Path(root).expanduser().resolve()
    if not root_path.exists():
        raise FileNotFoundError(root_path)
    if not root_path.is_dir():
        raise NotADirectoryError(root_path)

    count = 0
    scan_started_at = utc_now()
    scan_error_count = 0
    for path, stat, error in _iter_media_candidates(root_path):
        if error is not None:
            scan_error_count += 1
            record_scan_error(
                con,
                root=str(root_path),
                path=str(path),
                phase="scan",
                error=repr(error),
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
    if scan_error_count == 0:
        mark_missing_media_files(con, root=str(root_path), scan_started_at=scan_started_at)
    con.commit()
    return count
