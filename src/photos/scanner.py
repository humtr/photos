from __future__ import annotations

import sqlite3
from pathlib import Path

from .database import mark_missing_media_files, record_scan_error, upsert_media_file, utc_now
from .models import MediaRecord, is_supported_media, media_type_for_path


def scan_media(con: sqlite3.Connection, root: str | Path) -> int:
    root_path = Path(root).expanduser().resolve()
    if not root_path.exists():
        raise FileNotFoundError(root_path)
    if not root_path.is_dir():
        raise NotADirectoryError(root_path)

    count = 0
    scan_started_at = utc_now()
    for path in root_path.rglob("*"):
        if path.is_symlink():
            continue
        try:
            if not path.is_file() or not is_supported_media(path):
                continue
            stat = path.stat()
        except OSError as exc:
            record_scan_error(
                con,
                root=str(root_path),
                path=str(path),
                phase="scan",
                error=repr(exc),
            )
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
    mark_missing_media_files(con, root=str(root_path), scan_started_at=scan_started_at)
    con.commit()
    return count
