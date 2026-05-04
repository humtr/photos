from __future__ import annotations

import sqlite3
from pathlib import Path

from .database import upsert_media_file
from .models import MediaRecord, is_supported_media, media_type_for_path


def scan_media(con: sqlite3.Connection, root: str | Path) -> int:
    root_path = Path(root).expanduser().resolve()
    if not root_path.exists():
        raise FileNotFoundError(root_path)
    if not root_path.is_dir():
        raise NotADirectoryError(root_path)

    count = 0
    for path in sorted(root_path.rglob("*")):
        if not path.is_file() or not is_supported_media(path):
            continue
        stat = path.stat()
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
        upsert_media_file(con, record)
        count += 1
    return count
