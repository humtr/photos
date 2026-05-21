from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATE_PATTERNS = [
    re.compile(r"(19\d{2}|20\d{2})[-_]?([01]\d)[-_]?([0-3]\d)"),
    re.compile(r"(19\d{2}|20\d{2})[-_]?([01]\d)"),
]


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def ensure_parent(path: Path) -> None:
    ensure_parent_dir(path)


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=True, sort_keys=True)


def safe_rel(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve()))


def is_within(child: Path, root: Path) -> bool:
    try:
        child.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def is_subpath(path: Path, root: Path) -> bool:
    return is_within(path, root)


def normalize_case_path(value: str) -> str:
    return os.path.normcase(os.path.normpath(value))


def parse_folder_date(text: str) -> str | None:
    for pattern in DATE_PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        y = int(m.group(1))
        mo = int(m.group(2))
        d = 1
        if len(m.groups()) >= 3 and m.group(3):
            d = int(m.group(3))
        try:
            return datetime(y, mo, d, tzinfo=timezone.utc).date().isoformat()
        except ValueError:
            return None
    return None


def parse_iso_date(text: str | None) -> str | None:
    if not text:
        return None
    if "T" in text:
        return text.split("T", 1)[0]
    return text


def ext_lower(name: str) -> str:
    return os.path.splitext(name)[1].lower()
