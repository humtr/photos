from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .utils import ensure_parent, file_sha256


def write_manifest_atomic(path: Path, payload: dict[str, Any]) -> tuple[str, str]:
    ensure_parent(path)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8", newline="") as fh:
        fh.write(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
        fh.flush()
        os.fsync(fh.fileno())
    tmp_path.replace(path)
    return str(path), file_sha256(path)
